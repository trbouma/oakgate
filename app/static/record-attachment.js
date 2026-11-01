"use strict";
(() => {
  const input = document.getElementById('record-attachment');
  const status = document.getElementById('record-attachment-status');
  if (!input || !status) return;
  const update = () => {
    status.textContent = input.files?.length ? status.dataset.replacement : status.dataset.retained;
  };
  input.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
})();
