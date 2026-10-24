const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const nodes={},readers=[],calls=[],events={},timers=new Map();let n=0,resolve;
 const el=id=>nodes[id]||={hidden:false,disabled:false,textContent:'',listeners:{},addEventListener(e,f){this.listeners[e]=f;}};
 class Reader{constructor(){readers.push(this);}async scan(o){this.options=o;}}
 const ctx={window:{NDEFReader:Reader},isSecureContext:true,AbortController,Uint8Array,btoa,
 document:{getElementById:el,addEventListener:(e,f)=>events[e]=f},addEventListener:(e,f)=>events[e]=f,
 setTimeout:f=>{timers.set(++n,f);return n;},clearTimeout:n=>timers.delete(n)};
 vm.runInNewContext(fs.readFileSync('pos/static/card-balance.js','utf8'),ctx);
 ctx.window.startPOSCardBalance(async(op,data)=>{calls.push({op,data});return await new Promise(r=>resolve=r);});
 const read=()=>({message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(new Uint8Array(180).buffer,10,160)}]}});
 return {el,ctx,readers,calls,events,timers,read,click:id=>el(id).listeners.click(),resolve:r=>resolve(r)};
}
test('card is not sent until confirmation; display local currency and sats and clear on Done',async()=>{
 const f=fixture();await f.click('available-balance');f.readers[0].onreading(f.read());assert.equal(f.calls.length,0);
 const pending=f.click('card-balance-confirm');await f.click('card-balance-confirm');assert.equal(f.calls.length,1);
 assert.equal(f.calls[0].op,'card-balance');assert.equal(Buffer.from(f.calls[0].data.card_payload,'base64').length,160);
 f.resolve({sats:1234,local:{symbol:'$',amount:'1.23',code:'CAD'}});await pending;
 assert.equal(f.el('card-balance-local').textContent,'$1.23 CAD');assert.match(f.el('card-balance-sats').textContent,/1,234 sats/);
 await f.click('card-balance-close');assert.equal(f.el('card-balance-local').textContent,'');
});
test('cancel and visibility changes discard late scans and balance responses',async()=>{
 const f=fixture();await f.click('available-balance');await f.click('card-balance-close');f.readers[0].onreading(f.read());
 await f.click('card-balance-confirm');assert.equal(f.calls.length,0);assert.equal(f.readers[0].options.signal.aborted,true);
 await f.click('available-balance');f.readers[1].onreading(f.read());const pending=f.click('card-balance-confirm');
 f.ctx.document.hidden=true;f.events.visibilitychange();f.resolve({sats:50,local:null});await pending;
 assert.equal(f.el('card-balance-sats').textContent,'');assert.equal(f.el('card-balance-panel').hidden,true);
});
test('wrong MIME, timeout and unsupported hardware cannot query balances',async()=>{
 const f=fixture();await f.click('available-balance');const r=f.read();r.message.records[0].mediaType='text/plain';f.readers[0].onreading(r);
 await f.click('card-balance-confirm');assert.equal(f.calls.length,0);
 await f.click('card-balance-close');await f.click('available-balance');[...f.timers.values()][0]();
 assert.equal(f.readers[1].options.signal.aborted,true);
 await f.click('card-balance-close');f.ctx.window.NDEFReader=undefined;await f.click('available-balance');assert.equal(f.readers.length,2);
});
