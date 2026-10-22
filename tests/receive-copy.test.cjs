const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
for (const fails of [false,true]) test(`QR clipboard ${fails ? 'failure' : 'success'}`, async () => {
  let click, copied;
  const button={dataset:{receiveCopy:'lightning-request'},disabled:false,addEventListener:(_,fn)=>{click=fn;}};
  const status={dataset:{copied:'Copied.',failed:'Try again'}};
  vm.runInNewContext(fs.readFileSync('app/static/receive-copy.js','utf8'),{
    document:{querySelector:()=>button,getElementById:()=>status},
    navigator:{clipboard:{writeText:async value=>{copied=value;if(fails) throw Error('denied');}}}
  });
  await click();
  assert.equal(copied,'lightning-request');
  assert.equal(status.textContent,fails?'Try again':'Copied.');
  assert.equal(button.disabled,false);
});
