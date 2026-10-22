document.querySelectorAll('[data-pos-time]').forEach(el => {
  el.textContent = new Date(Number(el.dataset.posTime) * 1000).toLocaleString();
});
document.querySelectorAll('[data-pos-revoke]').forEach(form => form.addEventListener('submit', event => {
  if (!window.confirm(form.dataset.confirm)) event.preventDefault();
}));

const copyPOSKey = document.getElementById('copy-pos-key');
if (copyPOSKey) copyPOSKey.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(document.getElementById('pos-key').value);
    copyPOSKey.textContent = copyPOSKey.dataset.copied;
  } catch (_) { document.getElementById('pos-key').select(); }
});
