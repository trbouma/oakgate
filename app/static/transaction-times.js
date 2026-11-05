/* Display UTC transaction and receipt instants in the device timezone; never change stored data. */
(() => {
  'use strict';
  let formatter;
  try {
    formatter = new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
    });
  } catch (_) { return; }
  document.querySelectorAll('time[data-local-transaction-time][datetime]').forEach(element => {
    const instant = element.getAttribute('datetime');
    // Only convert explicit instants, never guess a timezone for a naive date.
    if (!instant || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(instant)) return;
    const date = new Date(instant);
    if (!Number.isFinite(date.getTime())) return;
    try {
      const local = formatter.format(date);
      if (!element.hasAttribute('title')) element.setAttribute('title', element.textContent);
      element.textContent = local;
    } catch (_) { /* Keep the original UTC fallback. */ }
  });
})();
