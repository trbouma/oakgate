'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const supported=()=>isSecureContext && typeof window.NDEFReader==='function';
  $('issue-card').hidden=!supported();
  const MIME='application/vnd.oakgate.card';
  let signed, storageKey, requestKey, prepared, active, timer, generation=0, busy=false, state='', deadline=0;
  function message(text){$('card-status').textContent=text;}
  function controls(){
    $('card-write').disabled=!supported() || !prepared || !!active || busy || !$('card-overwrite').checked;
    $('card-read').disabled=!supported() || !prepared || !!active || busy;
    $('card-prepare').disabled=busy;
    $('card-cancel').disabled=busy;
    $('card-refresh').disabled=busy;
    $('card-stop').hidden=!active;
    // Do not let the generic session controls race hardware verification.
    $('logout').disabled=!!active || busy;
  }
  function stopHardware(text){
    if(!active)return;
    const op=active; active=null; clearTimeout(op.timer); op.controller.abort();
    $('card-overwrite').checked=false;
    if(text)message(text);controls();
  }
  function stopPoll(){generation++;clearTimeout(timer);}
  function drawQR(source){
    const root=new DOMParser().parseFromString(source,'image/svg+xml').documentElement;
    const view=root.getAttribute('viewBox');
    if(root.localName!=='svg' || !view || !/^[\d.\s-]+$/.test(view))throw Error('Pairing QR unavailable.');
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',view);svg.setAttribute('role','img');svg.setAttribute('aria-label','Wallet pairing QR code');
    for(const path of root.querySelectorAll('path')){
      const d=path.getAttribute('d');if(!d || !/^[MmLlHhVvZz\d.,\s-]+$/.test(d))throw Error('Pairing QR unavailable.');
      const el=document.createElementNS(svg.namespaceURI,'path');el.setAttribute('d',d);el.setAttribute('fill','#000');svg.append(el);
    }
    $('card-qr').replaceChildren(svg);
  }
  function render(result){
    state=result.state;deadline=result.expires*1000;
    $('card-pair-code').textContent=result.pair_code || '';
    $('card-wallet').textContent=result.wallet_label ? `Wallet: ${result.wallet_label}` : '';
    $('card-qr').hidden=state!=='waiting';
    $('card-prepare').hidden=state!=='approved';
    $('card-hardware').hidden=state!=='prepared';
    $('card-refresh').hidden=['issued','cancelled','expired','revoked'].includes(state);
    $('card-cancel').textContent=state==='issued'?'Done':'Cancel issuance';
    const labels={waiting:'Scan this code with the OakGate wallet that will own the card. Compare the pairing code and approve.',
      approved:'Wallet approved. Check the wallet label, then prepare its card.',prepared:'Card prepared. Confirm the intended card, then write it. If a write was interrupted, read it back first.',
      issued:'Card verified and issued. You can now remove it.',cancelled:'Issuance cancelled.',expired:'Pairing expired. Start a new issuance.',revoked:'Card revoked. Start a new issuance.'};
    message(labels[state] || 'Check issuance status.');
    if(state==='waiting')drawQR(result.qr);
    prepared=state==='prepared'?result.payload:null;
    if(state==='issued'){sessionStorage.removeItem(storageKey);stopPoll();}
    controls();
  }
  async function operation(op,extra={}){
    return signed(op,{request_key:requestKey,...extra});
  }
  async function work(fn){
    if(busy || active)return;
    busy=true;controls();
    try {await fn();} catch(error){message(error.message || 'Could not confirm issuance. Check status before writing again.');$('card-refresh').hidden=false;}
    finally{busy=false;controls();}
  }
  function poll(){
    stopPoll();const run=generation;
    async function check(){
      if(run!==generation)return;
      if(deadline && Date.now()>=deadline){render({state:'expired'});return;}
      try{
        const result=await operation('card-status');
        if(run!==generation)return;
        render(result);
        if(result.state!=='waiting')return;
      }catch(_){if(run!==generation)return;message('Checking for wallet approval…');$('card-refresh').hidden=false;}
      timer=setTimeout(check,2000);
    }
    timer=setTimeout(check,2000);
  }
  async function open(){
    $('pos-payments').hidden=true;$('card-issuance').hidden=false;
    if(!supported()){message('Writing needs a compatible NFC-enabled browser over HTTPS, such as Chrome on Android.');$('card-refresh').hidden=true;return;}
    if(!requestKey){const candidate=crypto.randomUUID();sessionStorage.setItem(storageKey,candidate);requestKey=candidate;}
    message('Preparing pairing code…');
    const result=await operation('card-start');render(result);
    if(result.state==='waiting')poll();
  }
  $('issue-card').addEventListener('click',()=>work(open));
  $('card-prepare').addEventListener('click',()=>work(async()=>{stopPoll();render(await operation('card-prepare'));}));
  $('card-refresh').addEventListener('click',()=>work(async()=>{
    const result=await operation('card-start');render(result);if(result.state==='waiting')poll();
  }));
  $('card-cancel').addEventListener('click',()=>work(async()=>{
    stopPoll();
    if(requestKey && !['issued','expired','revoked'].includes(state))await operation('card-cancel');
    sessionStorage.removeItem(storageKey);requestKey=null;prepared=null;state='';
    $('card-qr').replaceChildren();$('card-issuance').hidden=true;$('pos-payments').hidden=false;
    $('card-overwrite').checked=false;
  }));
  function begin(){
    if(!supported() || active || busy || !prepared)return null;
    const op={controller:new AbortController()};active=op;
    op.timer=setTimeout(()=>{if(active===op)stopHardware('NFC timed out. Read the card before retrying a write.');},30000);
    controls();return op;
  }
  $('card-overwrite').addEventListener('change',controls);
  $('card-write').addEventListener('click',async()=>{
    if(!$('card-overwrite').checked)return;
    const op=begin();if(!op)return;
    try{
      const bytes=Uint8Array.from(atob(prepared),c=>c.charCodeAt(0));
      if(bytes.length<100 || bytes.length>400)throw Error('Invalid card payload');
      message('Present the intended card and hold it steady. Its existing contents will be replaced.');
      await new window.NDEFReader().write({records:[{recordType:'mime',mediaType:MIME,data:bytes}]},{overwrite:true,signal:op.controller.signal});
      if(active===op)stopHardware('Write completed. Remove the card, then choose Read back and verify and tap it again.');
    }catch(_){if(active===op)stopHardware('Write was not confirmed. Read the card before retrying; check NFC permission and card capacity.');}
  });
  $('card-read').addEventListener('click',async()=>{
    const op=begin();if(!op)return;
    try{
      const reader=new window.NDEFReader();
      reader.onreading=async({message:read})=>{
        if(active!==op)return;
        const records=read?.records,record=records?.[0];
        if(records?.length!==1 || record.recordType!=='mime' || record.mediaType!==MIME || !record.data || record.data.byteLength<100 || record.data.byteLength>400){stopHardware('This is not the prepared OakGate card. Nothing was submitted.');return;}
        const bytes=new Uint8Array(record.data.buffer,record.data.byteOffset,record.data.byteLength);
        const encoded=btoa(String.fromCharCode(...bytes));
        if(encoded!==prepared){stopHardware('This card does not match the prepared credential. Nothing was submitted.');return;}
        stopHardware('Card read. Confirming issuance…');
        await work(async()=>render(await operation('card-verify',{card_payload:encoded})));
      };
      reader.onreadingerror=()=>{if(active===op)stopHardware('Card could not be read. Remove it and try again.');};
      message('Tap the written card to read back and verify it.');
      await reader.scan({signal:op.controller.signal});
    }catch(_){if(active===op)stopHardware('NFC reading could not start. Check browser permissions and device support.');}
  });
  $('card-stop').addEventListener('click',()=>stopHardware('NFC cancelled. Read the card before retrying a write.'));
  const suspend=()=>{stopPoll();stopHardware('NFC paused. Read the card before retrying a write.');};
  addEventListener('pagehide',suspend);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});
  document.addEventListener('pos-session-end',suspend);
  window.refreshPOSCardControls=controls;
  window.startPOSCards=async(call,terminal)=>{
    signed=call;storageKey='oakgate-pos-card:'+terminal;requestKey=sessionStorage.getItem(storageKey);
    if(requestKey && supported())await work(open);
  };
})();
