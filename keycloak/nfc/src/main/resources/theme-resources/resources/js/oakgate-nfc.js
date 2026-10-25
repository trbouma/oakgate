(() => {
  const form = document.getElementById('oakgate-nfc');
  const card = document.getElementById('nfc-card'), pin = document.getElementById('nfc-pin');
  const read = document.getElementById('nfc-read'), submit = document.getElementById('nfc-submit');
  const status = document.getElementById('nfc-status');
  let controller, timer, submitting = false;
  function stop() { controller?.abort(); controller = null; clearTimeout(timer); }
  function clear() { stop(); card.value = ''; pin.value = ''; submit.disabled = true; }
  if (!window.isSecureContext || !('NDEFReader' in window)) {
    read.hidden = true; status.textContent = 'This browser cannot read NFC cards. Use Google or email from OakGate.';
    return;
  }
  read.addEventListener('click', async () => {
    clear(); read.disabled = true; status.textContent = 'Hold your card against the phone.';
    controller = new AbortController(); const signal = controller.signal;
    timer = setTimeout(() => { stop(); read.disabled = false; status.textContent = 'Scan timed out. Tap Read card to try again.'; }, 30000);
    try {
      const reader = new NDEFReader();
      reader.onreading = event => {
        if (signal.aborted) return;
        const records = event.message.records.filter(r => r.recordType === 'mime' && r.mediaType === 'application/vnd.oakgate.card');
        if (records.length !== 1 || records[0].data.byteLength > 400) {
          status.textContent = 'This is not an OakGate card.'; return;
        }
        const data = records[0].data;
        card.value = btoa(String.fromCharCode(...new Uint8Array(data.buffer, data.byteOffset, data.byteLength)));
        stop(); read.disabled = false; submit.disabled = false;
        status.textContent = 'Card read. Enter your PIN, or leave it blank if you enabled card-only sign-in.'; pin.focus();
      };
      reader.onreadingerror = () => { status.textContent = 'Could not read the card. Hold it still and try again.'; };
      await reader.scan({signal});
    } catch (_) { stop(); read.disabled = false; status.textContent = 'NFC unavailable. Try again or use your usual sign-in.'; }
  });
  form.addEventListener('submit', event => {
    if (submitting || !card.value || (pin.value !== '' && !/^[0-9]{4}$/.test(pin.value))) { event.preventDefault(); return; }
    submitting = true; stop(); read.disabled = true; submit.disabled = true;
    status.textContent = 'Checking card and PIN…';
  });
  window.addEventListener('pagehide', clear);
  document.addEventListener('visibilitychange', () => { if (document.hidden && !submitting) { clear(); read.disabled = false; } });
})();
