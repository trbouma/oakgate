'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let signed, current, timer, tick, generation = 0, code = '', storageKey, loaded = false, working = false, celebrated = false;
  const labels = {pending:'Waiting for payment', unavailable:'Checking payment status', preparing:'Preparing request…',
    detected:'Payment detected — confirming in background', complete:'Received', expired:'Request expired',
    review:'Receipt needs review. Check transactions in OakGate.', unconfirmed:'Preparation could not be confirmed. No new request was created by retrying.'};
  function stop() { generation++; clearTimeout(timer); clearInterval(tick); }
  function remember(value) {
    // Storage is required before submitting: reloads must retain the same idempotency key.
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
    else sessionStorage.removeItem(storageKey);
    current = value;
  }
  function confetti() {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const layer = document.createElement('div'); layer.className = 'confetti'; layer.setAttribute('aria-hidden','true');
    for (let i=0;i<36;i++) { const piece=document.createElement('i'); layer.append(piece); }
    document.body.append(layer); setTimeout(() => layer.remove(), 2400);
  }
  function qr(svg) {
    // Accept only the server's QR path geometry; never insert arbitrary markup.
    const parsed = new DOMParser().parseFromString(svg, 'image/svg+xml');
    const root = parsed.documentElement;
    if (root.localName !== 'svg') throw new Error('QR unavailable. Check this request again.');
    const safe = document.createElementNS('http://www.w3.org/2000/svg','svg');
    const view = root.getAttribute('viewBox');
    if (!view || !/^[\d.\s-]+$/.test(view)) throw new Error('QR unavailable.');
    safe.setAttribute('viewBox',view); safe.setAttribute('role','img'); safe.setAttribute('aria-label','Payment request QR code');
    for (const path of root.querySelectorAll('path')) {
      const d = path.getAttribute('d');
      if (!d || !/^[MmLlHhVvZz\d.,\s-]+$/.test(d)) throw new Error('QR unavailable.');
      const el=document.createElementNS(safe.namespaceURI,'path'); el.setAttribute('d',d); el.setAttribute('fill','#000'); safe.append(el);
    }
    $('qr-copy').replaceChildren(safe);
  }
  function display(result) {
    $('receive-form').hidden=true; $('receipt').hidden=false;
    $('receipt-status').textContent=labels[result.state] || labels.unavailable;
    if (result.code && result.code !== code) { qr(result.qr); code=result.code; }
    $('receipt-name').textContent=result.display_name || 'Your request';
    $('receipt-amount').textContent=result.amount ? `${Number(result.amount).toLocaleString()} ${result.display_unit}` : '';
    const received=['detected','complete'].includes(result.state);
    const ended=received || ['review','expired','unconfirmed'].includes(result.state);
    $('receipt-code').hidden=!code || received;
    $('new-request').textContent=ended ? 'New request' : 'Cancel';
    $('cancel-note').hidden=received;
    if (ended) {
      stop(); $('poll-progress').hidden=true;
      $('retry-request').hidden=received || result.state === 'expired';
      if (received && !celebrated) { confetti(); celebrated=true; }
    }
    return ended;
  }
  function polling() {
    stop(); const run=generation, end=Date.now()+120000;
    $('poll-progress').hidden=false; $('retry-request').hidden=true;
    function progress() {
      const remaining=Math.max(0, Math.ceil((end-Date.now())/1000));
      $('poll-bar').value=120-remaining;
      $('poll-note').textContent=`Checking for ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} remaining`;
      if (!remaining) { stop(); $('poll-note').textContent='Checking paused. Payments continue to settle in the background.'; $('retry-request').hidden=false; }
    }
    tick=setInterval(progress,250); progress();
    async function poll() {
      try {
        const result=await signed('receipt',{request_key:current.request_key});
        if (run !== generation) return;
        if (display(result)) return;
      } catch (_) {
        if (run !== generation) return;
        $('receipt-status').textContent=labels.unavailable;
      }
      if (run===generation) timer=setTimeout(poll,1000);
    }
    timer=setTimeout(poll,1000);
  }
  async function work(action) {
    if (working) return;
    working=true; $('receive-form').setAttribute('aria-busy','true'); $('error').textContent='';
    const controls=[...$('terminal').querySelectorAll('button,select,input')];
    const prior=controls.map(el=>el.disabled); controls.forEach(el=>el.disabled=true);
    try { await action(); } catch(error) { $('error').textContent=error.message || 'Please try again.'; }
    finally { controls.forEach((el,i)=>el.disabled=prior[i]); $('receive-form').removeAttribute('aria-busy'); working=false; }
  }
  async function options() {
    const config=await signed('receive-config',{});
    $('asset').replaceChildren(); $('currency').replaceChildren();
    if (config.cash_enabled) { const o=new Option('Cash',''); o.dataset.unit='sats'; $('asset').add(o); }
    for (const a of config.assets) { const o=new Option(`${a.display_name} · ${a.display_unit}`,a.id); o.dataset.unit=a.display_unit; $('asset').add(o); }
    for (const c of config.currencies) { const o=new Option(`${c.code} · ${c.description}`,c.code); o.dataset.symbol=c.symbol; o.dataset.rate=c.fiat_per_btc; $('currency').add(o); }
    const sats=new Option('SATS','SATS'); sats.dataset.symbol='sats'; $('currency').add(sats);
    $('currency').value=config.currencies.some(c=>c.code===config.currency) ? config.currency : 'SATS';
    if (!loaded) {
      await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/shared/receive-keypad.js';script.onload=resolve;script.onerror=()=>reject(new Error('Keypad could not load. Reload this page.'));document.head.append(script);});
      loaded=true;
    } else $('asset').dispatchEvent(new Event('change'));
    $('create-request').disabled=!$('asset').options.length;
    if (config.clear_unavailable) $('error').textContent='Clear assets are temporarily unavailable. Refresh to try again.';
  }
  async function submitExisting() {
    stop(); code=''; display({state:'preparing'}); $('receipt-code').hidden=true;
    const run=generation;
    try {
      const result=await signed('receive',current);
      if (run===generation && !display(result)) polling();
    } catch(error) {
      if (run!==generation) return;
      $('receipt-status').textContent='Request not confirmed. Check this request again to safely retry.';
      $('retry-request').hidden=false; $('poll-progress').hidden=true;
      throw error;
    }
  }
  $('receive-form').addEventListener('submit',event=>{
    event.preventDefault(); work(async()=>{
      const form=$('receive-form');
      remember({request_key:crypto.randomUUID(), amount:form.elements.amount.value,
        asset:form.elements.asset.value, currency:form.elements.currency.value, quoted_rate:form.elements.quoted_rate.value});
      await submitExisting();
    });
  });
  $('retry-request').addEventListener('click',()=>work(submitExisting));
  $('refresh-options').addEventListener('click',()=>work(options));
  $('new-request').addEventListener('click',()=>{
    if (working) return;
    stop(); celebrated=false; remember(null); code=''; $('qr-copy').replaceChildren(); $('receipt').hidden=true; $('receive-form').hidden=false;
    $('amount').value=''; $('amount').dispatchEvent(new Event('input')); $('error').textContent='';
  });
  $('qr-copy').addEventListener('click', async()=>{
    try { await navigator.clipboard.writeText(code); $('copy-note').textContent='Copied.'; }
    catch (_) { $('copy-note').textContent='Copy unavailable. Scan the QR code instead.'; }
  });
  addEventListener('pagehide',stop);
  window.startPOSReceiving=async (caller, terminal)=>{
    signed=caller; storageKey='oakgate-pos-request:'+terminal;
    await options();
    const saved=sessionStorage.getItem(storageKey);
    if (saved) { current=JSON.parse(saved); await work(submitExisting); }
  };
})();
