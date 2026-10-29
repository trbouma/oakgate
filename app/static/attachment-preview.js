"use strict";
const input = document.querySelector('#record-attachment');
const panel = document.querySelector('[data-attachment-preview]');
if (input && panel) {
  const content = panel.querySelector('[data-attachment-content]');
  const status = panel.querySelector('[data-attachment-status]');
  const name = panel.querySelector('[data-attachment-name]');
  let revision = 0;
  let objectUrl;
  let pdfTask;
  function clear() {
    revision += 1;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = undefined;
    if (pdfTask) void pdfTask.destroy().catch(() => {});
    pdfTask = undefined;
    content.replaceChildren();
    status.textContent = '';
    name.textContent = '';
    input.setCustomValidity('');
    panel.hidden = true;
  }
  input.addEventListener('change', async () => {
    clear();
    const file = input.files[0];
    if (!file) return;
    const current = revision;
    panel.hidden = false;
    name.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
    if (!file.size || file.size > 25 * 1024 * 1024) {
      status.textContent = panel.dataset.tooLarge;
      input.setCustomValidity(panel.dataset.tooLarge);
      return;
    }
    status.textContent = panel.dataset.loading;
    try {
      // Never embed HTML, SVG or unknown files as executable documents.
      if (['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'].includes(file.type)) {
        const img = document.createElement('img');
        img.alt = file.name;
        objectUrl = URL.createObjectURL(file);
        img.src = objectUrl;
        img.onerror = () => { if (current === revision) status.textContent = panel.dataset.unavailable; };
        content.append(img);
        status.textContent = '';
      } else if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) {
        const pdfjs = await import('/static/pdf.mjs?v=5.4.624-legacy1');
        if (current !== revision) return;
        pdfjs.GlobalWorkerOptions.workerSrc = '/static/pdf.worker.mjs?v=5.4.624-legacy1';
        const data = await file.arrayBuffer();
        if (current !== revision) return;
        const task = pdfjs.getDocument({data, isEvalSupported: false});
        pdfTask = task;
        const doc = await task.promise;
        const page = await doc.getPage(1);
        if (current !== revision) return;
        const natural = page.getViewport({scale: 1});
        const scale = Math.min(2, 1600 / Math.max(natural.width, natural.height));
        const viewport = page.getViewport({scale});
        const canvas = document.createElement('canvas');
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        canvas.setAttribute('aria-label', panel.dataset.pdfPage);
        await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
        if (current !== revision) return;
        content.append(canvas);
        status.textContent = panel.dataset.pdfPage;
      } else if (['text/plain', 'application/json'].includes(file.type) || /\.(txt|json|csv|md)$/i.test(file.name)) {
        const text = await file.slice(0, 262144).text();
        if (current !== revision) return;
        const pre = document.createElement('pre');
        pre.textContent = text + (file.size > 262144 ? '\n…' : '');
        content.append(pre);
        status.textContent = '';
      } else {
        status.textContent = panel.dataset.unavailable;
      }
    } catch (_) {
      if (current === revision) status.textContent = panel.dataset.unavailable;
    }
  });
  panel.querySelector('[data-attachment-remove]').addEventListener('click', () => {
    clear();
    input.value = '';
    input.focus();
  });
  window.addEventListener('pagehide', clear);
}
