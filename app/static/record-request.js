'use strict';
(() => {
 function recordLabel(value){const parts=value.replace(/^\/+|\/+$/g,'').split('/');const fingerprint=[...parts].reverse().find(p=>/^[a-f0-9]{64}$/i.test(p));return fingerprint?fingerprint.slice(0,8).toUpperCase():parts.at(-1);}

 const root=document.getElementById('record-request');if(!root)return;
 if(root.dataset.signedIn!=='yes'){document.getElementById('record-request-reload').onclick=()=>location.reload();return;}
 const fragment=location.hash.slice(1),remote=fragment.startsWith('remote.'),id=remote?fragment.slice(7):fragment;history.replaceState(null,'',location.pathname);
 const status=document.getElementById('record-request-status'),button=document.getElementById('record-request-approve');
 let records=[];
 async function call(action){const body=new URLSearchParams({csrf:root.dataset.csrf,request_id:id});if(remote)body.set('remote','1');if(action==='approve')body.set('selected',JSON.stringify(records.length===1?[records[0].id]:Array.from(document.querySelectorAll('[data-record-choice]:checked'),node=>node.value))); const response=await fetch('/account/record-request/'+action,{method:'POST',credentials:'same-origin',cache:'no-store',body});if(!response.ok)throw Error('Request unavailable, expired, or no matching record was found. Ask the terminal for a new request.');return response.json();}
 let busy=false;
 button.onclick=async()=>{if(busy)return;busy=true;button.disabled=true;status.textContent='Preparing presentation…';try{await call('approve');status.textContent='Ready. The terminal can now display your approved records.';}catch(error){status.textContent=error.message;}};
 call('details').then(result=>{
  records=result.records;
  const multiple=records.length>1;
  document.getElementById('record-request-details').textContent=`${result.name} requests your ${recordLabel(result.label)} ${multiple?'records':'record'}.`;
  button.textContent=multiple?'Present selected records':`Present ${recordLabel(records[0].label)}`;
  if(multiple){
   document.getElementById('record-request-choices').hidden=false;
   const options=document.getElementById('record-request-options');
   for(const record of records){
    const label=document.createElement('label'), input=document.createElement('input'), text=document.createElement('span');
    label.className='record-request-option';input.type='checkbox';input.value=record.id;input.setAttribute('data-record-choice','');text.textContent=recordLabel(record.label);
    input.addEventListener('change',()=>{button.disabled=busy||!document.querySelector('[data-record-choice]:checked');});
    label.append(input,text);options.append(label);
   }
  }else button.disabled=false;
 }).catch(error=>status.textContent=error.message);
})();
