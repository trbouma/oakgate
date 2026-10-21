"use strict";
(() => {
  const status = document.querySelector('[data-receive-status]');
  const pending = document.querySelector('[data-receive-pending]');
  if (!status || !pending) return;
  const note = document.querySelector('[data-receive-poll-note]');
  const received = document.querySelector('[data-receive-complete]');
  const progress = document.querySelector('[data-receive-progress]');
  const bar = document.querySelector('[data-receive-progress-bar]');
  const countdown = document.querySelector('[data-receive-countdown]');
  let progressTimer;
  let stopped = false;
  let timer;
  let controller;
  const deadline = performance.now() + 120000;
  let deadlineTimer;
  function stop(paused = false) {
    stopped = true;
    clearTimeout(progressTimer);
    if (progress) progress.hidden = true;
    clearTimeout(timer);
    clearTimeout(deadlineTimer);
    if (controller) controller.abort();
    if (note) {
      note.hidden = !paused;
      if (paused) note.textContent = note.dataset.paused;
    }
  }
  function updateProgress() {
    if (stopped) return;
    const remaining = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
    if (bar) bar.value = 120 - remaining;
    if (countdown) countdown.textContent = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
    if (progress) progress.hidden = false;
    if (remaining > 0) progressTimer = setTimeout(updateProgress, 1000);
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
      const state = ['pending', 'unavailable', 'detected', 'complete', 'review', 'expired'].includes(result.state) ? result.state : 'unavailable';
      status.textContent = status.dataset[state];
      status.dataset.state = state;
      if (state === 'complete' || state === 'detected') {
        pending.hidden = true;
        if (received) received.hidden = state !== 'complete';
        stop();
        return;
      }
      if (state === 'expired') { stop(); return; }
    } catch (_) {
      if (!stopped) status.textContent = status.dataset.unavailable;
    } finally {
      clearTimeout(requestTimer);
    }
    if (!stopped) timer = setTimeout(poll, 1000);
  }
  if (['complete', 'detected', 'expired'].includes(status.dataset.state)) return;
  updateProgress();
  deadlineTimer = setTimeout(() => stop(true), 120000);
  timer = setTimeout(poll, 1000);
  window.addEventListener('pagehide', () => stop(), {once: true});
})();
