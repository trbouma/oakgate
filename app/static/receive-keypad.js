"use strict";
(() => {
  const form = document.querySelector('[data-receive-entry]');
  if (!form) return;
  const amount = form.querySelector('[name="amount"]');
  const asset = form.querySelector('[name="asset"]');
  const unit = form.querySelector('[data-receive-unit]');
  const keypad = form.querySelector('[data-receive-keypad]');
  let previous = amount.value;
  const busy = () => form.getAttribute('aria-busy') === 'true';
  function normalize(value) {
    return value.replace(/^0+/, '');
  }
  function press(key) {
    if (busy()) return;
    if (key === 'clear') amount.value = '';
    else if (key === 'backspace') amount.value = amount.value.slice(0, -1);
    else if (/^[0-9]$/.test(key) && amount.value.length < 13) amount.value = normalize(amount.value + key);
    previous = amount.value;
    amount.dispatchEvent(new Event('input', {bubbles: true}));
  }
  amount.addEventListener('input', () => {
    // Reject decimals/exponents rather than silently changing their meaning.
    if (busy() || !/^[0-9]{0,13}$/.test(amount.value)) amount.value = previous;
    else amount.value = normalize(amount.value);
    previous = amount.value;
  });
  keypad.addEventListener('click', event => {
    const button = event.target.closest('button[data-key]');
    if (button) press(button.dataset.key);
  });
  keypad.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (/^[0-9]$/.test(event.key) || ['Backspace', 'Delete', 'Escape'].includes(event.key)) {
      event.preventDefault();
      press(event.key === 'Backspace' ? 'backspace' : ['Delete', 'Escape'].includes(event.key) ? 'clear' : event.key);
    }
  });
  function updateUnit() { unit.textContent = asset.selectedOptions[0]?.dataset.unit || ''; }
  asset.addEventListener('change', updateUnit);
  updateUnit();
  // The on-screen keypad replaces the mobile keyboard, but desktop typing and
  // native form validation/submission remain available. No-JS uses numeric input.
  amount.inputMode = 'none';
  keypad.hidden = false;
})();
