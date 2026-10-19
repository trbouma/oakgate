"use strict";

// Keep normal HTML submission, validation, redirects, and server-side guards.
// Only the first valid submission on the page may start an operation.
(() => {
  let activeForm = null;
  const controls = new Map();
  let submitterValue = null;
  const status = document.getElementById("page-progress");

  function reset() {
    activeForm?.removeAttribute("aria-busy");
    activeForm = null;
    for (const [control, original] of controls) {
      control.disabled = original.disabled;
      if (original.ariaDisabled === null) control.removeAttribute("aria-disabled");
      else control.setAttribute("aria-disabled", original.ariaDisabled);
    }
    controls.clear();
    submitterValue?.remove();
    submitterValue = null;
    if (status) status.hidden = true;
    document.querySelectorAll("a[data-opening]").forEach((link) => {
      link.removeAttribute("aria-busy");
      delete link.dataset.opening;
    });
  }

  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
    if (activeForm) {
      event.preventDefault();
      return;
    }
    const form = event.target;
    activeForm = form;
    form.setAttribute("aria-busy", "true");
    // Disabling a named submit button would otherwise omit its value from POST.
    if (event.submitter?.name && !event.submitter.disabled) {
      submitterValue = document.createElement("input");
      submitterValue.type = "hidden";
      submitterValue.name = event.submitter.name;
      submitterValue.value = event.submitter.value;
      form.appendChild(submitterValue);
    }
    document.querySelectorAll('button:not([type]), button[type="submit"], input[type="submit"]').forEach((control) => {
      controls.set(control, {disabled: control.disabled, ariaDisabled: control.getAttribute("aria-disabled")});
      control.disabled = true;
      control.setAttribute("aria-disabled", "true");
    });
    if (status) {
      status.textContent = form.dataset.progressMessage || status.dataset.working;
      status.hidden = false;
    }
    // Respect a later handler cancelling submission. Never time out and invite
    // a second payment while the original outcome may still be unresolved.
    queueMicrotask(() => { if (event.defaultPrevented) reset(); });
  });

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.("a[href]");
    if (!link || link.target || link.hasAttribute("download") || link.getAttribute("href").startsWith("#")) return;
    const destination = new URL(link.href, location.href);
    if (destination.origin !== location.origin) return;
    if (activeForm) {
      event.preventDefault();
      return;
    }
    if (status) {
      status.textContent = status.dataset.opening;
      status.hidden = false;
    }
    link.setAttribute("aria-busy", "true");
    link.dataset.opening = "true";
  });

  // Browsers may restore a submitted page from the back/forward cache.
  window.addEventListener("pageshow", reset);
})();
