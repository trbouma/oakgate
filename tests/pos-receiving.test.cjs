const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function fixture(storage=new Map(), nfc=false) {
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
  const readers=[];
  context.AbortController=AbortController; context.Uint8Array=Uint8Array;
  context.btoa=value=>Buffer.from(value,'binary').toString('base64');
  context.DOMParser=class {parseFromString(){return {documentElement:{localName:'svg',getAttribute:()=> '0 0 100 100',querySelectorAll:()=>[]}};}};
  context.document.createElementNS=()=>({setAttribute(){},append(){}});
  if(nfc){context.window.isSecureContext=true;context.window.NDEFReader=class {constructor(){readers.push(this);}async scan(options){this.signal=options.signal;}};}
  vm.runInNewContext(fs.readFileSync('pos/static/receiving.js','utf8'),context);
  return {nodes,make,timers,storage,readers,start:context.window.startPOSReceiving,submit:()=>make('receive-form').listeners.submit({preventDefault(){}})};
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

const cardEvent=()=>({message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(new ArrayBuffer(200))}]}});
test('NFC action hidden without browser support and shown for pending supported receipt',async()=>{
  for(const supported of [false,true]){
    const f=fixture(new Map(),supported);
    await f.start(async op=>op==='receive-config'?config:{state:'pending',code:'invoice',qr:'svg'},'terminal');
    f.make('amount').value='100';f.submit();await flush();
    assert.equal(f.make('pay-nfc').hidden,!supported);
  }
});
test('card tap submits only current receipt and only once without a PIN; receipt polling confirms',async()=>{
  const f=fixture(new Map(),true), payments=[];let release;
  await f.start(async(op,data)=>{
    if(op==='receive-config')return config;
    if(op==='card-pay'){payments.push(data);await new Promise(resolve=>release=resolve);return {state:'submitted'};}
    return {state:op==='receipt'?'detected':'pending',code:'invoice',qr:'svg'};
  },'terminal');
  f.make('amount').value='100';f.submit();await flush();
  await f.make('pay-nfc').listeners.click();const reader=f.readers[0];
  reader.onreading(cardEvent());reader.onreading(cardEvent());await flush();
  assert.equal(payments.length,1);assert.deepEqual(Object.keys(payments[0]).sort(),['card_payload','request_key']);
  assert.equal(reader.signal.aborted,true);assert.equal(f.make('new-request').disabled,true);
  assert.equal(f.make('receipt-code').hidden,true);
  release();await flush();assert.match(f.make('pay-nfc-status').textContent,/confirming receipt/);
  await [...f.timers.values()][0]();assert.equal(f.make('receipt-status').textContent,'Payment detected — confirming in background');
});
test('stopped NFC reader ignores a late card event',async()=>{
  const f=fixture(new Map(),true), payments=[];
  await f.start(async(op,data)=>op==='receive-config'?config:op==='card-pay'?(payments.push(data),{state:'submitted'}):{state:'pending',code:'invoice',qr:'svg'},'terminal');
  f.make('amount').value='100';f.submit();await flush();
  await f.make('pay-nfc').listeners.click();const reader=f.readers[0];
  f.make('stop-pay-nfc').listeners.click();reader.onreading(cardEvent());await flush();
  assert.equal(reader.signal.aborted,true);assert.equal(payments.length,0);
});

test('same-wallet rejection restores the original QR and allows a different card',async()=>{
  const f=fixture(new Map(),true), requests=[];
  await f.start(async(op,data)=>{
    if(op==='receive-config')return config;
    if(op==='card-pay'){requests.push(data);throw Object.assign(new Error('rejected'),{code:'same-wallet'});}
    return {state:'pending',code:'invoice',qr:'svg'};
  },'terminal');
  f.make('amount').value='100';f.submit();await flush();
  await f.make('pay-nfc').listeners.click();f.readers[0].onreading(cardEvent());await flush();
  assert.match(f.make('pay-nfc-status').textContent,/belongs to the receiving wallet/);
  assert.equal(f.make('pay-nfc').hidden,false);assert.equal(f.make('receipt-code').hidden,false);
  await f.make('pay-nfc').listeners.click();f.readers[1].onreading(cardEvent());await flush();
  assert.equal(requests.length,2);assert.equal(requests[0].request_key,requests[1].request_key);
});
test('unknown card failure does not unlock another debit attempt',async()=>{
  const f=fixture(new Map(),true);
  await f.start(async op=>{
    if(op==='receive-config')return config;
    if(op==='card-pay')throw new Error('timeout');
    return {state:'pending',code:'invoice',qr:'svg'};
  },'terminal');
  f.make('amount').value='100';f.submit();await flush();
  await f.make('pay-nfc').listeners.click();f.readers[0].onreading(cardEvent());await flush();
  assert.equal(f.make('pay-nfc').hidden,true);assert.equal(f.make('receipt-code').hidden,true);
  assert.match(f.make('pay-nfc-status').textContent,/could not be confirmed/);
});
