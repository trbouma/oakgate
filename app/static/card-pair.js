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
    if(action==='approve')body.set('enroll_login',document.getElementById('pair-login-opt-in').checked?'yes':'no');
    const response=await fetch('/account/cards/pair/'+action,{method:'POST',credentials:'same-origin',cache:'no-store',body});
    if (!response.ok) throw Error('Pairing is unavailable or expired. Ask the terminal to show a new code.');
    return response.json();
  }
  let busy=false, generation=0;
  button.addEventListener('click',async()=>{
    if(busy)return; busy=true;button.disabled=true;const run=generation;
    document.getElementById('pair-login-opt-in').disabled=true;
    try {
      const result=await callback('approve');
      if(run!==generation || document.hidden)return;
      if(result.state==='pin_pending'){
        document.getElementById('pair-pin').textContent=result.pin;
        document.getElementById('pair-pin-panel').hidden=false;
        status.textContent='Save your PIN separately from your card, then confirm below.';
      }else{status.textContent='Approved. Return to the terminal to prepare and write your card.';}
    }
    catch(error){status.textContent=error.message;button.disabled=false;busy=false;}
  });
  let saving=false;
  const saved=document.getElementById('pair-pin-saved');
  saved.addEventListener('click',async()=>{
    if(saving)return;saving=true;saved.disabled=true;
    try{
      await callback('pin-saved');
      document.getElementById('pair-pin').textContent='';
      document.getElementById('pair-pin-panel').hidden=true;
      status.textContent='PIN saved. Return to the terminal to prepare and write your card.';
    }catch(error){status.textContent=error.message;}
    finally{saving=false;saved.disabled=false;}
  });
  const hidePin=()=>{
    generation++;
    document.getElementById('pair-pin').textContent='';
    document.getElementById('pair-pin-panel').hidden=true;
    if(busy && !saving){busy=false;button.disabled=false;}
  };
  addEventListener('pagehide',hidePin);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)hidePin();});
  (async()=>{
    try {
      if(!/^ogpair1\.[a-f0-9]{32}\.[A-Za-z0-9_-]{43}$/.test(code))throw Error('Scan a fresh pairing code from the terminal.');
      const detail=await callback('details');
      document.getElementById('pair-details').textContent=`${detail.terminal_name} · ${detail.pair_code}`;
      button.disabled=false;
    } catch(error){status.textContent=error.message;}
  })();
})();
