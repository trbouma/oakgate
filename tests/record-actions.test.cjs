const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/record-actions.js', 'utf8');
function setup(remaining = 120, expired = false) {
  let now = 0, requests = 0, next = 0;
  const timers = new Map(), events = {}, handlers = {};
  const bar = {}, countdown = {};
  const stop = {addEventListener: (name, fn) => handlers[name] = fn,
    requestSubmit: () => { requests++; handlers.submit({defaultPrevented:false}); }};
  const nodes = {'[data-stop-record-sharing]':stop, '[data-share-progress]':expired ? null : {dataset:{remainingSeconds:String(remaining)}},
    '[data-share-progress-bar]':bar, '[data-share-countdown]':countdown};
  vm.runInNewContext(source, {
    document:{querySelector:s=>nodes[s], querySelectorAll:()=>[], addEventListener:(name,fn)=>events[name]=fn},
    window:{addEventListener:(name,fn)=>events[name]=fn, removeEventListener:()=>{}},
    Date:{now:()=>now}, setTimeout:fn=>{timers.set(++next,fn);return next;}, clearTimeout:id=>timers.delete(id)
  });
  return {bar,countdown,stop,events,requests:()=>requests,
    advance:ms=>{now+=ms; const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());}};
}
test('countdown submits Stop once at two minutes', () => {
  const page=setup();assert.equal(page.countdown.textContent,'2:00');
  page.advance(60000);assert.equal(page.countdown.textContent,'1:00');assert.equal(page.bar.value,60);
  page.advance(60000);assert.equal(page.requests(),1);
  page.events.visibilitychange();page.advance(10000);assert.equal(page.requests(),1);
});
test('manual stop prevents a second automatic stop',()=>{
  const page=setup();page.stop.requestSubmit();page.advance(120000);assert.equal(page.requests(),1);
});
test('remaining lifetime survives reload and sleeping tabs',()=>{
  const page=setup(15);assert.equal(page.countdown.textContent,'0:15');
  page.advance(20000);page.events.visibilitychange();assert.equal(page.requests(),1);
});
test('expired page keeps Stop manual rather than retrying in a loop',()=>{
  const page=setup(0,true);page.advance(120000);assert.equal(page.requests(),0);
  page.stop.requestSubmit();assert.equal(page.requests(),1);
});
