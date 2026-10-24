'use strict';
(() => {
  const root=document.getElementById('card-pair');
  if (!root) return;
  if (root.dataset.signedIn !== 'yes') {
    document.getElementById('pair-reload').addEventListener('click',()=>location.reload()); return;
  }
  const status=document.getElementById('pair-status'), button=document.getElementById('pair-approve');
  const code=location.hash.slice(1);
  history.replaceState(null,'',location.pathname);
  async function callback(action) {
    const body=new URLSearchParams({csrf:root.dataset.csrf,pair_code:code});
    const response=await fetch('/account/cards/pair/'+action,{method:'POST',credentials:'same-origin',cache:'no-store',body});
    if (!response.ok) throw Error('Pairing is unavailable or expired. Ask the terminal to show a new code.');
    return response.json();
  }
  let busy=false;
  button.addEventListener('click',async()=>{
    if(busy)return; busy=true;button.disabled=true;
    try {await callback('approve');status.textContent='Approved. Return to the terminal to prepare and write your card.';}
    catch(error){status.textContent=error.message;button.disabled=false;busy=false;}
  });
  (async()=>{
    try {
      if(!/^ogpair1\.[a-f0-9]{32}\.[A-Za-z0-9_-]{43}$/.test(code))throw Error('Scan a fresh pairing code from the terminal.');
      const detail=await callback('details');
      document.getElementById('pair-details').textContent=`${detail.terminal_name} · ${detail.pair_code}`;
      button.disabled=false;
    } catch(error){status.textContent=error.message;}
  })();
})();
