"use strict";
(() => {
  const element = document.getElementById('oakgate-translations');
  let messages = {};
  try { messages = JSON.parse(element?.textContent || '{}'); } catch (_) { /* English fallback. */ }
  window.oakgateTranslate = (message) => Object.prototype.hasOwnProperty.call(messages, message) ? messages[message] : message;
})();
