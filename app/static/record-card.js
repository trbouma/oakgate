'use strict';
(() => {
 const form=document.querySelector('[data-record-card]');if(!form)return;
 const button=form.querySelector('button'),status=form.querySelector('[role="status"]');
 button.hidden=!(isSecureContext && typeof window.NDEFReader==='function');
 let active=null,timer;
 function stop(){if(active)active.abort();active=null;clearTimeout(timer);button.disabled=false;}
 button.addEventListener('click',async()=>{
  if(active)return;
  const controller=new AbortController();active=controller;button.disabled=true;
  status.textContent=button.dataset.prompt;
  timer=setTimeout(()=>{if(active===controller){stop();status.textContent=button.dataset.error;}},30000);
  try {
   const reader=new window.NDEFReader();
   reader.onreading=({message})=>{
    if(active!==controller)return;
    const records=message?.records,r=records?.[0];stop();
    if(records?.length!==1 || r.recordType!=='mime' || r.mediaType!=='application/vnd.oakgate.card' || !r.data || r.data.byteLength<100 || r.data.byteLength>400){status.textContent=button.dataset.error;return;}
    form.elements.card.value=btoa(String.fromCharCode(...new Uint8Array(r.data.buffer,r.data.byteOffset,r.data.byteLength)));
    button.disabled=true;form.requestSubmit();
   };
   reader.onreadingerror=()=>{if(active===controller){stop();status.textContent=button.dataset.error;}};
   await reader.scan({signal:controller.signal});
  } catch(_){if(active===controller){stop();status.textContent=button.dataset.error;}}
 });
 addEventListener('pagehide',stop);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
})();
