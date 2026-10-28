const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function fixture(getDocument){
 const nodes={};const el=id=>nodes[id]||={hidden:false,textContent:'',disabled:false,clientWidth:400,children:[],listeners:{},addEventListener(k,f){this.listeners[k]=f;},replaceChildren(...items){this.children=items;},setAttribute(){},getContext(){return {};}};
 const context={pdfjsLib:{GlobalWorkerOptions:{},getDocument},document:{getElementById:el,createElement:()=>el('canvas')},window:{devicePixelRatio:1},Uint8Array,atob};
 vm.runInNewContext(fs.readFileSync('pos/static/record-pdf.js','utf8').replace(/^import .*;\n/,''),context);
 return {el,viewer:context.window.oakgatePOSPDF};
}
const page={getViewport:({scale})=>({width:400*scale,height:250*scale}),render:()=>({promise:Promise.resolve(),cancel(){}})};
test('PDF renders and supports page navigation, then clears',async()=>{
 let destroyed=0;const f=fixture(options=>{assert.equal(options.isEvalSupported,false);return {promise:Promise.resolve({numPages:2,getPage:async()=>page}),destroy:async()=>destroyed++};});
 await f.viewer.show('JVBERg==');assert.equal(f.el('record-pdf-page').textContent,'Page 1 of 2');assert.equal(f.el('record-pdf-controls').hidden,false);
 f.el('record-pdf-next').listeners.click();await new Promise(r=>setImmediate(r));assert.equal(f.el('record-pdf-page').textContent,'Page 2 of 2');
 f.viewer.clear();assert.equal(destroyed,1);assert.equal(f.el('record-pdf-pages').children.length,0);assert.equal(f.el('record-pdf').hidden,true);
});
test('cancelled PDF load cannot restore private content',async()=>{
 let resolve;const f=fixture(()=>({promise:new Promise(r=>resolve=r),destroy:async()=>{}}));
 const pending=f.viewer.show('JVBERg==');f.viewer.clear();resolve({numPages:1,getPage:async()=>{throw Error('must not render');}});await pending;
 assert.equal(f.el('record-pdf').hidden,true);assert.equal(f.el('record-pdf-pages').children.length,0);
});
test('invalid PDF reports failure without throwing or displaying content',async()=>{
 const f=fixture(()=>({promise:Promise.reject(Error('invalid')),destroy:async()=>{}}));
 await f.viewer.show('JVBERg==');assert.equal(f.el('record-pdf-status').textContent,'PDF preview unavailable.');assert.equal(f.el('record-pdf-controls').hidden,true);
});
