"use strict";
(() => {
  document.querySelectorAll('[data-copy-value]').forEach((button) => {
    button.addEventListener('click', async () => {
      const status = document.getElementById(button.dataset.copyStatus);
      try {
        await navigator.clipboard.writeText(button.dataset.copyValue);
        if (status) status.textContent = 'Copied.';
      } catch (_) {
        if (status) status.textContent = 'Copy unavailable. Select and copy the code or link manually.';
      }
      if (status) status.hidden = false;
    });
  });
  const stop = document.querySelector('[data-stop-record-sharing]');
  if (!stop) return;
  const warn = (event) => { event.preventDefault(); event.returnValue = ''; };
  window.addEventListener('beforeunload', warn);
  stop.addEventListener('submit', (event) => {
    if (!event.defaultPrevented) window.removeEventListener('beforeunload', warn);
  });
})();
