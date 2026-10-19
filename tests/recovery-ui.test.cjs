const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/static/recovery.js'),'utf8');
for (const trigger of ['click','timer','visibilitychange','pagehide','pageshow']) {
  const events = {};
  const secret = {text:'synthetic recovery material',hidden:false,replaceChildren(){this.text='';}};
  const button = {removed:false,addEventListener(name,fn){events[name]=fn;},remove(){this.removed=true;}};
  const hidden = {hidden:true};
  const document = {hidden:true,getElementById(id){return {'recovery-secret':secret,'hide-recovery':button,'recovery-hidden':hidden}[id]},addEventListener(name,fn){events[name]=fn;}};
  const window = {addEventListener(name,fn){events[name]=fn;},setTimeout(fn,ms){assert.equal(ms,120000);events.timer=fn;}};
  vm.runInNewContext(source,{document,window});
  events[trigger]({persisted:true});
  assert.equal(secret.text,''); assert.equal(secret.hidden,true); assert.equal(button.removed,true); assert.equal(hidden.hidden,false);
}
console.log('5 recovery concealment checks passed');
