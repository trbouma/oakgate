const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const nodes={},readers=[],events={},timers=new Map();let n=0;
 const el=id=>nodes[id]||={hidden:false,disabled:false,required:true,value:'',textContent:'',listeners:{},addEventListener(e,f){this.listeners[e]=f;},closest(){return el('form');}};
 class Reader{constructor(){readers.push(this);}async scan(o){this.options=o;}}
 const ctx={window:{NDEFReader:Reader},isSecureContext:true,AbortController,Uint8Array,btoa,
 document:{getElementById:el,addEventListener:(e,f)=>events[e]=f},addEventListener:(e,f)=>events[e]=f,
 setTimeout:f=>{timers.set(++n,f);return n;},clearTimeout:n=>timers.delete(n)};
 vm.runInNewContext(fs.readFileSync('app/static/send-card.js','utf8'),ctx);
 const read=()=>({message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(new Uint8Array(180).buffer,10,160)}]}});
 return {el,ctx,readers,events,timers,read,click:id=>el(id).listeners.click()};
}
test('card read only fills review form; respects view offsets and permits returning to address',async()=>{
 const f=fixture();await f.click('send-card-read');await f.click('send-card-read');assert.equal(f.readers.length,1);
 f.readers[0].onreading(f.read());assert.equal(f.el('address').disabled,true);assert.equal(f.el('address').required,false);
 assert.equal(Buffer.from(f.el('send-card-payload').value,'base64').length,160);
 assert.match(f.el('send-card-status').textContent,/No payment has been sent/);
 await f.click('send-card-cancel');assert.equal(f.el('send-card-payload').value,'');assert.equal(f.el('address').disabled,false);
});
test('cancel, backgrounding and timeout abort scans and ignore late results',async()=>{
 const f=fixture();await f.click('send-card-read');await f.click('send-card-cancel');f.readers[0].onreading(f.read());assert.equal(f.el('send-card-payload').value,'');
 await f.click('send-card-read');f.ctx.document.hidden=true;f.events.visibilitychange();assert.equal(f.readers[1].options.signal.aborted,true);
 await f.click('send-card-read');[...f.timers.values()][0]();f.readers[2].onreading(f.read());assert.equal(f.el('send-card-payload').value,'');
});
test('wrong MIME and unsupported browsers preserve address entry',async()=>{
 const f=fixture();await f.click('send-card-read');const r=f.read();r.message.records[0].mediaType='text/plain';f.readers[0].onreading(r);
 assert.equal(f.el('address').disabled,false);assert.equal(f.el('send-card-payload').value,'');
 f.ctx.window.NDEFReader=undefined;await f.click('send-card-read');assert.equal(f.readers.length,1);
});
