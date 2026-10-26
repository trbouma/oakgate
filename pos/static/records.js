'use strict';
(() => {
 const $=id=>document.getElementById(id);
 let signed, id, expires=0, generation=0, timer, expiryTimer, reader, imageURL, busy=false;
 const message=text=>$('record-status').textContent=text;
 const nfc=()=>isSecureContext && typeof window.NDEFReader==='function';
 function stopNFC(){if(reader){reader.abort();reader=null;}}
 function clearDisplay(){
  if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;
  $('record-result').hidden=true;$('record-image').hidden=true;$('record-image').removeAttribute('src');
  ['record-label','record-contents','record-verification','record-verification-summary','record-attachment-note'].forEach(name=>$(name).textContent='');
 }
 function clear(){
  generation++;clearTimeout(timer);clearTimeout(expiryTimer);stopNFC();clearDisplay();id=null;busy=false;
  $('record-qr').replaceChildren();$('record-qr').hidden=true;
  $('record-present').hidden=true;$('record-nfc').hidden=true;$('record-cancel').hidden=true;
  $('record-start').disabled=!signed;$('record-type').disabled=false;
 }
 function qr(source){
  const root=new DOMParser().parseFromString(source,'image/svg+xml').documentElement,view=root.getAttribute('viewBox');
  if(root.localName!=='svg'||!view||!/^[\d.\s-]+$/.test(view))throw Error();
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',view);svg.setAttribute('role','img');svg.setAttribute('aria-label','Record request QR code');
  for(const path of root.querySelectorAll('path')){const d=path.getAttribute('d');if(!d||!/^[MmLlHhVvZz\d.,\s-]+$/.test(d))throw Error();const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',d);p.setAttribute('fill','#000');svg.append(p);}
  $('record-qr').replaceChildren(svg);$('record-qr').hidden=false;
 }
 function ready(){stopNFC();clearTimeout(timer);$('record-present').hidden=false;$('record-present').disabled=false;$('record-nfc').hidden=true;$('record-qr').hidden=true;message('Presentation ready. Select Present Record to display it.');}
 async function poll(run){
  if(run!==generation||!id)return;
  try{const result=await signed('record-status',{request_id:id});if(run!==generation)return;
   if(result.state==='ready'){ready();return;}
   if(result.state==='unavailable'){message('The record could not be prepared. Create a new request.');return;}
  }catch(_){if(run!==generation)return;message('Checking request status…');}
  timer=setTimeout(()=>poll(run),2000);
 }
 $('record-start').addEventListener('click',async()=>{
  if(!signed||busy)return;
  clear();busy=true;$('record-start').disabled=true;const run=generation;
  message('Creating request…');
  try{const result=await signed('record-start',{label:$('record-type').value});if(run!==generation)return;
   id=result.request_id;expires=result.expires;qr(result.qr);$('record-cancel').hidden=false;$('record-nfc').hidden=!nfc();$('record-nfc').disabled=false;
   message('Ask the wallet holder to scan and approve, or request using their NFC card.');
   expiryTimer=setTimeout(()=>{if(run===generation){clear();message('Request expired. Create a new request.');}},Math.max(0,expires*1000-Date.now()));
   poll(run);
  }catch(_){if(run===generation)message('Request unavailable. Activate the terminal or try again shortly.');}
  finally{if(run===generation){busy=false;$('record-start').disabled=false;}}
 });
 $('record-nfc').addEventListener('click',async()=>{
  if(!id||busy||!nfc())return;
  busy=true;const run=generation,requestID=id;reader=new AbortController();const controller=reader;
  $('record-nfc').disabled=true;message('Ask the holder to tap their card to present their whoami record.');
  const scan=new window.NDEFReader();
  scan.onreading=async({message:read})=>{
   if(run!==generation||reader!==controller)return;
   stopNFC();const r=read?.records?.[0];
   try{
    if(read.records.length!==1||r.recordType!=='mime'||r.mediaType!=='application/vnd.oakgate.card'||!r.data||r.data.byteLength<100||r.data.byteLength>400)throw Error();
    message('Preparing presentation…');
    const card_payload=btoa(String.fromCharCode(...new Uint8Array(r.data.buffer,r.data.byteOffset,r.data.byteLength)));
    await signed('record-nfc',{request_id:requestID,card_payload});if(run===generation)ready();
   }catch(_){if(run===generation)message('The card or matching record is unavailable. Create a new request.');}
   finally{if(run===generation){busy=false;$('record-nfc').disabled=false;}}
  };
  scan.onreadingerror=()=>{if(run===generation){stopNFC();busy=false;$('record-nfc').disabled=false;message('Could not read the card. Try again or cancel.');}};
  try{await scan.scan({signal:controller.signal});}catch(_){if(run===generation){stopNFC();busy=false;$('record-nfc').disabled=false;message('NFC unavailable. Check permissions or use the QR request.');}}
 });
 $('record-present').addEventListener('click',async()=>{
  if(!id||busy)return;busy=true;const run=generation;$('record-present').disabled=true;message('Acquiring record and verification information…');
  try{const result=await signed('record-present',{request_id:id});if(run!==generation)return;
   clearDisplay();$('record-label').textContent=result.label;$('record-contents').textContent=result.contents;
   $('record-attachment-note').textContent=result.attachment_note || '';
   $('record-verification-summary').textContent=result.verification
    ? `OpenETR: ${String(result.verification.aggregate_state || 'unverifiable').replaceAll('_',' ')}. This does not by itself verify the holder’s identity or the truth of the record.`
    : 'No attached artifact to check with OpenETR.';
   $('record-verification').textContent=result.verification?JSON.stringify(result.verification,null,2):'No attached artifact to check with OpenETR. Presentation is not proof that its claims are true.';
   if(result.attachment && ['image/png','image/jpeg','image/webp','image/gif'].includes(result.attachment.type)){
    const bytes=Uint8Array.from(atob(result.attachment.data),c=>c.charCodeAt(0));
    imageURL=URL.createObjectURL(new Blob([bytes],{type:result.attachment.type}));$('record-image').src=imageURL;$('record-image').hidden=false;
   }
   $('record-result').hidden=false;$('record-present').hidden=true;message('Record presented. Review the record and verification information.');
  }catch(_){if(run===generation){message('Presentation unavailable or expired. Create a new request.');$('record-present').disabled=false;}}
  finally{if(run===generation)busy=false;}
 });
 function cancel(){const old=id;clear();message('Create a request to check a record.');if(old&&signed)signed('record-cancel',{request_id:old}).catch(()=>{});}
 $('record-cancel').addEventListener('click',cancel);
 document.addEventListener('pos-session-end',cancel);
 document.addEventListener('pos-tab-change',event=>{if(event.detail===0)cancel();});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});
 addEventListener('pagehide',()=>{clear();});
 window.refreshPOSRecordControls=()=>{$('record-start').disabled=!signed||busy;};
 window.startPOSRecords=call=>{signed=call;$('record-start').disabled=false;message('Create a request to check a record.');};
})();
