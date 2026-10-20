"use strict";
(() => {
  const status = document.querySelector('[data-receive-status]');
  const pending = document.querySelector('[data-receive-pending]');
  if (!status || !pending) return;
  const note = document.querySelector('[data-receive-poll-note]');
  const received = document.querySelector('[data-receive-complete]');
  let stopped = false;
  let timer;
  let controller;
  const deadline = performance.now() + 60000;
  let deadlineTimer;
  function stop(paused = false) {
    stopped = true;
    clearTimeout(timer);
    clearTimeout(deadlineTimer);
    if (controller) controller.abort();
    if (note) {
      note.hidden = !paused;
      if (paused) note.textContent = note.dataset.paused;
    }
  }
  async function poll() {
    if (stopped) return;
    if (performance.now() >= deadline) { stop(true); return; }
    controller = new AbortController();
    const requestTimer = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(status.dataset.statusUrl, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal
      });
      if (stopped) return;
      if ([401, 403, 404].includes(response.status)) {
        status.textContent = status.dataset.unavailable;
        stop(true);
        return;
      }
      if (!response.ok) throw new Error('Unavailable');
      const result = await response.json();
      if (stopped) return;
      const state = ['pending', 'unavailable', 'complete', 'review', 'expired'].includes(result.state) ? result.state : 'unavailable';
      status.textContent = status.dataset[state];
      status.dataset.state = state;
      if (state === 'complete') {
        pending.hidden = true;
        if (received) received.hidden = false;
        stop();
        return;
      }
      if (['review', 'expired'].includes(state)) { stop(); return; }
    } catch (_) {
      if (!stopped) status.textContent = status.dataset.unavailable;
    } finally {
      clearTimeout(requestTimer);
    }
    if (!stopped) timer = setTimeout(poll, 5000);
  }
  if (['complete', 'review', 'expired'].includes(status.dataset.state)) return;
  deadlineTimer = setTimeout(() => stop(true), 60000);
  timer = setTimeout(poll, 1000);
  window.addEventListener('pagehide', () => stop(), {once: true});
})();
