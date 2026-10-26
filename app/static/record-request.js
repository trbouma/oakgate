'use strict';
(() => {
 const root=document.getElementById('record-request');if(!root)return;
 if(root.dataset.signedIn!=='yes'){document.getElementById('record-request-reload').onclick=()=>location.reload();return;}
 const id=location.hash.slice(1);history.replaceState(null,'',location.pathname);
 const status=document.getElementById('record-request-status'),button=document.getElementById('record-request-approve');
 async function call(action){const response=await fetch('/account/record-request/'+action,{method:'POST',credentials:'same-origin',cache:'no-store',body:new URLSearchParams({csrf:root.dataset.csrf,request_id:id})});if(!response.ok)throw Error('Request unavailable, expired, or no unique whoami record was found. Ask the terminal for a new request.');return response.json();}
 let busy=false;
 button.onclick=async()=>{if(busy)return;busy=true;button.disabled=true;status.textContent='Preparing presentation…';try{await call('approve');status.textContent='Ready. The terminal can now present your record.';}catch(error){status.textContent=error.message;}};
 call('details').then(result=>{document.getElementById('record-request-details').textContent=`${result.name} requests your ${result.label} record.`;button.disabled=false;}).catch(error=>status.textContent=error.message);
})();
