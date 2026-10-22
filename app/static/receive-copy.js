"use strict";
(() => {
  const button = document.querySelector('[data-receive-copy]');
  const status = document.getElementById('receive-copy-status');
  if (!button || !status) return;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {
      await navigator.clipboard.writeText(button.dataset.receiveCopy);
      status.textContent = status.dataset.copied;
    } catch (_) {
      status.textContent = status.dataset.failed;
    } finally {
      button.disabled = false;
    }
  });
})();
