const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const raw=new Uint8Array(160).fill(37), encoded=Buffer.from(raw).toString('base64');
function fixture({supported=true,writeWait=false}={}){
  const nodes={},readers=[],writes=[],calls=[],timers=new Map(),events={};let id=0,resolveWrite;
  const el=id=>nodes[id]||={hidden:false,disabled:false,checked:false,listeners:{},textContent:'',addEventListener(e,f){this.listeners[e]=f;},replaceChildren(){}};
  class Reader{constructor(){readers.push(this);}async scan(options){this.options=options;}async write(message,options){writes.push({message,options});if(writeWait)await new Promise(r=>resolveWrite=r);}}
  const storage=new Map();
  const ctx={window:{NDEFReader:supported?Reader:undefined},isSecureContext:true,AbortController,Uint8Array,atob,btoa,
    document:{getElementById:el,addEventListener:(e,f)=>events[e]=f},addEventListener:(e,f)=>events[e]=f,
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    crypto:{randomUUID:()=> 'request-key-000001'},setTimeout:f=>{timers.set(++id,f);return id;},clearTimeout:i=>timers.delete(i)};
  vm.runInNewContext(fs.readFileSync('pos/static/cards.js','utf8'),ctx);
  const call=async(op,data)=>{calls.push({op,data});return {state:op==='card-verify'?'issued':'prepared',payload:encoded,mime:'application/vnd.oakgate.card',expires:Date.now()/1000+600,pair_code:'ABCDEF',wallet_label:'Alice'};};
  return {nodes,el,readers,writes,calls,timers,events,storage,resolve:()=>resolveWrite(),init:()=>ctx.window.startPOSCards(call,'terminal'),click:async id=>el(id).listeners.click(),context:ctx};
}
function reading(bytes=raw,mime='application/vnd.oakgate.card'){
  const buffer=new Uint8Array(bytes.length+8);buffer.set(bytes,4);
  return {message:{records:[{recordType:'mime',mediaType:mime,data:new DataView(buffer.buffer,4,bytes.length)}]}};
}
test('write requires explicit consent and does not activate until a matching read-back',async()=>{
  const f=fixture();await f.init();await f.click('issue-card');
  assert.equal(f.readers.length,0);await f.click('card-write');assert.equal(f.writes.length,0);
  f.el('card-overwrite').checked=true;await f.click('card-write');
  assert.equal(f.writes.length,1);assert.equal(f.writes[0].options.overwrite,true);
  assert.deepEqual([...f.writes[0].message.records[0].data],[...raw]);
  assert.equal(f.calls.filter(c=>c.op==='card-verify').length,0);
  await f.click('card-read');await f.readers.at(-1).onreading(reading());
  assert.equal(f.calls.at(-1).op,'card-verify');assert.equal(f.calls.at(-1).data.card_payload,encoded);
  assert.match(f.el('card-status').textContent,/verified and issued/);assert.equal(f.storage.size,0);
});
test('wrong MIME or wrong card never reaches the server',async()=>{
  const f=fixture();await f.init();await f.click('issue-card');
  for(const event of [reading(raw,'application/vnd.safebox.card+cbor'),reading(new Uint8Array(160).fill(3)),{message:{records:[]}}]){
    await f.click('card-read');await f.readers.at(-1).onreading(event);
  }
  assert.equal(f.calls.filter(c=>c.op==='card-verify').length,0);
});
test('cancellation and hidden page abort hardware and ignore late results',async()=>{
  const f=fixture({writeWait:true});await f.init();await f.click('issue-card');
  f.el('card-overwrite').checked=true;const pending=f.click('card-write');
  await f.click('card-stop');assert.equal(f.writes[0].options.signal.aborted,true);
  f.resolve();await pending;assert.doesNotMatch(f.el('card-status').textContent,/Write completed/);
  await f.click('card-read');f.context.document.hidden=true;f.events.visibilitychange();
  await f.readers.at(-1).onreading(reading());assert.equal(f.calls.filter(c=>c.op==='card-verify').length,0);
});
test('unsupported browsers do not create a pairing or access hardware',async()=>{
  const f=fixture({supported:false});await f.init();await f.click('issue-card');
  assert.equal(f.calls.length,0);assert.match(f.el('card-status').textContent,/compatible NFC/);
});
test('timeout leaves the card unconfirmed and requires read-back',async()=>{
  const f=fixture();await f.init();await f.click('issue-card');await f.click('card-read');
  [...f.timers.values()][0]();assert.equal(f.readers[0].options.signal.aborted,true);
  assert.match(f.el('card-status').textContent,/timed out/);assert.equal(f.calls.filter(c=>c.op==='card-verify').length,0);
});
