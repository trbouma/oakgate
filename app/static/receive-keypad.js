"use strict";
// Integer arithmetic keeps the preview's half-up rounding identical to Decimal
// on the server, including rates serialized in scientific notation.
function receiveSats(value, rate) {
  if (!/^(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,2})?$/.test(value)) return null;
  const match = /^(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(rate);
  if (!match || Math.abs(Number(match[3] || 0)) > 1000) return null;
  const cents = BigInt(value.split('.')[0]) * 100n + BigInt((value.split('.')[1] || '').padEnd(2, '0'));
  let denominator = BigInt(match[1] + (match[2] || ''));
  if (!denominator || !cents) return null;
  const scale = (match[2] || '').length - Number(match[3] || 0);
  let numerator = cents * 1000000n;
  if (scale >= 0) numerator *= 10n ** BigInt(scale);
  else denominator *= 10n ** BigInt(-scale);
  const sats = (2n * numerator + denominator) / (2n * denominator);
  return sats > 0n && sats <= 9999999999999n ? sats.toString() : null;
}
function receiveEntryValid(value, integer) {
  return (integer ? /^[0-9]{0,13}$/ : /^[0-9]{0,13}(?:\.[0-9]{0,2})?$/).test(value);
}
if (typeof module !== 'undefined') module.exports = {receiveSats, receiveEntryValid};
(() => {
  if (typeof document === 'undefined') return;
  const form = document.querySelector('[data-receive-entry]');
  if (!form) return;
  const amount = form.querySelector('[name="amount"]');
  const asset = form.querySelector('[name="asset"]');
  const currency = form.querySelector('[name="currency"]');
  const currencyPane = form.querySelector('[data-receive-currency]');
  const description = form.querySelector('[data-receive-description]');
  const quotedRate = form.querySelector('[name="quoted_rate"]');
  const symbol = form.querySelector('[data-receive-symbol]');
  const unit = form.querySelector('[data-receive-unit]');
  const preview = form.querySelector('[data-receive-sats]');
  const keypad = form.querySelector('[data-receive-keypad]');
  const decimal = keypad.querySelector('[data-key="."]');
  let previous = amount.value;
  const busy = () => form.getAttribute('aria-busy') === 'true';
  const integer = () => !!asset.value || currency.value === 'SATS';
  function updatePreview() {
    preview.hidden = integer();
    if (integer()) { amount.setCustomValidity(''); return; }
    const rate = currency.selectedOptions[0]?.dataset.rate || '';
    quotedRate.value = rate;
    const sats = receiveSats(amount.value, rate);
    preview.textContent = !rate ? preview.dataset.unavailable : sats ? `${BigInt(sats).toLocaleString()} ${preview.dataset.satsLabel}` : `— ${preview.dataset.satsLabel}`;
    amount.setCustomValidity(!rate ? preview.dataset.unavailable : amount.value && !sats ? preview.dataset.invalid : '');
  }
  function press(key) {
    if (busy()) return;
    let next = amount.value;
    if (key === 'clear') next = '';
    else if (key === 'backspace') next = next.slice(0, -1);
    else if (key === '.' && !integer() && !next.includes('.')) next = (next || '0') + '.';
    else if (/^[0-9]$/.test(key)) next += key;
    if (receiveEntryValid(next, integer())) amount.value = next;
    amount.dispatchEvent(new Event('input', {bubbles: true}));
  }
  amount.addEventListener('input', () => {
    if (busy() || !receiveEntryValid(amount.value, integer())) amount.value = previous;
    else amount.value = amount.value.replace(/^0+(?=\d)/, '').replace(/^\./, '0.');
    previous = amount.value;
    updatePreview();
  });
  amount.addEventListener('blur', () => {
    if (!integer() && amount.value.endsWith('.')) {
      amount.value += '00'; previous = amount.value; updatePreview();
    }
  });
  keypad.addEventListener('click', event => {
    const button = event.target.closest('button[data-key]');
    if (button) press(button.dataset.key);
  });
  keypad.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (/^[0-9.]$/.test(event.key) || ['Backspace', 'Delete', 'Escape'].includes(event.key)) {
      event.preventDefault();
      press(event.key === 'Backspace' ? 'backspace' : ['Delete', 'Escape'].includes(event.key) ? 'clear' : event.key);
    }
  });
  function updateMode(reset) {
    // Switching units clears the amount; never reinterpret dollars as shares/sats.
    if (reset) { amount.value = ''; previous = ''; }
    currencyPane.hidden = !!asset.value;
    if (description) description.hidden = !asset.value;
    currency.disabled = !!asset.value;
    unit.textContent = asset.value ? asset.selectedOptions[0]?.dataset.unit : currency.value;
    if (symbol) {
      symbol.textContent = asset.value ? '' : currency.selectedOptions[0]?.dataset.symbol || '';
      symbol.hidden = !!asset.value;
    }
    decimal.hidden = integer();
    keypad.classList.toggle('integer-mode', integer());
    amount.pattern = integer() ? '[1-9][0-9]{0,12}' : '(0|[1-9][0-9]{0,12})([.][0-9]{1,2})?';
    amount.maxLength = integer() ? 13 : 16;
    amount.placeholder = integer() ? '0' : '0.00';
    updatePreview();
  }
  asset.addEventListener('change', () => updateMode(true));
  currency.addEventListener('change', () => updateMode(true));
  updateMode(false);
  amount.inputMode = 'none';
  keypad.hidden = false;
})();
