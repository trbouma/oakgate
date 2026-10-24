const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const nodes={},events={},calls=[],bodies=[];let approveResolve,failSave=false;
 const el=id=>nodes[id]||={dataset:{signedIn:'yes',csrf:'csrf'},textContent:'',hidden:true,disabled:false,listeners:{},addEventListener(e,f){this.listeners[e]=f;}};
 const ctx={document:{hidden:false,getElementById:el,addEventListener:(e,f)=>events[e]=f},addEventListener:(e,f)=>events[e]=f,
 location:{hash:'#ogpair1.'+'a'.repeat(32)+'.'+'b'.repeat(43),pathname:'/account/cards/pair'},history:{replaceState(){}},URLSearchParams,
 fetch:async(url,options)=>{calls.push(url);bodies.push(options.body);if(url.endsWith('/approve'))return await new Promise(r=>approveResolve=r);return {ok:!(failSave&&url.endsWith('/pin-saved')),json:async()=>({terminal_name:'Desk',pair_code:'ABCDEF',state:'approved'})};}};
 vm.runInNewContext(fs.readFileSync('app/static/card-pair.js','utf8'),ctx);
 return {el,ctx,events,calls,bodies,fail:()=>failSave=true,resolve:()=>approveResolve({ok:true,json:async()=>({state:'pin_pending',pin:'0007'})}),click:id=>el(id).listeners.click()};
}
test('private PIN preserves leading zeros and disappears after acknowledgement',async()=>{
 const f=fixture();const pending=f.click('pair-approve');f.resolve();await pending;
 assert.equal(f.el('pair-pin').textContent,'0007');assert.equal(f.el('pair-pin-panel').hidden,false);
 await f.click('pair-pin-saved');assert.equal(f.el('pair-pin').textContent,'');assert.equal(f.el('pair-pin-panel').hidden,true);
});
test('failed acknowledgement permits retry without discarding the displayed PIN',async()=>{
 const f=fixture();const pending=f.click('pair-approve');f.resolve();await pending;f.fail();await f.click('pair-pin-saved');
 assert.equal(f.el('pair-pin').textContent,'0007');assert.equal(f.el('pair-pin-saved').disabled,false);
});
test('backgrounding clears PIN and a late response cannot redisplay it',async()=>{
 const f=fixture();const pending=f.click('pair-approve');f.ctx.document.hidden=true;f.events.visibilitychange();f.resolve();await pending;
 assert.equal(f.el('pair-pin').textContent,'');assert.equal(f.el('pair-pin-panel').hidden,true);
});

test('login enrollment defaults off and explicit selection is only sent on approval',async()=>{
 for(const checked of [false,true]){
  const f=fixture();f.el('pair-login-opt-in').checked=checked;
  const pending=f.click('pair-approve');assert.equal(f.el('pair-login-opt-in').disabled,true);f.resolve();await pending;
  const index=f.calls.findIndex(url=>url.endsWith('/approve'));
  assert.equal(f.bodies[index].get('enroll_login'),checked?'yes':'no');
  await f.click('pair-pin-saved');assert.equal(f.bodies.at(-1).has('enroll_login'),false);
 }
});
