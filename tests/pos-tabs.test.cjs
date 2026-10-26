const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function fixture(){
 const nodes={};
 const el=id=>nodes[id]||=( {hidden:true,disabled:false,attrs:{},listeners:{},
 setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this.listeners[k]=v;},focus(){this.focused=true;}} );
 el('terminal').hidden=false;el('panel-sale').hidden=false;
 vm.runInNewContext(fs.readFileSync('pos/static/tabs.js','utf8'),{CustomEvent:function(){},document:{getElementById:el,dispatchEvent(){}}});
 return {el,choose:()=>el('tab-record').listeners.click()};
}
test('switching tabs preserves the existing sale content and returns with keyboard navigation',()=>{
 const f=fixture();const sale=f.el('panel-sale');sale.requestKey='existing-request';
 f.choose();assert.equal(sale.hidden,true);assert.equal(f.el('panel-record').hidden,false);
 assert.equal(f.el('tab-record').attrs['aria-selected'],'true');
 f.el('tab-record').listeners.keydown({key:'Home',preventDefault(){}});
 assert.equal(sale.hidden,false);assert.equal(sale.requestKey,'existing-request');
 assert.equal(f.el('tab-sale').focused,true);assert.equal(f.el('panel-record').hidden,true);
});
for(const id of ['receipt','card-issuance','card-balance-panel','scan-preview']){
 test(`navigation keeps active ${id} visible without cancelling it`,()=>{
  const f=fixture();f.el(id).hidden=false;f.choose();
  assert.equal(f.el('panel-sale').hidden,false);assert.equal(f.el('panel-record').hidden,true);
  assert.match(f.el('tab-notice').textContent,/Finish or cancel/);
  f.el(id).hidden=true;f.choose();assert.equal(f.el('panel-record').hidden,false);
 });
}
