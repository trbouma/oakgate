import QrScanner from '/scanner/qr-scanner.min.js';

// QR data is a credential, never a navigation target. Nothing is sent until a
// valid activation key enters the same proof-bound flow as manual entry.
const form = document.getElementById('activation');
const input = document.getElementById('credential');
const startButton = document.getElementById('scan-start');
const stopButton = document.getElementById('scan-stop');
const preview = document.getElementById('scan-preview');
const video = document.getElementById('scan-video');
const status = document.getElementById('scan-status');
let scanner = null;
let starting = false;
let running = false;

function stop() {
  running = false;
  scanner?.destroy();
  scanner = null;
  // Stop camera tracks immediately, including pending decoder callbacks.
  video.srcObject?.getTracks().forEach(track => track.stop());
  video.srcObject = null;
  preview.hidden = true;
  startButton.hidden = false;
  startButton.disabled = starting;
}

function accept(result) {
  if (!running || form.hidden || form.getAttribute('aria-busy') === 'true') return;
  const value = typeof result.data === 'string' ? result.data.trim() : '';
  if (!/^ogpos1\.[a-f0-9]{32}\.[A-Za-z0-9_-]{43}$/.test(value)) {
    status.textContent = 'This is not an OakGate POS activation code. Scan the code shown when you create a POS key.';
    return;
  }
  stop(); // Set running=false before submission so repeated frames cannot enroll twice.
  input.value = value;
  status.textContent = 'Activation code acquired. Activating this browser…';
  form.requestSubmit();
}

startButton.addEventListener('click', async () => {
  if (starting || running || form.hidden || form.getAttribute('aria-busy') === 'true') return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    status.textContent = 'Camera scanning needs HTTPS and camera support. Enter your key below instead.';
    return;
  }
  starting = true;
  running = true;
  startButton.disabled = true;
  preview.hidden = false;
  status.textContent = 'Allow camera access, then point at the activation QR code.';
  try {
    const current = new QrScanner(video, accept, {
      preferredCamera: 'environment', returnDetailedScanResult: true,
      maxScansPerSecond: 6, onDecodeError: () => {},
    });
    scanner = current;
    await current.start();
    if (!running || scanner !== current) {
      current.destroy();
      video.srcObject?.getTracks().forEach(track => track.stop());
      video.srcObject = null;
      return;
    }
    startButton.hidden = true;
    status.textContent = 'Point at the activation QR code. Activation will start when it is recognized.';
  } catch (_) {
    const wasRunning = running;
    stop();
    if (wasRunning) status.textContent = 'Camera access was unavailable. Check camera permission or enter your key below.';
  } finally {
    starting = false;
    startButton.disabled = form.getAttribute('aria-busy') === 'true';
  }
});
stopButton.addEventListener('click', () => { stop(); status.textContent = 'Camera stopped. You can enter your key below.'; });
document.addEventListener('pos-activation-start', stop);
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
window.addEventListener('pagehide', stop);
