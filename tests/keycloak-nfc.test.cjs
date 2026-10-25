const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
function fixture(supported=true){
 const nodes={},events={};let reader,timer;
 const node=id=>nodes[id]||={value:'',hidden:false,disabled:id==='nfc-submit',listeners:{},focus(){},addEventListener(k,f){this.listeners[k]=f;}};
 const window={isSecureContext:true,addEventListener:(k,f)=>events[k]=f};
 const document={hidden:false,getElementById:node,addEventListener:(k,f)=>events[k]=f};
 class Reader {constructor(){reader=this;}async scan(options){this.signal=options.signal;}}
 if(supported)window.NDEFReader=Reader;
 const ctx={window,document,NDEFReader:Reader,AbortController,Uint8Array,setTimeout:f=>{timer=f;return 1;},clearTimeout(){},btoa:s=>Buffer.from(s,'binary').toString('base64')};
 vm.runInNewContext(fs.readFileSync('keycloak/nfc/src/main/resources/theme-resources/resources/js/oakgate-nfc.js','utf8'),ctx);
 return {node,events,document,read:()=>node('nfc-read').listeners.click(),reader:()=>reader,timeout:()=>timer()};
}
test('unsupported browsers cannot start NFC login',()=>{
 const f=fixture(false);assert.equal(f.node('nfc-read').hidden,true);assert.equal(f.node('nfc-submit').disabled,true);
 assert.match(f.node('nfc-status').textContent,/Google or email/);
});
test('reader honors DataView offsets and stops once the card is read',async()=>{
 const f=fixture();await f.read();const bytes=Uint8Array.from([99,1,2,3,99]);
 f.reader().onreading({message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(bytes.buffer,1,3)}]}});
 assert.equal(f.node('nfc-card').value,Buffer.from([1,2,3]).toString('base64'));
 assert.equal(f.reader().signal.aborted,true);assert.equal(f.node('nfc-submit').disabled,false);
 let blocked=false;f.node('nfc-pin').value='123';f.node('oakgate-nfc').listeners.submit({preventDefault(){blocked=true;}});assert.equal(blocked,true);
 f.node('nfc-pin').value='0123';f.node('oakgate-nfc').listeners.submit({preventDefault(){assert.fail();}});
 assert.equal(f.node('nfc-submit').disabled,true);
});
test('backgrounding clears PIN and credential and ignores late reads',async()=>{
 const f=fixture();await f.read();f.node('nfc-pin').value='1234';f.document.hidden=true;f.events.visibilitychange();
 f.reader().onreading({message:{records:[{recordType:'mime',mediaType:'application/vnd.oakgate.card',data:new DataView(new ArrayBuffer(20))}]}});
 assert.equal(f.node('nfc-card').value,'');assert.equal(f.node('nfc-pin').value,'');assert.equal(f.node('nfc-submit').disabled,true);
});
test('timeout aborts reader and permits an explicit retry',async()=>{
 const f=fixture();await f.read();f.timeout();assert.equal(f.reader().signal.aborted,true);assert.equal(f.node('nfc-read').disabled,false);
 assert.equal(f.node('nfc-card').value,'');assert.equal(f.node('nfc-submit').disabled,true);
});

test('blank PIN is submitted for server-side policy enforcement',()=>{
 const f=fixture();f.node('nfc-card').value='encoded-card';f.node('nfc-pin').value='';
 f.node('oakgate-nfc').listeners.submit({preventDefault(){assert.fail('Blank PIN should reach the server');}});
 assert.equal(f.node('nfc-submit').disabled,true);
});
