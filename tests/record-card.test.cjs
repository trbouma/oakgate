const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
function setup(supported=true){
 const handlers={},events={},status={},button={dataset:{prompt:'Tap',error:'Try again'},addEventListener:(n,f)=>handlers[n]=f};
 let reader,submitted=0;
 const form={elements:{card:{value:''}},querySelector:s=>s==='button'?button:status,requestSubmit:()=>submitted++};
 class Reader{constructor(){reader=this;}async scan(){}}
 vm.runInNewContext(fs.readFileSync('app/static/record-card.js','utf8'),{document:{querySelector:()=>form,addEventListener:(n,f)=>events[n]=f},window:{NDEFReader:supported?Reader:undefined},isSecureContext:true,AbortController,Uint8Array,btoa:s=>Buffer.from(s,'binary').toString('base64'),setTimeout:()=>1,clearTimeout:()=>{},addEventListener:(n,f)=>events[n]=f});
 return {button,status,form,events,click:()=>handlers.click(),reader:()=>reader,submitted:()=>submitted};
}
test('unsupported browser hides NFC action',()=>{assert.equal(setup(false).button.hidden,true);});
test('single card submits for review once and stops reading',async()=>{
 const p=setup();await p.click();assert.equal(p.button.disabled,true);
 const event={message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(new ArrayBuffer(150))}]}};
 p.reader().onreading(event);p.reader().onreading(event);
 assert.equal(p.submitted(),1);assert.ok(p.form.elements.card.value);
});
test('invalid record and reading error allow retry without submission',async()=>{
 const p=setup();await p.click();p.reader().onreading({message:{records:[]}});
 assert.equal(p.submitted(),0);assert.equal(p.button.disabled,false);
 await p.click();p.reader().onreadingerror();assert.equal(p.submitted(),0);assert.equal(p.button.disabled,false);
});
test('leaving page ignores late read events',async()=>{
 const p=setup();await p.click();p.events.pagehide();p.reader().onreading({message:{records:[]}});
 assert.equal(p.submitted(),0);assert.equal(p.button.disabled,false);
});
