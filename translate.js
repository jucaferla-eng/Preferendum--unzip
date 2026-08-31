/**
 * Preferendum — Google Translate engine wiring.
 * Served at /translate.js by the backend.
 *
 * COMPLETE INTERNATIONALIZATION REMEDIATION: this file no longer decides
 * the user's language itself (it used to auto-detect from
 * navigator.language independently of everything else). It is now purely
 * a TRANSLATION ENGINE — it loads the Google Translate widget and lets
 * lang.js's PreferendumLang.currentLanguage() (the ONE authoritative
 * resolver) set the googtrans cookie. This file only initializes the
 * widget and, if a page includes a [data-pref-lang-selector] container
 * itself, lets lang.js render into it.
 *
 * Requires lang.js to be loaded on the same page BEFORE this file for the
 * cookie to already reflect the resolved language; if lang.js is absent
 * (a page that hasn't been updated yet), this file still loads the widget
 * so manual selection continues to work, just without the unified
 * precedence.
 */
(function() {
  var LANGUAGES = 'en,zh-CN,fr,de,ar,pt,ru,ja,ko,hi,es,it';

  function initWidget() {
    var containers = document.querySelectorAll('[id^="gt-widget"]');
    if (!containers.length) return;
    var containerId = containers[0].id;
    var pageLang = document.documentElement.getAttribute('data-source-lang') || 'es';
    if (window.google && window.google.translate) {
      new google.translate.TranslateElement({
        pageLanguage: pageLang,
        includedLanguages: LANGUAGES,
        layout: google.translate.TranslateElement.InlineLayout.SIMPLE,
        autoDisplay: false
      }, containerId);
    }
  }

  window.googleTranslateElementInit  = initWidget;
  window.googleTranslateElementInit2 = initWidget;
  window.googleTranslateElementInit3 = initWidget;

  if (!document.querySelector('script[src*="translate.google.com"]')) {
    var s = document.createElement('script');
    s.src = '//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
    s.async = true;
    document.head.appendChild(s);
  }

  // lang.js (loaded first on every updated portal) already computed the
  // resolved language and set the googtrans cookie via
  // PreferendumLang.currentLanguage() — nothing else to do here. On a
  // page that does NOT yet include lang.js, PreferendumLang is undefined
  // and Google Translate simply starts untranslated until the user picks
  // a language from the widget itself (graceful degradation, not a
  // crash — see the typeof guard).
  if (typeof window.PreferendumLang === 'undefined') {
    console.warn('[translate.js] lang.js not loaded on this page — language is not centrally resolved here.');
  }
})();
