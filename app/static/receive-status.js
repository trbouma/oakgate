"use strict";
(() => {
  const status = document.querySelector('[data-receive-status]');
  const pending = document.querySelector('[data-receive-pending]');
  if (!status || !pending) return;
  const note = document.querySelector('[data-receive-poll-note]');
  const cancel = document.querySelector('[data-receive-cancel]');
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
  function celebrate() {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const burst = document.createElement('div');
    burst.className = 'receive-confetti';
    burst.setAttribute('aria-hidden', 'true');
    const colors = ['#9bbf74', '#e9c46a', '#62b6b7', '#f4a261', '#d7e9bd'];
    for (let i = 0; i < 48; i++) {
      const piece = document.createElement('span');
      piece.style.setProperty('--x', `${Math.random() * 100}%`);
      piece.style.setProperty('--drift', `${(Math.random() - 0.5) * 160}px`);
      piece.style.setProperty('--delay', `${Math.random() * 0.35}s`);
      piece.style.setProperty('--turn', `${Math.random() * 720 - 360}deg`);
      piece.style.backgroundColor = colors[i % colors.length];
      burst.appendChild(piece);
    }
    document.body.appendChild(burst);
    const cleanup = setTimeout(() => burst.remove(), 2600);
    window.addEventListener('pagehide', () => {
      clearTimeout(cleanup);
      burst.remove();
    }, {once: true});
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
        if (cancel) cancel.textContent = cancel.dataset.completeLabel;
        stop();
        celebrate();
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
  cancel?.addEventListener('click', event => {
    if (!event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && !event.button) stop();
  });
  if (['complete', 'detected', 'expired'].includes(status.dataset.state)) return;
  updateProgress();
  deadlineTimer = setTimeout(() => stop(true), 120000);
  timer = setTimeout(poll, 1000);
  window.addEventListener('pagehide', () => stop(), {once: true});
})();
