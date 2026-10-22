const {test} = require('node:test');
const assert = require('node:assert/strict');
const {receiveSats,receiveEntryValid} = require('../app/static/receive-keypad.js');
test('preview rounds exactly like invoice conversion', () => {
  assert.equal(receiveSats('1.25','100000'),'1250');
  assert.equal(receiveSats('0.01','2000000'),'1');
  assert.equal(receiveSats('2.50','1E+5'),'2500');
  assert.equal(receiveSats('0.01','1e18'),null);
  assert.equal(receiveSats('1',''),null);
  assert.equal(receiveSats('1.234','100000'),null);
});
test('keypad allows two decimal places only in fiat mode', () => {
  for(const value of ['0.','1.2','1.25']) {
    assert.equal(receiveEntryValid(value,false),true);
    assert.equal(receiveEntryValid(value,true),false);
  }
  for(const value of ['1e2','-1','1.234','1..2']) assert.equal(receiveEntryValid(value,false),false);
  assert.equal(receiveEntryValid('12',true),true);
});

test('currency and Clear switches reset entry and update decimal controls', () => {
  const fs = require('node:fs');
  const vm = require('node:vm');
  function node(value='') { return {value, hidden:false, disabled:false, dataset:{}, handlers:{},
    addEventListener(type,handler){this.handlers[type]=handler;},
    dispatchEvent(event){this.handlers[event.type]?.(event);},
    setCustomValidity(value){this.validity=value;}, classList:{toggle(){}}}; }
  const amount=node(), asset=node(), currency=node('CAD'), pane=node(), rate=node(), unit=node(), preview=node(), keypad=node(), decimal=node();
  currency.selectedOptions=[{dataset:{rate:'100000'}}];
  asset.selectedOptions=[{dataset:{unit:'shares'}}];
  preview.dataset={satsLabel:'sats',unavailable:'unavailable',invalid:'invalid'};
  keypad.querySelector=()=>decimal;
  const nodes={'[name="amount"]':amount,'[name="asset"]':asset,'[name="currency"]':currency,
    '[data-receive-currency]':pane,'[name="quoted_rate"]':rate,'[data-receive-unit]':unit,
    '[data-receive-sats]':preview,'[data-receive-keypad]':keypad};
  let busy=false;
  const form={querySelector:key=>nodes[key],getAttribute:()=>busy?'true':null};
  vm.runInNewContext(fs.readFileSync('app/static/receive-keypad.js','utf8'),{document:{querySelector:()=>form},Event:class {constructor(type){this.type=type;}}});
  function press(key){keypad.handlers.click({target:{closest:()=>({dataset:{key}})}});}
  for(const key of ['1','.','2','5','9']) press(key);
  assert.equal(amount.value,'1.25'); assert.equal(preview.textContent,'1,250 sats');
  busy=true;press('clear');assert.equal(amount.value,'1.25');busy=false;
  currency.value='SATS';currency.handlers.change();
  assert.equal(amount.value,'');assert.equal(decimal.hidden,true);assert.equal(preview.hidden,true);
  press('2');press('.');assert.equal(amount.value,'2');
  asset.value='clear';asset.handlers.change();
  assert.equal(amount.value,'');assert.equal(pane.hidden,true);assert.equal(currency.disabled,true);assert.equal(unit.textContent,'shares');
  asset.value='';currency.value='CAD';asset.handlers.change();
  assert.equal(decimal.hidden,false);assert.equal(currency.disabled,false);
  press('.');press('5');assert.equal(amount.value,'0.5');assert.equal(preview.textContent,'500 sats');
});
