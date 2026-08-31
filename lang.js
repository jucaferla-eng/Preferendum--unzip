/**
 * Preferendum — canonical language resolver (COMPLETE INTERNATIONALIZATION
 * REMEDIATION).
 *
 * ONE authoritative decision, shared by every portal and every translation
 * mechanism (Google Translate, UI_STRINGS, MyMemory). None of those
 * mechanisms may independently decide the user's language anymore — they
 * all read PreferendumLang.currentLanguage() (or listen for the
 * 'preferendum:langchange' event) and follow it.
 *
 * PRECEDENCE (never reordered without updating the mutation tests in
 * test_i18n_resolver.py / test_i18n_resolver.mjs):
 *   1. Explicit language the user picked (persisted, ALWAYS wins)
 *   2. Device/browser preferred language (navigator.language)
 *   3. User profile/account country, via COUNTRY_DEFAULT_LANGUAGE — ONLY
 *      for countries with a genuinely defensible single default. A
 *      multilingual country (US, GB, AU, CA, ZA, NG, IN, CH, BE, ...) is
 *      deliberately ABSENT from that table — it falls through to (5).
 *   4. Reserved: a country-based default distinct from (3) would go here
 *      if ever introduced; today (3) and (4) collapse into one table.
 *   5. Global fallback (GLOBAL_FALLBACK_LANGUAGE).
 *
 * Exported as CommonJS (`require('./lang.js')`, for Node-based unit tests)
 * AND attached to `window.PreferendumLang` in a browser — same file, same
 * logic, no drift between what is tested and what runs.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PreferendumLang = factory();
  }
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  // The 12 languages this task requires reconciling support for. Order is
  // display order in the manual selector.
  var SUPPORTED_LANGUAGES = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi'];

  var LANGUAGE_NAMES = {
    es: 'Español', en: 'English', pt: 'Português', fr: 'Français',
    de: 'Deutsch', it: 'Italiano', ja: '日本語', ko: '한국어',
    zh: '简体中文', ar: 'العربية', ru: 'Русский', hi: 'हिन्दी',
  };

  var RTL_LANGUAGES = { ar: true };

  // Genuinely single-default-language countries only. A country ABSENT
  // here is not a bug — it means no defensible single default exists
  // (US, GB, AU, CA, ZA, NG, IN, CH, BE, and any other multilingual
  // market), so resolution falls through to the device-language check
  // above it in precedence, or the global fallback below it.
  var COUNTRY_DEFAULT_LANGUAGE = {
    CL: 'es', AR: 'es', PE: 'es', MX: 'es', CO: 'es', ES: 'es', UY: 'es',
    VE: 'es', EC: 'es', BO: 'es', PY: 'es', GL: 'es', GQ: 'es',
    BR: 'pt', PT: 'pt', AO: 'pt', MZ: 'pt',
    FR: 'fr',
    DE: 'de', AT: 'de',
    IT: 'it',
    JP: 'ja',
    KR: 'ko',
    CN: 'zh',
    RU: 'ru',
  };

  var GLOBAL_FALLBACK_LANGUAGE = 'es';

  // ── Pure precedence logic — no DOM, no globals read here, fully
  // unit-testable from Node with plain objects. ──────────────────────────

  function normalizeLangTag(tag) {
    if (!tag) return '';
    var primary = String(tag).split('-')[0].toLowerCase();
    return primary === 'zh' ? 'zh' : primary;
  }

  function normalizeCountry(country) {
    return country ? String(country).trim().toUpperCase() : '';
  }

  /**
   * input: { explicit, device, country }
   * explicit/device are raw tags (e.g. 'en-US'); country is an ISO2 code.
   * Returns { lang, reason } where reason is one of:
   *   'explicit' | 'device' | 'country' | 'global_fallback'
   */
  function resolveLanguage(input) {
    input = input || {};
    var explicit = normalizeLangTag(input.explicit);
    var device = normalizeLangTag(input.device);
    var country = normalizeCountry(input.country);

    if (explicit && SUPPORTED_LANGUAGES.indexOf(explicit) !== -1) {
      return { lang: explicit, reason: 'explicit' };
    }
    if (device && SUPPORTED_LANGUAGES.indexOf(device) !== -1) {
      return { lang: device, reason: 'device' };
    }
    if (country && Object.prototype.hasOwnProperty.call(COUNTRY_DEFAULT_LANGUAGE, country)) {
      return { lang: COUNTRY_DEFAULT_LANGUAGE[country], reason: 'country' };
    }
    return { lang: GLOBAL_FALLBACK_LANGUAGE, reason: 'global_fallback' };
  }

  // ── Browser-only wiring: persistence, DOM, Google Translate cookie,
  // manual selector, event dispatch. No-ops (or throws helpfully) outside
  // a browser, so the pure logic above stays testable in plain Node. ─────

  var EXPLICIT_KEY = 'pref_lang_explicit';
  var COUNTRY_KEY = 'pref_lang_country';
  var LEGACY_GOOGLE_FLAG_KEY = 'pref_lang_set'; // translate.js's old auto-detect flag

  function hasBrowser() {
    return typeof window !== 'undefined' && typeof document !== 'undefined';
  }

  function safeLocalStorageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function safeLocalStorageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }

  function getExplicit() {
    if (!hasBrowser()) return null;
    var v = safeLocalStorageGet(EXPLICIT_KEY);
    return v && SUPPORTED_LANGUAGES.indexOf(v) !== -1 ? v : null;
  }

  function setExplicit(lang) {
    if (!hasBrowser()) return;
    if (SUPPORTED_LANGUAGES.indexOf(lang) === -1) return;
    safeLocalStorageSet(EXPLICIT_KEY, lang);
    // Preserve existing users' preference: the OLD Google-Translate-only
    // flow already had a signal (the googtrans cookie) for anyone who had
    // manually picked a language before this remediation. That is merged
    // in on first read (see migrateLegacyPreference) rather than
    // discarded, so a returning user's prior choice is not silently reset
    // the first time this file runs on their device.
    safeLocalStorageSet(LEGACY_GOOGLE_FLAG_KEY, '1');
    applyGoogleTranslateCookie(lang);
    setDocumentLangAttrs(lang);
    dispatchChange(lang, 'explicit');
  }

  function getDeviceLanguage() {
    if (!hasBrowser()) return '';
    return navigator.language || navigator.userLanguage || '';
  }

  function getStoredCountry() {
    if (!hasBrowser()) return '';
    return safeLocalStorageGet(COUNTRY_KEY) || '';
  }

  /**
   * Called by a portal once it knows the user's profile/account country
   * (e.g. after login, or from the registration form) — tier 3 of the
   * precedence. Never overrides an explicit choice; only widens what
   * resolveLanguage can fall back to.
   */
  function setCountry(country) {
    if (!hasBrowser() || !country) return;
    safeLocalStorageSet(COUNTRY_KEY, String(country).toUpperCase());
  }

  /**
   * A user who picked a language under the OLD Google-Translate-only
   * mechanism (googtrans cookie set, pref_lang_set flag present, but no
   * pref_lang_explicit yet) gets that choice carried forward as their
   * explicit preference exactly once, instead of losing it.
   */
  function migrateLegacyPreference() {
    if (!hasBrowser()) return;
    if (getExplicit()) return; // already on the new system
    var legacyFlag = safeLocalStorageGet(LEGACY_GOOGLE_FLAG_KEY);
    if (!legacyFlag) return;
    var cookie = getGoogtransCookie();
    if (!cookie) return;
    var parts = cookie.split('/'); // "/es/en" -> ['', 'es', 'en']
    var target = parts[2];
    if (!target) return;
    var normalized = target === 'zh-CN' || target === 'zh-TW' ? 'zh' : normalizeLangTag(target);
    if (SUPPORTED_LANGUAGES.indexOf(normalized) !== -1) {
      safeLocalStorageSet(EXPLICIT_KEY, normalized);
    }
  }

  function getGoogtransCookie() {
    if (!hasBrowser()) return null;
    var match = document.cookie.match(/(^|;)\s*googtrans=([^;]+)/);
    return match ? decodeURIComponent(match[2]) : null;
  }

  /**
   * Coordinates Google Translate as a TRANSLATION ENGINE only — it no
   * longer runs its own independent auto-detect (see translate.js). This
   * sets the exact cookie Google's widget reads, using the SOURCE
   * language of the current page (document.documentElement.lang at load
   * time, defaulting to 'es' for the historically Spanish-authored
   * portals) so a page authored in English (e.g. root landing) is not
   * mistranslated as if it were Spanish source text.
   */
  function applyGoogleTranslateCookie(targetLang) {
    if (!hasBrowser()) return;
    var sourceLang = document.documentElement.getAttribute('data-source-lang') || 'es';
    if (targetLang === sourceLang) {
      // Google Translate's own convention for "no translation": source==target.
      var noop = '/' + sourceLang + '/' + sourceLang;
      document.cookie = 'googtrans=' + noop + '; path=/';
      document.cookie = 'googtrans=' + noop + '; path=/; domain=.' + location.hostname;
      return;
    }
    var googleTarget = targetLang === 'zh' ? 'zh-CN' : targetLang;
    var val = '/' + sourceLang + '/' + googleTarget;
    document.cookie = 'googtrans=' + val + '; path=/';
    document.cookie = 'googtrans=' + val + '; path=/; domain=.' + location.hostname;
  }

  function setDocumentLangAttrs(lang) {
    if (!hasBrowser()) return;
    document.documentElement.setAttribute('lang', lang);
    document.documentElement.setAttribute('dir', RTL_LANGUAGES[lang] ? 'rtl' : 'ltr');
  }

  function dispatchChange(lang, reason) {
    if (!hasBrowser()) return;
    try {
      document.dispatchEvent(new CustomEvent('preferendum:langchange', { detail: { lang: lang, reason: reason } }));
    } catch (e) { /* older WebView without CustomEvent support: no-op */ }
    // Bridge to the native iOS/Android shell (App.js), if this page is
    // running inside the app's react-native-webview — lets the NATIVE
    // chrome (loading/offline overlay, outside this page's DOM) match an
    // explicit choice on the next cold start. window.ReactNativeWebView
    // only exists inside that WebView; a no-op in a normal browser tab.
    try {
      if (window.ReactNativeWebView && typeof window.ReactNativeWebView.postMessage === 'function') {
        window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'preferendum:langchange', lang: lang, reason: reason }));
      }
    } catch (e) { /* not inside the app WebView — ignore */ }
  }

  /**
   * The ONE call every portal makes to get today's resolved language.
   * Also applies it (document lang/dir attrs + Google Translate cookie)
   * as a side effect of resolving, so a caller never needs to remember to
   * call applyGoogleTranslateCookie separately.
   */
  function currentLanguage() {
    migrateLegacyPreference();
    var result = resolveLanguage({
      explicit: getExplicit(),
      device: getDeviceLanguage(),
      country: getStoredCountry(),
    });
    setDocumentLangAttrs(result.lang);
    applyGoogleTranslateCookie(result.lang);
    return result.lang;
  }

  // ── Manual selector widget ──────────────────────────────────────────

  function renderSelectors() {
    if (!hasBrowser()) return;
    var containers = document.querySelectorAll('[data-pref-lang-selector]');
    if (!containers.length) return;
    var current = currentLanguage();
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.getAttribute('data-pref-lang-rendered') === '1') {
        el.value = current;
        continue;
      }
      var select = document.createElement('select');
      select.setAttribute('aria-label', 'Language / Idioma');
      select.style.cssText = 'background:#111a2e;color:#e8f0ff;border:1px solid rgba(255,255,255,0.2);' +
        'border-radius:6px;padding:4px 8px;font-size:13px;cursor:pointer;';
      SUPPORTED_LANGUAGES.forEach(function (code) {
        var opt = document.createElement('option');
        opt.value = code;
        opt.textContent = LANGUAGE_NAMES[code] || code;
        if (code === current) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener('change', function (ev) {
        setExplicit(ev.target.value);
        location.reload();
      });
      el.innerHTML = '';
      el.appendChild(select);
      el.setAttribute('data-pref-lang-rendered', '1');
    }
  }

  function init() {
    if (!hasBrowser()) return;
    var run = function () {
      currentLanguage();
      renderSelectors();
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', run);
    } else {
      run();
    }
  }

  init();

  return {
    SUPPORTED_LANGUAGES: SUPPORTED_LANGUAGES,
    LANGUAGE_NAMES: LANGUAGE_NAMES,
    RTL_LANGUAGES: RTL_LANGUAGES,
    COUNTRY_DEFAULT_LANGUAGE: COUNTRY_DEFAULT_LANGUAGE,
    GLOBAL_FALLBACK_LANGUAGE: GLOBAL_FALLBACK_LANGUAGE,
    normalizeLangTag: normalizeLangTag,
    resolveLanguage: resolveLanguage,
    currentLanguage: currentLanguage,
    setExplicit: setExplicit,
    setCountry: setCountry,
    getExplicit: getExplicit,
    renderSelectors: renderSelectors,
  };
});
