const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(records,hash='#request'){
 const nodes={},calls=[];let count=0;
 const el=id=>nodes[id]||={dataset:{signedIn:'yes',csrf:'token'},hidden:true,disabled:true,textContent:'',children:[],listeners:{},setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.listeners[k]=f;},append(...items){this.children.push(...items);}};
 const checked=()=>Object.values(nodes).filter(n=>n.type==='checkbox'&&n.checked);
 const context={document:{getElementById:el,createElement:()=>el('new'+count++),querySelectorAll:checked,querySelector:()=>checked()[0]},location:{hash,pathname:'/account/record-request'},history:{replaceState(){}},URLSearchParams,fetch:async(url,options)=>{calls.push([url,options.body]);return {ok:true,json:async()=>({name:'Counter',label:'benefits',records})};}};
 vm.runInNewContext(fs.readFileSync('app/static/record-request.js','utf8'),context);
 return {el,nodes,calls};
}
test('wallet single match approves without showing checkboxes',async()=>{
 const f=fixture([{id:'one',label:'benefits/dental'}]);await new Promise(r=>setImmediate(r));
 assert.equal(f.el('record-request-choices').hidden,true);assert.equal(f.el('record-request-approve').disabled,false);
 await f.el('record-request-approve').onclick();assert.deepEqual(JSON.parse(f.calls.at(-1)[1].get('selected')),['one']);
});
test('wallet category approval includes only explicitly checked records',async()=>{
 const f=fixture([{id:'dental',label:'benefits/dental'},{id:'health',label:'benefits/health'}]);await new Promise(r=>setImmediate(r));
 assert.equal(f.el('record-request-choices').hidden,false);assert.equal(f.el('record-request-approve').disabled,true);
 const boxes=Object.values(f.nodes).filter(n=>n.type==='checkbox');boxes[1].checked=true;boxes[1].listeners.change();
 assert.equal(f.el('record-request-approve').disabled,false);await f.el('record-request-approve').onclick();
 assert.deepEqual(JSON.parse(f.calls.at(-1)[1].get('selected')),['health']);
});

test('foreign request approval uses an owner-bound local ticket and local callback',async()=>{
 const f=fixture([{id:'one',label:'benefits/dental'}],'#remote.ticket');await new Promise(r=>setImmediate(r));
 assert.equal(f.calls[0][0],'/account/record-request/details');
 assert.equal(f.calls[0][1].get('request_id'),'ticket');
 assert.equal(f.calls[0][1].get('remote'),'1');
 await f.el('record-request-approve').onclick();
 assert.equal(f.calls.at(-1)[0],'/account/record-request/approve');
 assert.equal(f.calls.at(-1)[1].get('remote'),'1');
});

test('mixed labels show short fingerprints but approval retains exact selection ids',async()=>{
 const f=fixture([{id:'plain',label:'benefits/dental'},{id:'digest',label:'benefits/'+'a'.repeat(64)}]);
 await new Promise(r=>setImmediate(r));
 const texts=Object.values(f.nodes).map(n=>n.textContent);
 assert.ok(texts.includes('dental'));assert.ok(texts.includes('aaaaaaaaaaaa…aaaaaaaa'));
 const boxes=Object.values(f.nodes).filter(n=>n.type==='checkbox');boxes[1].checked=true;boxes[1].listeners.change();
 await f.el('record-request-approve').onclick();assert.deepEqual(JSON.parse(f.calls.at(-1)[1].get('selected')),['digest']);
});
