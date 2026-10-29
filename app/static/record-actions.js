"use strict";
const t = (message) => window.oakgateTranslate ? window.oakgateTranslate(message) : message;

(() => {
  document.querySelectorAll('[data-copy-value]').forEach((button) => {
    button.addEventListener('click', async () => {
      const status = document.getElementById(button.dataset.copyStatus);
      try {
        await navigator.clipboard.writeText(button.dataset.copyValue);
        if (status) status.textContent = t('Copied.');
      } catch (_) {
        if (status) status.textContent = t("Copy unavailable. Select and copy the code or link manually.");
      }
      if (status) status.hidden = false;
    });
  });
  const stop = document.querySelector('[data-stop-record-sharing]');
  if (!stop) return;
  const progress = document.querySelector('[data-share-progress]');
  const bar = document.querySelector('[data-share-progress-bar]');
  const countdown = document.querySelector('[data-share-countdown]');
  const remaining = Number(progress?.dataset.remainingSeconds);
  const deadline = Date.now() + Math.max(0, remaining) * 1000;
  let timer;
  let submitted = false;
  function update() {
    clearTimeout(timer);
    if (submitted || !progress || !Number.isFinite(remaining)) return;
    const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    if (bar) bar.value = 120 - Math.min(120, seconds);
    if (countdown) countdown.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (seconds === 0) {
      // Use the normal CSRF-protected form and its duplicate-submit guard.
      // Never claim deletion just because the local countdown has finished.
      stop.requestSubmit();
      return;
    }
    timer = setTimeout(update, 250);
  }
  const warn = (event) => { event.preventDefault(); event.returnValue = ''; };
  window.addEventListener('beforeunload', warn);
  stop.addEventListener('submit', (event) => {
    if (!event.defaultPrevented) {
      submitted = true;
      clearTimeout(timer);
      window.removeEventListener('beforeunload', warn);
    }
  });
  document.querySelector('[data-record-card]')?.addEventListener('submit', (event) => {
    if (!event.defaultPrevented) {
      submitted = true;
      clearTimeout(timer);
      window.removeEventListener('beforeunload', warn);
    }
  });
  document.addEventListener('visibilitychange', update);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.addEventListener('pageshow', () => {
    submitted = false;
    update();
  });
  update();
})();
