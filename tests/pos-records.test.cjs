const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const nodes={},events={},timers=new Map();let counter=0;
 const el=id=>nodes[id]||={hidden:true,disabled:false,value:id==='record-type'?'whoami':'',textContent:'',listeners:{},addEventListener(k,v){this.listeners[k]=v;},replaceChildren(){},removeAttribute(){},setAttribute(){},append(){}};
 const document={hidden:false,getElementById:el,addEventListener(k,v){events[k]=v;},createElementNS:()=>({setAttribute(){},append(){}})};
 const context={document,window:{},isSecureContext:true,addEventListener(){},CustomEvent:function(){},Date,Uint8Array,Blob,URL,atob,btoa,AbortController,
 setTimeout:fn=>{timers.set(++counter,fn);return counter;},clearTimeout:id=>timers.delete(id),DOMParser:class{parseFromString(){return {documentElement:{localName:'svg',getAttribute:()=> '0 0 100 100',querySelectorAll:()=>[]}};}}};
 vm.runInNewContext(fs.readFileSync('pos/static/records.js','utf8'),context);
 return {el,events,context,start:context.window.startPOSRecords,click:id=>el(id).listeners.click()};
}
const request={request_id:'test',expires:Date.now()/1000+120,qr:'<svg/>'};
test('new requests erase displayed record and NFC is absent on unsupported browsers',async()=>{
 const f=fixture();f.start(async op=>op==='record-start'?request:op==='record-status'?{state:'ready'}:{label:'whoami',contents:'<script>text only</script>'});
 await f.click('record-start');await f.click('record-present');
 assert.equal(f.el('record-contents').textContent,'<script>text only</script>');assert.equal(f.el('record-nfc').hidden,true);
 await f.click('record-start');assert.equal(f.el('record-result').hidden,true);assert.equal(f.el('record-contents').textContent,'');
});
test('a cancelled lookup cannot restore a previous record',async()=>{
 const f=fixture();let resolve;f.start(async op=>op==='record-start'?request:op==='record-present'?new Promise(r=>resolve=r):{state:'ready'});
 await f.click('record-start');const pending=f.click('record-present');f.click('record-cancel');resolve({label:'whoami',contents:'old result'});await pending;
 assert.equal(f.el('record-result').hidden,true);assert.equal(f.el('record-contents').textContent,'');
});
test('hiding or leaving the record tab clears sensitive display and cancels request',async()=>{
 const f=fixture(),calls=[];f.start(async op=>{calls.push(op);return op==='record-start'?request:op==='record-present'?{label:'whoami',contents:'private'}:{state:'ready'};});
 await f.click('record-start');await f.click('record-present');f.events['pos-tab-change']({detail:0});
 assert.equal(f.el('record-contents').textContent,'');assert.ok(calls.includes('record-cancel'));
 await f.click('record-start');await f.click('record-present');f.context.document.hidden=true;f.events.visibilitychange();assert.equal(f.el('record-result').hidden,true);
});
