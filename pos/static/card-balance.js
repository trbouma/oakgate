'use strict';
(() => {
  const $=id=>document.getElementById(id);
  $('available-balance').hidden=!(isSecureContext && typeof window.NDEFReader==='function');
  let signed, active, payload, timeout, generation=0, busy=false, visible=false, balances=null;
  const message=text=>$('card-balance-status').textContent=text;
  function stop(){if(active){active.abort();active=null;}clearTimeout(timeout);}
  function clear(){
    generation++;stop();payload=null;busy=false;visible=false;balances=null;
    $('card-balance-asset').replaceChildren();
    $('card-balance-confirm').hidden=true;$('card-balance-confirm').disabled=false;
    $('card-balance-local').textContent='';$('card-balance-sats').textContent='';
    $('card-balance-result').hidden=true;$('card-balance-panel').hidden=true;
    $('pos-payments').hidden=false;
  }
  $('available-balance').addEventListener('click',async()=>{
    if(visible)return;
    clear();visible=true;const run=generation;
    $('pos-payments').hidden=true;$('card-balance-panel').hidden=false;
    $('card-balance-close').textContent='Cancel';
    if(!isSecureContext || typeof window.NDEFReader!=='function'){
      message('Reading cards requires a compatible NFC-enabled browser, such as Chrome on Android.');return;
    }
    active=new AbortController();const controller=active;
    timeout=setTimeout(()=>{if(run===generation){stop();message('Card reading timed out. Cancel and try again.');}},30000);
    const reader=new window.NDEFReader();
    reader.onreading=({message:read})=>{
      if(run!==generation || active!==controller)return;
      const records=read?.records,r=records?.[0];stop();
      if(records?.length!==1 || r.recordType!=='mime' || r.mediaType!=='application/vnd.oakgate.card' || !r.data || r.data.byteLength<100 || r.data.byteLength>400){
        message('This is not an OakGate card. Cancel and try again.');return;
      }
      const bytes=new Uint8Array(r.data.buffer,r.data.byteOffset,r.data.byteLength);
      payload=btoa(String.fromCharCode(...bytes));
      message('Card read. Confirm to display its Cash and Clear balances on this terminal.');
      $('card-balance-confirm').hidden=false;
    };
    reader.onreadingerror=()=>{if(run===generation && active===controller){stop();message('Could not read the card. Cancel and try again.');}};
    message('Tap your OakGate card to read it.');
    try{await reader.scan({signal:controller.signal});}
    catch(_){if(run===generation && active===controller){stop();message('Could not start NFC. Check device support and browser permissions.');}}
  });
  $('card-balance-confirm').addEventListener('click',async()=>{
    if(busy || !payload || !visible)return;
    busy=true;const run=generation, card=payload;payload=null;
    $('card-balance-confirm').disabled=true;message('Checking available balance…');
    try{
      const result=await signed('card-balance',{card_payload:card,confirmed:'yes'});
      if(run!==generation)return;
      if(!Number.isSafeInteger(result.sats) || result.sats<0)throw Error();
      balances=result;
      const select=$('card-balance-asset');select.replaceChildren();
      const add=(value,label)=>{const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);};
      add('cash','Cash');
      for(const [i,asset] of (result.clear || []).entries()){
        const duplicate=result.clear.filter(a=>a.display_name===asset.display_name).length>1;
        add(String(i),asset.display_name+(duplicate ? ` · ${asset.display_unit} · ${asset.mint} · ${asset.unit}` : ''));
      }
      select.value='cash';renderBalance();
      $('card-balance-result').hidden=false;
      $('card-balance-close').textContent='Done';
      timeout=setTimeout(clear,60000);
    }catch(_){if(run===generation)message('Balance unavailable. The card may be expired, revoked or unverified, or the wallet may be busy. Cancel and tap again.');}
    finally{if(run===generation){busy=false;$('card-balance-confirm').hidden=true;}}
  });
  function renderBalance(){
    if(!balances)return;
    const value=$('card-balance-asset').value;
    if(value==='cash'){
      $('card-balance-local').textContent=balances.local ? `${balances.local.symbol}${balances.local.amount} ${balances.local.code}` : 'Local currency unavailable';
      $('card-balance-sats').textContent=`₿ ${balances.sats.toLocaleString()} sats`;
    }else{
      const asset=(balances.clear || [])[Number(value)];if(!asset)return;
      $('card-balance-local').textContent=BigInt(asset.amount).toLocaleString();
      $('card-balance-sats').textContent=asset.display_unit;
    }
    message(balances.clear_unavailable ? 'Clear balances are temporarily unavailable.' : 'Available balance');
  }
  $('card-balance-asset').addEventListener('change',renderBalance);
  $('card-balance-close').addEventListener('click',clear);
  addEventListener('pagehide',()=>{if(visible)clear();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden && visible)clear();});
  document.addEventListener('pos-session-end',()=>{if(visible)clear();});
  window.startPOSCardBalance=call=>{signed=call;};
})();
