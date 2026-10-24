'use strict';
(() => {
 const $=id=>document.getElementById(id),button=$('send-card-read');if(!button)return;
 let active=null,timer;
 const status=text=>$('send-card-status').textContent=text;
 function stop(){if(active){active.abort();active=null;}clearTimeout(timer);button.disabled=false;}
 function reset(){stop();$('send-card-payload').value='';$('address').disabled=false;$('address').required=true;$('send-card-cancel').hidden=true;status('');}
 button.addEventListener('click',async()=>{
  if(active)return;reset();
  if(!isSecureContext || typeof window.NDEFReader!=='function'){status('Card reading requires a compatible NFC-enabled browser, such as Chrome on Android. You can still use a payment address.');return;}
  const controller=new AbortController();active=controller;button.disabled=true;$('send-card-cancel').hidden=false;
  timer=setTimeout(()=>{if(active===controller){reset();status('Card reading timed out. Try again.');}},30000);
  const reader=new window.NDEFReader();
  reader.onreading=({message})=>{
   if(active!==controller)return;
   const records=message?.records,r=records?.[0];stop();
   if(records?.length!==1 || r.recordType!=='mime' || r.mediaType!=='application/vnd.oakgate.card' || !r.data || r.data.byteLength<100 || r.data.byteLength>400){reset();status('This is not an OakGate payment card.');return;}
   const bytes=new Uint8Array(r.data.buffer,r.data.byteOffset,r.data.byteLength);
   $('send-card-payload').value=btoa(String.fromCharCode(...bytes));$('address').disabled=true;$('address').required=false;
   status('Card read. Enter the amount and choose Review payment to verify the recipient. No payment has been sent.');
  };
  reader.onreadingerror=()=>{if(active===controller){reset();status('Could not read the card. Try again.');}};
  status('Tap the recipient’s OakGate card.');
  try{await reader.scan({signal:controller.signal});}catch(_){if(active===controller){reset();status('NFC reading could not start. Check browser permissions.');}}
 });
 $('send-card-cancel').addEventListener('click',reset);
 button.closest('form').addEventListener('submit',()=>stop());
 addEventListener('pagehide',reset);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)reset();});
})();
