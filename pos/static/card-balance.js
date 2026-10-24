'use strict';
(() => {
  const $=id=>document.getElementById(id);
  $('available-balance').hidden=!(isSecureContext && typeof window.NDEFReader==='function');
  let signed, active, payload, timeout, generation=0, busy=false, visible=false;
  const message=text=>$('card-balance-status').textContent=text;
  function stop(){if(active){active.abort();active=null;}clearTimeout(timeout);}
  function clear(){
    generation++;stop();payload=null;busy=false;visible=false;
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
      message('Card read. Confirm to display its cash balance on this terminal.');
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
      $('card-balance-local').textContent=result.local ? `${result.local.symbol}${result.local.amount} ${result.local.code}` : 'Local currency unavailable';
      $('card-balance-sats').textContent=`₿ ${result.sats.toLocaleString()} sats`;
      $('card-balance-result').hidden=false;message('Available cash balance');
      $('card-balance-close').textContent='Done';
      timeout=setTimeout(clear,60000);
    }catch(_){if(run===generation)message('Balance unavailable. The card may be expired, revoked or unverified, or the wallet may be busy. Cancel and tap again.');}
    finally{if(run===generation){busy=false;$('card-balance-confirm').hidden=true;}}
  });
  $('card-balance-close').addEventListener('click',clear);
  addEventListener('pagehide',()=>{if(visible)clear();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden && visible)clear();});
  document.addEventListener('pos-session-end',()=>{if(visible)clear();});
  window.startPOSCardBalance=call=>{signed=call;};
})();
