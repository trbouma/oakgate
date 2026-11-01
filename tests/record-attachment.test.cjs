const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/record-attachment.js','utf8');
test('existing attachment status follows selection, clearing, and restored pages',()=>{
  const events={};
  const input={files:[],addEventListener:(name,fn)=>events[name]=fn};
  const status={dataset:{retained:'Kept',replacement:'Replaced when saved'}};
  vm.runInNewContext(source,{document:{getElementById:id=>id==='record-attachment'?input:status},window:{addEventListener:(name,fn)=>events[name]=fn}});
  assert.equal(status.textContent,'Kept');
  input.files=[{}];events.change();assert.equal(status.textContent,'Replaced when saved');
  input.files=[];events.change();assert.equal(status.textContent,'Kept');
  input.files=[{}];events.pageshow();assert.equal(status.textContent,'Replaced when saved');
});
test('no existing attachment needs no replacement status',()=>{
  vm.runInNewContext(source,{document:{getElementById:()=>null}});
});
