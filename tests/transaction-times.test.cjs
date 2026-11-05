const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/transaction-times.js','utf8');
function render(instant,zone='America/Toronto',locale='en-CA',broken=false){
 const attrs={datetime:instant};
 const element={textContent:'UTC fallback',getAttribute:k=>attrs[k],hasAttribute:k=>k in attrs,setAttribute:(k,v)=>attrs[k]=v};
 const context={Date,Number,Intl:{DateTimeFormat:function(lang,options){
  if(broken)throw Error('Unavailable');
  return new Intl.DateTimeFormat(lang,{...options,timeZone:zone});
 }},document:{documentElement:{lang:locale},querySelectorAll:()=>[element]}};
 vm.runInNewContext(source,context);return {element,attrs};
}
test('device timezone handles winter and summer offsets without changing the instant',()=>{
 for(const [instant,hour] of [['2026-01-15T17:30:00+00:00','12'],['2026-07-15T17:30:00+00:00','01']]){
  const {element,attrs}=render(instant);
  const expected=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short',timeZone:'America/Toronto'}).format(new Date(instant));
  assert.equal(element.textContent,expected);assert.equal(attrs.datetime,instant);assert.equal(attrs.title,'UTC fallback');
 }
});
test('supports fractional-offset timezones, date rollover and selected language',()=>{
 const instant='2026-11-05T23:30:00Z';
 const {element}=render(instant,'Asia/Kolkata','fr');
 assert.equal(element.textContent,new Intl.DateTimeFormat('fr',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short',timeZone:'Asia/Kolkata'}).format(new Date(instant)));
});
test('invalid, missing and naive dates retain fallback',()=>{
 for(const instant of ['',undefined,'badZ','2026-11-05T12:30:00'])assert.equal(render(instant).element.textContent,'UTC fallback');
 assert.equal(render('2026-11-05T12:30:00Z','UTC','en',true).element.textContent,'UTC fallback');
});
