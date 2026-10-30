'use strict';
(() => {
 function recordLabel(value){const parts=value.replace(/^\/+|\/+$/g,'').split('/');const fingerprint=[...parts].reverse().find(p=>/^[a-f0-9]{64}$/i.test(p));return fingerprint?fingerprint.slice(0,8).toUpperCase():parts.at(-1);}

 const $=id=>document.getElementById(id);
 let signed, id, requestedLabel, expires=0, generation=0, timer, expiryTimer, reader, imageURL, busy=false, displayGeneration=0;
 const message=text=>$('record-status').textContent=text;
 const nfc=()=>isSecureContext && typeof window.NDEFReader==='function';
 function stopNFC(){if(reader){reader.abort();reader=null;}}
 function clearDisplay(){
  displayGeneration++;
  window.oakgatePOSPDF?.clear();
  $('record-epub').replaceChildren();$('record-epub').hidden=true;
  if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;
  $('record-anchor-summary').replaceChildren();$('record-verification-details').open=false;
  $('record-result').hidden=true;$('record-image').hidden=true;$('record-image').removeAttribute('src');
  ['record-label','record-contents','record-verification','record-verification-summary','record-publishers','record-attachment-note'].forEach(name=>$(name).textContent='');
 }
 function clear(){
  generation++;clearTimeout(timer);clearTimeout(expiryTimer);stopNFC();clearDisplay();id=null;busy=false;
  $('record-choice').replaceChildren();$('record-choice-wrap').hidden=true;
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
 function ready(records=[]){
  $('record-choice').replaceChildren();
  for(const record of records){const option=document.createElement('option');option.value=record.id;option.textContent=recordLabel(record.label);$('record-choice').append(option);}
  $('record-choice-wrap').hidden=records.length<=1;
stopNFC();clearTimeout(timer);$('record-present').hidden=false;$('record-present').disabled=false;$('record-nfc').hidden=true;$('record-qr').hidden=true;message('Presentation ready. Select Show Record to display it.');}
 async function poll(run){
  if(run!==generation||!id)return;
  try{const result=await signed('record-status',{request_id:id});if(run!==generation)return;
   if(result.state==='ready'){ready(result.records);return;}
   if(result.state==='unavailable'){message('The record could not be prepared. Create a new request.');return;}
  }catch(_){if(run!==generation)return;message('Checking request status…');}
  timer=setTimeout(()=>poll(run),2000);
 }
 $('record-start').addEventListener('click',async()=>{
  if(!signed||busy)return;
  const parent=$('record-type').value;
  const child=$('record-subcategory').value.trim().replace(/^\/+|\/+$/g,'');
  const label=(child?parent+'/'+child:parent).toLowerCase();
  if(!['whoami','myinfo','emergency','health','benefits','member','pass'].includes(parent)||label.length>200||
     label.split('/').some(part=>!part||part==='.'||part==='..'||/[\x00-\x1f]/.test(part))){
   message('Enter a subcategory such as prescriptions or prescriptions/current.');return;
  }
  clear();busy=true;$('record-start').disabled=true;const run=generation;
  message('Creating request…');
  try{const result=await signed('record-start',{label});if(run!==generation)return;
   requestedLabel=label;id=result.request_id;expires=result.expires;qr(result.qr);$('record-cancel').hidden=false;$('record-nfc').hidden=!nfc();$('record-nfc').disabled=false;
   message('Ask the wallet holder to scan and approve, or request using their NFC card.');
   expiryTimer=setTimeout(()=>{if(run===generation){clear();message('Request expired. Create a new request.');}},Math.max(0,expires*1000-Date.now()));
   poll(run);
  }catch(_){if(run===generation)message('Request unavailable. Activate the terminal or try again shortly.');}
  finally{if(run===generation){busy=false;$('record-start').disabled=false;}}
 });
 $('record-nfc').addEventListener('click',async()=>{
  if(!id||busy||!nfc())return;
  busy=true;const run=generation,requestID=id;reader=new AbortController();const controller=reader;
  $('record-nfc').disabled=true;message(`Ask the holder to tap their card to present their ${requestedLabel} record.`);
  const scan=new window.NDEFReader();
  scan.onreading=async({message:read})=>{
   if(run!==generation||reader!==controller)return;
   stopNFC();const r=read?.records?.[0];
   try{
    if(read.records.length!==1||r.recordType!=='mime'||r.mediaType!=='application/vnd.oakgate.card'||!r.data||r.data.byteLength<100||r.data.byteLength>400)throw Error();
    message('Preparing presentation…');
    const card_payload=btoa(String.fromCharCode(...new Uint8Array(r.data.buffer,r.data.byteOffset,r.data.byteLength)));
    const result=await signed('record-nfc',{request_id:requestID,card_payload});if(run===generation)ready(result.records);
   }catch(_){if(run===generation)message('The card or matching record is unavailable. Create a new request.');}
   finally{if(run===generation){busy=false;$('record-nfc').disabled=false;}}
  };
  scan.onreadingerror=()=>{if(run===generation){stopNFC();busy=false;$('record-nfc').disabled=false;message('Could not read the card. Try again or cancel.');}};
  try{await scan.scan({signal:controller.signal});}catch(_){if(run===generation){stopNFC();busy=false;$('record-nfc').disabled=false;message('NFC unavailable. Check permissions or use the QR request.');}}
 });
 $('record-present').addEventListener('click',async()=>{
  if(!id||busy)return;clearDisplay();busy=true;const run=generation, display=displayGeneration;$('record-present').disabled=true;message('Acquiring record and verification information…');
  try{const payload={request_id:id};if($('record-choice').value)payload.record_id=$('record-choice').value;
   const result=await signed('record-present',payload);if(run!==generation||display!==displayGeneration)return;
   $('record-label').textContent=recordLabel(result.label);$('record-contents').textContent=result.contents;
   $('record-attachment-note').textContent=result.attachment_note || '';
   $('record-verification-summary').textContent=result.verification
    ? `OpenETR: ${String(result.verification.aggregate_state || 'unverifiable').replaceAll('_',' ')}`
    : 'No attached artifact to check with OpenETR.';
   $('record-verification').textContent=result.verification?JSON.stringify(result.verification,null,2):'No attached artifact to check with OpenETR.';
   const shortKey=value=>typeof value==='string' && value.startsWith('npub1') && value.length>16 ? `${value.slice(0,9)}...${value.slice(-4)}` : value;
   const publishers=result.publishers || [];
   for(const publisher of publishers){
    const block=document.createElement('div'), heading=document.createElement('p');
    const check=document.createElement('span'), name=document.createElement('strong'), statement=document.createElement('p');
    block.className='record-anchor';check.className='record-anchor-check';
    check.textContent='✓';check.setAttribute('role','img');check.setAttribute('aria-label','Anchor found');
    name.textContent=shortKey(publisher.name || publisher.signer || 'Unknown signer');
    statement.textContent=publisher.statement || '';
    heading.append(check, name);block.append(heading, statement);$('record-anchor-summary').append(block);
   }
   if(!publishers.length)$('record-anchor-summary').textContent=$('record-verification-summary').textContent;
   $('record-publishers').textContent=publishers.map(p=>{
    const lines=['Anchor signer', shortKey(p.name)];
    if(p.signer && p.signer!==p.name)lines.push(shortKey(p.signer));
    if(p.anchored_at)lines.push('', 'Anchored at', p.anchored_at);
    if(p.statement)lines.push('', 'Anchor statement', p.statement);
    const profile=p.profile || {};
    const fields=['name','display_name','about','address'].filter(field=>profile[field]);
    if(fields.length)lines.push('', 'Anchor Signer Profile', ...fields.map(field=>`${field}: ${profile[field]}`));
    return lines.join('\n');
   }).join('\n\n');
   if(result.attachment?.type==='application/epub+zip' && Array.isArray(result.attachment.book?.chapters)){
    const container=$('record-epub'),book=result.attachment.book;
    const heading=document.createElement('h3');heading.textContent=book.title;container.append(heading);
    book.chapters.slice(0,200).forEach((chapter,index)=>{
     const section=document.createElement('details'),title=document.createElement('summary'),text=document.createElement('div');
     section.open=index===0;title.textContent=chapter.title;text.className='epub-text';text.textContent=chapter.text;
     section.append(title,text);container.append(section);
    });container.hidden=false;
   }
   if(result.attachment?.type==='application/pdf'){
    if(window.oakgatePOSPDF)window.oakgatePOSPDF.show(result.attachment.data);
    else $('record-attachment-note').textContent='PDF preview unavailable. Reload the terminal and create a new request.';
   }
   if(result.attachment && ['image/png','image/jpeg','image/webp','image/gif'].includes(result.attachment.type)){
    const bytes=Uint8Array.from(atob(result.attachment.data),c=>c.charCodeAt(0));
    imageURL=URL.createObjectURL(new Blob([bytes],{type:result.attachment.type}));$('record-image').src=imageURL;$('record-image').hidden=false;
   }
   $('record-result').hidden=false;$('record-present').hidden=true;message('Record presented. Review the record and verification information.' + (result.notification ? ' ' + result.notification : ''));
  }catch(_){if(run===generation&&display===displayGeneration){message('Presentation unavailable or expired. Create a new request.');$('record-present').disabled=false;}}
  finally{if(run===generation){busy=false;$('record-present').disabled=false;}}
 });
 $('record-choice').addEventListener('change',()=>{
  clearDisplay();$('record-present').hidden=false;$('record-present').disabled=busy;
  message('Select Show Record to display the selected record.');
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
