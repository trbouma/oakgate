const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function fixture(storage=new Map()) {
  const nodes={}, timers=new Map(); let counter=0;
  const make=id=>nodes[id]||= {value:'',hidden:false,disabled:false,dataset:{},options:[],listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}, setAttribute(){},removeAttribute(){},dispatchEvent(){},
    replaceChildren(){this.options=[];}, add(option){this.options.push(option);},querySelectorAll(){return [];}};
  ['receive-form','asset','currency','amount','terminal','create-request','error','retry-request','refresh-options','new-request','qr-copy'].forEach(make);
  make('terminal').querySelectorAll=()=>['create-request','amount','asset','currency','retry-request','new-request'].map(make);
  make('receive-form').elements={amount:make('amount'),asset:make('asset'),currency:make('currency'),quoted_rate:{value:'150000'}};
  const context={window:{},document:{getElementById:make,createElement:()=>({}),head:{append:script=>script.onload()}},
    Option:function(text,value){return {text,value,dataset:{}};},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,v)=>storage.set(key,v),removeItem:key=>storage.delete(key)},
    crypto:{randomUUID:()=>`request-number-${++counter}`},Event:function(){},addEventListener(){},matchMedia:()=>({matches:true}),
    setTimeout:fn=>{const id=++counter;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
    setInterval:()=>++counter,clearInterval(){},navigator:{clipboard:{writeText:async()=>{}}}};
  vm.runInNewContext(fs.readFileSync('pos/static/receiving.js','utf8'),context);
  return {nodes,make,timers,storage,start:context.window.startPOSReceiving,submit:()=>make('receive-form').listeners.submit({preventDefault(){}})};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const config={cash_enabled:true,assets:[],currencies:[],currency:'SATS'};
test('double tap and uncertain retry reuse the persisted request',async()=>{
  const f=fixture(), sent=[]; let release;
  await f.start(async(op,data)=>{
    if(op==='receive-config')return config;
    sent.push(JSON.parse(JSON.stringify(data)));
    if(sent.length===1) await new Promise(resolve=>release=resolve);
    throw Error('connection lost');
  },'terminal');
  f.make('amount').value='100'; f.submit(); f.submit();
  await flush(); assert.equal(sent.length,1); assert.equal(f.make('create-request').disabled,true);
  release(); await flush();
  f.make('retry-request').listeners.click(); await flush();
  assert.equal(sent.length,2); assert.deepEqual(sent[0],sent[1]); assert.equal(f.make('retry-request').hidden,false);
  const next=fixture(f.storage), resumed=[];
  await next.start(async(op,data)=>op==='receive-config'?config:(resumed.push(data),{state:'unconfirmed'}),'terminal');
  assert.equal(resumed[0].request_key,sent[0].request_key);
});
test('detection stops polling and cancel cannot be overwritten by an in-flight status',async()=>{
  const f=fixture(); let release;
  await f.start(async(op)=>op==='receive-config'?config:op==='receive'?{state:'pending'}:new Promise(resolve=>release=resolve),'terminal');
  f.make('amount').value='1';f.submit();await flush();
  const poll=[...f.timers.values()][0];const pending=poll();await flush();
  f.make('new-request').listeners.click();assert.equal(f.make('receipt').hidden,true);
  release({state:'detected'});await pending;
  assert.equal(f.make('receipt').hidden,true);assert.equal(f.storage.size,0);
});
test('detected receipts stop checking and offer a new request',async()=>{
  const f=fixture();
  await f.start(async(op)=>op==='receive-config'?config:{state:op==='receive'?'pending':'detected'},'terminal');
  f.make('amount').value='1';f.submit();await flush();
  await [...f.timers.values()][0]();
  assert.equal(f.make('new-request').textContent,'New request');assert.equal(f.make('poll-progress').hidden,true);
});
