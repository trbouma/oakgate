"use strict";
(() => {
  const status = document.querySelector('[data-receive-status]');
  if (!status || !document.querySelector('[data-receive-pending]')) return;
  let stopped = false;
  let timer;
  async function poll() {
    if (stopped) return;
    try {
      const response = await fetch(status.dataset.statusUrl, {credentials:'same-origin', cache:'no-store'});
      if ([401, 403, 404].includes(response.status)) {
        status.textContent = status.dataset.unavailable;
        return;
      }
      if (!response.ok) throw new Error('Unavailable');
      const result = await response.json();
      const state = ['pending', 'unavailable', 'complete', 'review', 'expired'].includes(result.state) ? result.state : 'unavailable';
      status.textContent = status.dataset[state];
      if (result.state === 'complete') {
        document.querySelector('[data-receive-pending]').hidden = true;
        return;
      }
    } catch (_) { status.textContent = status.dataset.unavailable; }
    if (!stopped) timer = setTimeout(poll, 10000);
  }
  timer = setTimeout(poll, 5000);
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); }, {once:true});
})();
