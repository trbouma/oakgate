"use strict";
// Display preference only, using the same year-long cookie approach as Safebox Web.
(() => {
  const root = document.documentElement;
  const saved = document.cookie.split("; ").find((entry) => entry.startsWith("oakgate_theme="))?.split("=")[1];
  let theme = saved === "light" ? "light" : "dark";
  // Run in the head before styles paint, avoiding a flash of the wrong theme.
  root.dataset.theme = theme;
  function apply() {
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#171914" : "#faf8f1");
    document.querySelectorAll("[data-theme-toggle]").forEach((toggle) => {
      const action = theme === "dark" ? toggle.dataset.lightLabel : toggle.dataset.darkLabel;
      toggle.setAttribute("aria-label", action);
      toggle.setAttribute("title", action);
    });
  }
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    document.querySelectorAll("[data-theme-toggle]").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        theme = theme === "dark" ? "light" : "dark";
        document.cookie = `oakgate_theme=${theme}; Path=/; Max-Age=31536000; SameSite=Strict${location.protocol === "https:" ? "; Secure" : ""}`;
        apply();
      });
    });
  });
})();
