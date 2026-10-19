(() => {
  const secret = document.getElementById('recovery-secret');
  const button = document.getElementById('hide-recovery');
  const hide = () => {
    if (secret) { secret.replaceChildren(); secret.hidden = true; }
    if (button) button.remove();
    document.getElementById('recovery-hidden').hidden = false;
  };
  button?.addEventListener('click', hide);
  window.addEventListener('pagehide', hide);
  window.addEventListener('pageshow', (event) => { if (event.persisted) hide(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) hide(); });
  window.setTimeout(hide, 120000);
})();
