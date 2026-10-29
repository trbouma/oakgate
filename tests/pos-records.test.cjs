const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const nodes={},events={},timers=new Map();let counter=0;
 const el=id=>nodes[id]||={hidden:true,disabled:false,value:id==='record-type'?'whoami':'',textContent:'',listeners:{},addEventListener(k,v){this.listeners[k]=v;},children:[],replaceChildren(){this.children=[];this.textContent='';},removeAttribute(){},setAttribute(){},append(...items){this.children.push(...items);}};
 const document={hidden:false,getElementById:el,addEventListener(k,v){events[k]=v;},createElement:()=>el('created-'+(++counter)),createElementNS:()=>({setAttribute(){},append(){}})};
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
test('anchor publisher and statement render as text and clear with the request',async()=>{
 const f=fixture();f.start(async op=>op==='record-start'?request:op==='record-status'?{state:'ready'}:{label:'whoami',contents:'',verification:{aggregate_state:'anchored'},publishers:[{name:'Community Centre',statement:'<b>Membership confirmed</b>'}]});
 await f.click('record-start');await f.click('record-present');
 assert.equal(f.el('record-publishers').textContent,'Anchor signer\nCommunity Centre\n\nAnchor statement\n<b>Membership confirmed</b>');
 assert.equal(f.el('record-verification-summary').textContent,'OpenETR: anchored');
 const block=f.el('record-anchor-summary').children[0];
 assert.equal(block.children[0].children[0].textContent,'✓');
 assert.equal(block.children[0].children[1].textContent,'Community Centre');
 assert.equal(block.children[1].textContent,'<b>Membership confirmed</b>');
 assert.equal(f.el('record-verification-details').open,false);
 await f.click('record-cancel');assert.equal(f.el('record-publishers').textContent,'');assert.equal(f.el('record-anchor-summary').children.length,0);
});
test('multiple records expose a selector and selection changes discard an in-flight display',async()=>{
 const f=fixture();let resolve;const calls=[];
 f.start(async(op,payload)=>{calls.push([op,payload]);return op==='record-start'?request:op==='record-status'?{state:'ready',records:[{id:'dental',label:'benefits/dental'},{id:'health',label:'benefits/health'}]}:new Promise(r=>resolve=r);});
 f.el('record-type').value='benefits';await f.click('record-start');await Promise.resolve();
 assert.equal(f.el('record-choice-wrap').hidden,false);assert.equal(f.el('record-choice').children[0].textContent,'dental');
 f.el('record-choice').value='dental';const pending=f.click('record-present');
 assert.equal(calls.at(-1)[1].record_id,'dental');
 f.el('record-choice').value='health';f.el('record-choice').listeners.change();
 resolve({label:'benefits/dental',contents:'old'});await pending;
 assert.equal(f.el('record-result').hidden,true);assert.equal(f.el('record-contents').textContent,'');assert.equal(f.el('record-present').disabled,false);
});
test('one approved record never shows the selector',async()=>{
 const f=fixture();f.start(async op=>op==='record-start'?request:{state:'ready',records:[{id:'one',label:'benefits/dental'}]});
 f.el('record-type').value='benefits';await f.click('record-start');await Promise.resolve();assert.equal(f.el('record-choice-wrap').hidden,true);
});

test('POS shows fingerprint only while requesting the exact approved record',async()=>{
 const f=fixture();let selected;
 f.el('record-type').value='benefits';
 f.start(async(op,data)=>op==='record-start'?request:op==='record-status'?{state:'ready',records:[{id:'plain',label:'benefits/dental'},{id:'digest',label:'benefits/'+'a'.repeat(64)}]}:(selected=data,{label:'benefits/'+'a'.repeat(64),contents:'record'}));
 await f.click('record-start');await Promise.resolve();
 const options=f.el('record-choice').children;
 assert.equal(options[0].textContent,'dental');assert.equal(options[1].textContent,'aaaaaaaaaaaa…aaaaaaaa');
 f.el('record-choice').value='digest';await f.click('record-present');
 assert.equal(selected.record_id,'digest');assert.equal(f.el('record-label').textContent,'aaaaaaaaaaaa…aaaaaaaa');
});
