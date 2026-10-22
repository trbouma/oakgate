const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const KEY = 'ogpos1.' + 'a'.repeat(32) + '.' + 'b'.repeat(43);
function harness({deny=false, pending=false, camera=true}={}) {
  const elements={}, events={}, instances=[];
  let submitted=0, stopped=0, resolveStart;
  for (const id of ['activation','credential','scan-start','scan-stop','scan-preview','scan-video','scan-status']) {
    elements[id]={hidden:false,disabled:false,value:'',textContent:'',listeners:{},getAttribute:()=>null,
      addEventListener(event,fn){this.listeners[event]=fn;}};
  }
  elements.activation.requestSubmit=()=>submitted++;
  elements['scan-video'].srcObject={getTracks:()=>[{stop:()=>stopped++}]};
  class Scanner {
    constructor(video, callback, options){this.callback=callback;this.options=options;instances.push(this);}
    async start(){if(deny)throw Error('private camera details');if(pending)await new Promise(resolve=>resolveStart=resolve);}
    destroy(){this.destroyed=true;}
  }
  const document={getElementById:id=>elements[id],addEventListener:(name,fn)=>events[name]=fn};
  vm.runInNewContext(fs.readFileSync('pos/static/activation-scan.js','utf8').replace(/^import .*;\n/,''),
    {QrScanner:Scanner, document, window:{isSecureContext:true,addEventListener:(name,fn)=>events[name]=fn},
      navigator:{mediaDevices:camera?{getUserMedia(){}}:undefined}});
  return {elements,events,instances,document,start:()=>elements['scan-start'].listeners.click(),
    stop:()=>elements['scan-stop'].listeners.click(),complete:()=>resolveStart(),
    submitted:()=>submitted,stopped:()=>stopped};
}
test('camera starts only on request; valid code submits once and releases camera',async()=>{
  const h=harness();assert.equal(h.instances.length,0);
  await h.start();assert.equal(h.instances[0].options.preferredCamera,'environment');
  h.instances[0].callback({data:KEY});h.instances[0].callback({data:KEY});
  assert.equal(h.submitted(),1);assert.equal(h.elements.credential.value,KEY);
  assert.equal(h.stopped(),1);assert(h.instances[0].destroyed);assert(h.elements['scan-preview'].hidden);
});
test('reject unrelated QR codes and URLs without echoing or submitting their contents',async()=>{
  const h=harness();await h.start();
  for(const value of ['https://evil.example/?secret=test','nsec1private',KEY+'x','ogpos1.short','',null]) {
    h.instances[0].callback({data:value});assert.equal(h.submitted(),0);assert.equal(h.elements.credential.value,'');
  }
  assert.match(h.elements['scan-status'].textContent,/not an OakGate/);
});
test('permission denial and missing camera leave manual entry available',async()=>{
  for (const options of [{deny:true},{camera:false}]) {
    const h=harness(options);await h.start();assert.equal(h.submitted(),0);
    assert.equal(h.elements['scan-start'].disabled,false);
    assert.match(h.elements['scan-status'].textContent,/enter|Enter/);
  }
});
test('cancel during camera permission does not accept late callbacks or restart',async()=>{
  const h=harness({pending:true});const start=h.start();h.stop();
  h.instances[0].callback({data:KEY});assert.equal(h.submitted(),0);
  await h.start();assert.equal(h.instances.length,1);
  h.complete();await start;assert(h.elements['scan-preview'].hidden);assert(h.instances[0].destroyed);
});
test('manual activation, page hiding and backgrounding stop the camera',async()=>{
  for(const event of ['pos-activation-start','pagehide','visibilitychange']) {
    const h=harness();await h.start();
    if(event==='visibilitychange') h.document.hidden=true;
    h.events[event]();h.instances[0].callback({data:KEY});assert.equal(h.submitted(),0);assert.equal(h.stopped(),1);
  }
});
