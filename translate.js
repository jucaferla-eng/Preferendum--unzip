/**
 * Preferendum — Global Translation Config
 * Change LANGUAGES here to add/remove languages across ALL portals.
 * Served at /translate.js by the backend.
 *
 * Auto-detects browser language on first visit and sets Google Translate
 * via the googtrans cookie. User can override manually with the widget.
 */
(function() {
  var LANGUAGES = 'en,zh-CN,fr,de,ar,pt,ru,ja,ko,hi,es';
  var PAGE_LANG = 'es';

  // Map browser language tags → Google Translate language codes
  var LANG_MAP = {
    'en': 'en', 'fr': 'fr', 'de': 'de', 'pt': 'pt',
    'ru': 'ru', 'ja': 'ja', 'ko': 'ko', 'hi': 'hi',
    'ar': 'ar', 'zh': 'zh-CN', 'es': 'es'
  };

  // Read current googtrans cookie value
  function getGoogtrans() {
    var match = document.cookie.match(/(^|;)\s*googtrans=([^;]+)/);
    return match ? decodeURIComponent(match[2]) : null;
  }

  // Set googtrans cookie on root path (required for Google Translate)
  function setGoogtrans(targetLang) {
    var val = '/' + PAGE_LANG + '/' + targetLang;
    document.cookie = 'googtrans=' + val + '; path=/';
    document.cookie = 'googtrans=' + val + '; path=/; domain=.' + location.hostname;
  }

  // Auto-detect browser language on first visit
  function autoDetectLanguage() {
    var stored = localStorage.getItem('pref_lang_set');
    if (stored) return; // User already has a preference set

    var existing = getGoogtrans();
    if (existing && existing !== '/' + PAGE_LANG + '/' + PAGE_LANG) return; // Already translated

    var browserLang = (navigator.language || navigator.userLanguage || 'es').toLowerCase();
    var primary = browserLang.split('-')[0]; // e.g. "en" from "en-US"

    // Special case: zh-TW, zh-HK → zh-TW; others → zh-CN
    var targetLang;
    if (browserLang.startsWith('zh-tw') || browserLang.startsWith('zh-hk')) {
      targetLang = 'zh-TW';
    } else {
      targetLang = LANG_MAP[primary];
    }

    if (!targetLang || targetLang === PAGE_LANG) return; // Already Spanish or unsupported

    localStorage.setItem('pref_lang_set', '1');
    setGoogtrans(targetLang);
    location.reload(); // Reload so Google Translate picks up the cookie
  }

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

  // Run auto-detection when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoDetectLanguage);
  } else {
    autoDetectLanguage();
  }
})();
