/**
 * Preferendum — Global Translation Config
 * Change LANGUAGES here to add/remove languages across ALL portals.
 * Served at /translate.js by the backend.
 */
(function() {
  var LANGUAGES = 'en,zh-CN,fr,de,ar,pt,ru,ja,ko,hi,es';
  var PAGE_LANG = 'es';

  // Find the widget container on this page (any div with id starting with 'gt-widget')
  function initWidget() {
    var containers = document.querySelectorAll('[id^="gt-widget"]');
    if (!containers.length) return;
    var containerId = containers[0].id;
    if (window.google && window.google.translate) {
      new google.translate.TranslateElement({
        pageLanguage: PAGE_LANG,
        includedLanguages: LANGUAGES,
        layout: google.translate.TranslateElement.InlineLayout.SIMPLE,
        autoDisplay: false
      }, containerId);
    }
  }

  // Expose callback for Google Translate CDN
  window.googleTranslateElementInit  = initWidget;
  window.googleTranslateElementInit2 = initWidget;
  window.googleTranslateElementInit3 = initWidget;

  // Load Google Translate script once
  if (!document.querySelector('script[src*="translate.google.com"]')) {
    var s = document.createElement('script');
    s.src = '//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
    s.async = true;
    document.head.appendChild(s);
  }
})();
