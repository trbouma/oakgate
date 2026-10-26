'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const tabs = [$('tab-sale'), $('tab-record')];
  const panels = [$('panel-sale'), $('panel-record')];
  const notice = $('tab-notice');
  function select(index, focus = false) {
    if (tabs[index].disabled) return;
    // Keep an active request or hardware operation visible. Do not cancel,
    // restart, or otherwise change payment/card state through navigation.
    const active = !$('scan-preview').hidden || (!$('terminal').hidden &&
      ['receipt', 'card-issuance', 'card-balance-panel'].some(id => !$(id).hidden));
    if (index === 1 && active) {
      notice.textContent = 'Finish or cancel the current Point of Sale activity before switching tabs.';
      return;
    }
    notice.textContent = '';
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
    if (focus) tabs[index].focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(index));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = 1 - index;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = 1;
      else return;
      event.preventDefault();
      select(next, true);
    });
  });
})();
