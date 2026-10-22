const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/receive-status.js', 'utf8');
function setup(fetcher) {
  let now = 0, next = 0;
  const timers = new Map();
  const status = {dataset: {state:'pending', statusUrl:'/status', pending:'Waiting', detected:'Detected', complete:'Received', unavailable:'Checking', expired:'Expired', review:'Review'}};
  const pending = {hidden:false}, complete = {hidden:true};
  const note = {hidden:false, dataset:{paused:'Stopped'}};
  let onCancel;
  const cancel = {dataset:{completeLabel:'New request'},addEventListener:(_,fn)=>{onCancel=fn;}};
  const progress = {hidden:true}, bar = {value:0}, countdown = {textContent:''};
  const nodes = {'[data-receive-cancel]':cancel,'[data-receive-progress]':progress, '[data-receive-progress-bar]':bar, '[data-receive-countdown]':countdown, '[data-receive-status]':status, '[data-receive-pending]':pending, '[data-receive-complete]':complete, '[data-receive-poll-note]':note};
  let calls = 0, lastSignal, onHide;
  vm.runInNewContext(source, {
    document:{querySelector:s=>nodes[s], createElement:()=>({style:{setProperty(){}},setAttribute(){},appendChild(){},remove(){}}),body:{appendChild(){}}}, performance:{now:()=>now}, AbortController,
    setTimeout:(fn, delay)=>{const id=++next; timers.set(id, {fn, at:now+delay}); return id;},
    clearTimeout:id=>timers.delete(id), window:{addEventListener:(_,fn)=>{onHide=fn;}},
    fetch:async (_,options)=>{calls++; lastSignal=options.signal; return fetcher(options);}
  });
  async function advance(to) {
    while (true) {
      const due=[...timers].filter(([,t])=>t.at<=to).sort((a,b)=>a[1].at-b[1].at)[0];
      if (!due) break;
      now=due[1].at; timers.delete(due[0]); due[1].fn();
      for(let i=0;i<12;i++) await Promise.resolve();
    }
    now=to;
  }
  return {cancel:()=>onCancel({}),status,pending,complete,note,progress,bar,countdown,advance,hide:()=>onHide(),calls:()=>calls,signal:()=>lastSignal};
}
const response=state=>({ok:true,status:200,json:async()=>({state})});
test('confirmed credit shows received and stops polling',async()=>{
  const h=setup(()=>response('complete'));
  await h.advance(1000);
  assert.equal(h.status.textContent,'Received');
  assert.equal(h.pending.hidden,true); assert.equal(h.complete.hidden,false);
  assert.equal(h.progress.hidden,true);
  await h.advance(120000); assert.equal(h.calls(),1); assert.equal(h.note.hidden,true);
});
test('pending stops after 120 seconds without expiring request',async()=>{
  const h=setup(()=>response('pending'));
  await h.advance(120000); const calls=h.calls();
  assert.equal(h.status.textContent,'Waiting'); assert.equal(h.note.textContent,'Stopped');
  assert.equal(h.pending.hidden,false);
  await h.advance(180000); assert.equal(h.calls(),calls);
});
test('failed lookup remains checking and stops after deadline',async()=>{
  const h=setup(()=>{throw Error('offline');});
  await h.advance(120000);
  assert.equal(h.status.textContent,'Checking'); assert.equal(h.note.textContent,'Stopped');
});
test('deadline aborts an in-flight lookup and ignores late results',async()=>{
  let resolve;
  const h=setup(()=>new Promise(r=>{resolve=r;}));
  await h.advance(120000); assert.equal(h.signal().aborted,true);
  resolve(response('complete')); for(let i=0;i<12;i++) await Promise.resolve();
  assert.equal(h.complete.hidden,true); assert.equal(h.note.textContent,'Stopped');
});
test('leaving the page stops polling',async()=>{
  const h=setup(()=>response('pending')); await h.advance(1000); h.hide();
  await h.advance(120000); assert.equal(h.calls(),1);
});

test('review keeps checking until credit history is confirmed',async()=>{
  let count=0;
  const h=setup(()=>response(++count===1 ? 'review' : 'complete'));
  await h.advance(1000); assert.equal(h.status.textContent,'Review');
  await h.advance(6000); assert.equal(h.status.textContent,'Received');
  assert.equal(h.pending.hidden,true);
});
test('payment confirmed in the second minute is shown',async()=>{
  let paid=false;
  const h=setup(()=>response(paid ? 'complete' : 'pending'));
  await h.advance(65000); paid=true;
  await h.advance(71000); assert.equal(h.status.textContent,'Received');
});

test('checking countdown advances and disappears when polling stops',async()=>{
  const h=setup(()=>response('pending'));
  assert.equal(h.countdown.textContent,'2:00');
  assert.equal(h.progress.hidden,false);
  await h.advance(30000);
  assert.equal(h.countdown.textContent,'1:30'); assert.equal(h.bar.value,30);
  await h.advance(120000); assert.equal(h.progress.hidden,true);
  const last=h.countdown.textContent;
  await h.advance(180000); assert.equal(h.countdown.textContent,last);
});

test('detected transfer stops polling without claiming confirmed credit',async()=>{
  const h=setup(()=>response('detected'));
  await h.advance(1000);
  assert.equal(h.status.textContent,'Detected');
  assert.equal(h.pending.hidden,true);
  assert.equal(h.complete.hidden,true);
  assert.equal(h.progress.hidden,true);
  await h.advance(120000);
  assert.equal(h.calls(),1);
});

test('cancel aborts lookup and ignores a late response',async()=>{
  let resolve;
  const h=setup(()=>new Promise(r=>{resolve=r;}));
  await h.advance(1000);h.cancel();
  assert.equal(h.signal().aborted,true);
  assert.equal(h.progress.hidden,true);
  resolve(response('complete'));for(let i=0;i<12;i++) await Promise.resolve();
  assert.equal(h.complete.hidden,true);
  await h.advance(180000);assert.equal(h.calls(),1);
});
