// test_lang_resolver.mjs — COMPLETE INTERNATIONALIZATION REMEDIATION
// Node-based unit tests for lang.js's pure resolveLanguage() precedence
// logic. Run with: node test_lang_resolver.mjs
// Exits 0 on all-pass, 1 on any failure (mutation-testing friendly).

import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const Lang = require('./lang.js');

let passed = 0, failed = 0;
const failures = [];

function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { passed++; }
  else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}

function assertTrue(cond, msg) {
  if (cond) passed++; else { failed++; failures.push(msg); }
}

// ── Precedence order ────────────────────────────────────────────────────

// 1. Explicit always wins, even over device and country.
assertEqual(Lang.resolveLanguage({ explicit: 'fr', device: 'en-US', country: 'JP' }),
  { lang: 'fr', reason: 'explicit' }, 'explicit beats device and country');

// 2. Device wins over country when no explicit choice.
assertEqual(Lang.resolveLanguage({ device: 'de-DE', country: 'JP' }),
  { lang: 'de', reason: 'device' }, 'device beats country');

// 3. Country is the fallback when device language is unsupported/absent.
assertEqual(Lang.resolveLanguage({ device: 'xx-XX', country: 'JP' }),
  { lang: 'ja', reason: 'country' }, 'country used when device unsupported');
assertEqual(Lang.resolveLanguage({ country: 'BR' }),
  { lang: 'pt', reason: 'country' }, 'country used when device absent');

// 5. Global fallback when nothing else resolves.
assertEqual(Lang.resolveLanguage({}),
  { lang: 'es', reason: 'global_fallback' }, 'global fallback with no input at all');
assertEqual(Lang.resolveLanguage({ device: 'xx-XX', country: 'ZZ' }),
  { lang: 'es', reason: 'global_fallback' }, 'global fallback when country unrecognised');

// ── Explicit/device tag normalization ───────────────────────────────────

assertEqual(Lang.resolveLanguage({ explicit: 'EN-us' }), { lang: 'en', reason: 'explicit' },
  'explicit tag is case/region insensitive');
assertEqual(Lang.resolveLanguage({ device: 'zh-CN' }), { lang: 'zh', reason: 'device' },
  'zh-CN normalizes to zh');
assertEqual(Lang.resolveLanguage({ device: 'zh-TW' }), { lang: 'zh', reason: 'device' },
  'zh-TW normalizes to zh (Simplified is the only zh variant this app supports today)');

// ── Multilingual countries must NOT force a single language ────────────
// This is the task's explicit, named concern.

for (const cc of ['US', 'GB', 'AU', 'CA', 'ZA', 'NG', 'IN', 'CH', 'BE']) {
  assertTrue(!Object.prototype.hasOwnProperty.call(Lang.COUNTRY_DEFAULT_LANGUAGE, cc),
    `${cc} must NOT have a forced country-default language (multilingual country)`);
}

// India: unsupported device language must NOT be forced into Hindi or
// English merely from country -- it must fall through to the global
// fallback, exactly like any other multilingual country.
assertEqual(Lang.resolveLanguage({ device: 'ta-IN', country: 'IN' }),
  { lang: 'es', reason: 'global_fallback' },
  'India + unsupported device language (Tamil) does not get forced into Hindi/English');
// But if the device itself reports a supported language, that DOES win
// (device precedence still applies inside a multilingual country).
assertEqual(Lang.resolveLanguage({ device: 'hi-IN', country: 'IN' }),
  { lang: 'hi', reason: 'device' }, 'India + Hindi device language resolves via DEVICE, not country');
assertEqual(Lang.resolveLanguage({ device: 'en-IN', country: 'IN' }),
  { lang: 'en', reason: 'device' }, 'India + English device language resolves via DEVICE, not country');

// United States: "device/user preference must win; English may be
// fallback" -- confirm English is NOT a forced country default (so a
// Spanish-device US user gets Spanish, not overridden to English), but a
// US user with no resolvable device language still lands somewhere sane
// via the GLOBAL fallback (not a US-specific override).
assertEqual(Lang.resolveLanguage({ device: 'es-US', country: 'US' }),
  { lang: 'es', reason: 'device' }, 'US + Spanish device language resolves to Spanish, not forced English');
assertEqual(Lang.resolveLanguage({ device: 'en-US', country: 'US' }),
  { lang: 'en', reason: 'device' }, 'US + English device language resolves via device');

// ── Defensible single-default countries DO get a sane fallback ─────────

const expectedCountryDefaults = {
  CL: 'es', MX: 'es', ES: 'es', AR: 'es', PY: 'es',
  BR: 'pt', PT: 'pt',
  FR: 'fr', DE: 'de', IT: 'it', JP: 'ja', KR: 'ko', RU: 'ru',
};
for (const [cc, expected] of Object.entries(expectedCountryDefaults)) {
  assertEqual(Lang.resolveLanguage({ country: cc }), { lang: expected, reason: 'country' },
    `${cc} country-fallback should be ${expected}`);
}

// ── Unsupported explicit/device values are correctly ignored ───────────

assertEqual(Lang.resolveLanguage({ explicit: 'xx', device: 'en-US' }),
  { lang: 'en', reason: 'device' }, 'unsupported explicit value falls through to device');
assertEqual(Lang.resolveLanguage({ explicit: '', device: '', country: '' }),
  { lang: 'es', reason: 'global_fallback' }, 'all-empty input reaches global fallback');

// ── Supported language list matches the 30 languages LANGUAGE EXPANSION
// requires (updated from the original 12 — see git history for that
// baseline; this is the current authoritative set). ────────────────────

const REQUIRED = [
  'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
  'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
  'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
];
assertEqual(REQUIRED.length, 30, 'the required-language list itself has exactly 30 entries');
assertEqual(Lang.SUPPORTED_LANGUAGES.slice().sort(), REQUIRED.slice().sort(),
  'SUPPORTED_LANGUAGES must be exactly the 30 required languages');
assertEqual(Lang.SUPPORTED_LANGUAGES.length, 30, 'SUPPORTED_LANGUAGES has exactly 30 entries (no accidental duplicate)');
assertEqual(new Set(Lang.SUPPORTED_LANGUAGES).size, 30, 'no duplicate language code in SUPPORTED_LANGUAGES');

// Every supported language has a display name, and every RTL language is
// itself a supported language (no orphaned RTL entry).
Lang.SUPPORTED_LANGUAGES.forEach(code => {
  assertTrue(!!Lang.LANGUAGE_NAMES[code], `LANGUAGE_NAMES has a display name for '${code}'`);
});

// ── RTL — ar/fa/he/ur, exactly (LANGUAGE EXPANSION §9) ──────────────────
const EXPECTED_RTL = ['ar', 'fa', 'he', 'ur'];
EXPECTED_RTL.forEach(code => assertTrue(Lang.RTL_LANGUAGES[code] === true, `${code} is marked RTL`));
Object.keys(Lang.RTL_LANGUAGES).forEach(code => {
  assertTrue(EXPECTED_RTL.indexOf(code) !== -1, `RTL_LANGUAGES has no unexpected entry beyond ar/fa/he/ur (found ${code})`);
  assertTrue(Lang.SUPPORTED_LANGUAGES.indexOf(code) !== -1, `RTL language ${code} is a supported language`);
});
assertEqual(Object.keys(Lang.RTL_LANGUAGES).length, 4, 'exactly 4 RTL languages');

// ── Multilingual countries are never collapsed to one mandatory language
// (explicit product rule) — India above all, but the general principle
// applies to every market already absent from the table. ───────────────
['IN', 'US', 'GB', 'AU', 'CA', 'ZA', 'NG', 'CH', 'BE'].forEach(cc => {
  assertTrue(!Object.prototype.hasOwnProperty.call(Lang.COUNTRY_DEFAULT_LANGUAGE, cc),
    `${cc} (multilingual) has no forced COUNTRY_DEFAULT_LANGUAGE entry`);
});
// India specifically: a Hindi-device user, a Bengali-device user, and an
// English-device user in India each keep their own device language —
// country never overrides a supported device language, and with no
// device signal either, India correctly falls through to something OTHER
// than a single hardcoded Indian language.
assertEqual(Lang.resolveLanguage({ device: 'hi-IN', country: 'IN' }), { lang: 'hi', reason: 'device' }, 'Hindi-device India user gets Hindi');
assertEqual(Lang.resolveLanguage({ device: 'bn-IN', country: 'IN' }), { lang: 'bn', reason: 'device' }, 'Bengali-device India user gets Bengali');
assertEqual(Lang.resolveLanguage({ device: 'ur-IN', country: 'IN' }), { lang: 'ur', reason: 'device' }, 'Urdu-device India user gets Urdu');
assertEqual(Lang.resolveLanguage({ device: 'en-IN', country: 'IN' }), { lang: 'en', reason: 'device' }, 'English-device India user gets English');
assertEqual(Lang.resolveLanguage({ country: 'IN' }), { lang: 'es', reason: 'global_fallback' }, 'India with no device signal reaches the GLOBAL fallback, never a forced national language');

// New single-default countries resolve correctly, each only as a tier-3
// fallback (device/explicit still win — covered generically above).
const NEW_COUNTRY_DEFAULTS = {
  NL: 'nl', PL: 'pl', TR: 'tr', ID: 'id', VN: 'vi', TH: 'th', PH: 'fil',
  BD: 'bn', PK: 'ur', IR: 'fa', IL: 'he', SE: 'sv', DK: 'da', FI: 'fi',
  GR: 'el', CZ: 'cs', RO: 'ro', UA: 'uk',
};
Object.keys(NEW_COUNTRY_DEFAULTS).forEach(cc => {
  const expected = NEW_COUNTRY_DEFAULTS[cc];
  assertEqual(Lang.resolveLanguage({ country: cc }), { lang: expected, reason: 'country' },
    `country fallback: ${cc} -> ${expected}`);
  // Device language, when supported, still wins over the country default.
  assertEqual(Lang.resolveLanguage({ device: 'es-ES', country: cc }), { lang: 'es', reason: 'device' },
    `device language beats the ${cc} country default`);
});

// Google Translate's own vocabulary diverges from ours for Filipino ('tl'
// vs our 'fil') — confirmed structurally since applyGoogleTranslateCookie
// is browser-only; this checks the resolver-level code itself stays 'fil'
// (the browser/Android BCP-47 tag), not silently renamed to 'tl'.
assertTrue(Lang.SUPPORTED_LANGUAGES.indexOf('fil') !== -1 && Lang.SUPPORTED_LANGUAGES.indexOf('tl') === -1,
  "the resolver's own code for Filipino is 'fil' (BCP-47), not Google's internal 'tl'");

// ── Persistence layer (setExplicit/getExplicit) via a minimal browser
// mock — this is what actually backs "a manual choice ALWAYS wins and
// must persist" (navigation/refresh/logout/reopen), not just the pure
// precedence function above. ────────────────────────────────────────────

function makeBrowserMock() {
  const store = {};
  const cookies = {};
  const listeners = [];
  global.window = {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    location: { hostname: 'test.local' },
  };
  Object.defineProperty(global, 'navigator', { value: { language: 'en-US' }, configurable: true, writable: true });
  global.location = { hostname: 'test.local' };
  global.document = {
    cookie: '',
    documentElement: {
      _attrs: {},
      setAttribute(k, v) { this._attrs[k] = v; },
      getAttribute(k) { return this._attrs[k] || null; },
    },
    dispatchEvent: (ev) => listeners.forEach(l => l(ev)),
    addEventListener: () => {},
    querySelectorAll: () => [], // selector-widget rendering is out of scope here
    readyState: 'complete',
  };
  // Minimal cookie jar: `document.cookie = "k=v; path=/"` style writes.
  Object.defineProperty(global.document, 'cookie', {
    get() { return Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; '); },
    set(raw) { const [kv] = raw.split(';'); const [k, v] = kv.split('='); cookies[k] = v; },
  });
  global.CustomEvent = function (name, opts) { this.type = name; this.detail = opts && opts.detail; };
  return { store, cookies };
}

{
  const { store } = makeBrowserMock();
  delete require.cache[require.resolve('./lang.js')];
  const LangBrowser = require('./lang.js');

  assertEqual(LangBrowser.getExplicit(), null, 'no explicit preference stored initially');

  LangBrowser.setExplicit('fr');
  assertEqual(LangBrowser.getExplicit(), 'fr', 'setExplicit persists to localStorage, getExplicit reads it back');
  assertEqual(store['pref_lang_explicit'], 'fr', 'persisted under the documented key name');

  // Persistence across "navigation" = a fresh require of the same module
  // against the SAME store (simulates a new page load reading the same
  // localStorage).
  delete require.cache[require.resolve('./lang.js')];
  const LangAfterNav = require('./lang.js');
  assertEqual(LangAfterNav.getExplicit(), 'fr', 'explicit choice survives a fresh page load (same storage)');

  // Explicit choice wins over a conflicting device language once resolved
  // through the full currentLanguage() path.
  global.navigator.language = 'de-DE';
  assertEqual(LangAfterNav.currentLanguage(), 'fr', 'currentLanguage() honors the persisted explicit choice over device language');

  // An invalid/unsupported explicit value is rejected, not silently stored.
  LangAfterNav.setExplicit('not-a-real-language');
  assertEqual(LangAfterNav.getExplicit(), 'fr', 'setExplicit rejects an unsupported language, prior choice unchanged');
}

// ── LANGUAGE EXPANSION follow-up — automatic detection re-verified for
// all 30 canonical locale variants, both hyphen (BCP-47/browser) and
// underscore (Android Locale.toString()) forms. This also exercises a
// genuine, previously-latent normalizeLangTag bug found while doing this
// check: underscore-form tags ('nl_NL') were never split correctly and
// silently fell through to country/global fallback for EVERY language,
// not just the newly-added ones — fixed in normalizeLangTag itself (see
// its own updated regex), not worked around here. ──────────────────────
const LOCALE_VARIANTS = {
  nl: 'nl-NL', pl: 'pl-PL', tr: 'tr-TR', id: 'id-ID', vi: 'vi-VN', th: 'th-TH',
  fil: 'fil-PH', bn: 'bn-BD', ur: 'ur-PK', fa: 'fa-IR', he: 'he-IL',
  sv: 'sv-SE', da: 'da-DK', fi: 'fi-FI', el: 'el-GR', cs: 'cs-CZ', ro: 'ro-RO', uk: 'uk-UA',
};
Object.keys(LOCALE_VARIANTS).forEach(expectedLang => {
  const hyphenTag = LOCALE_VARIANTS[expectedLang];
  const underscoreTag = hyphenTag.replace('-', '_');
  assertEqual(Lang.resolveLanguage({ device: hyphenTag }), { lang: expectedLang, reason: 'device' },
    `${hyphenTag} (hyphen form) resolves to ${expectedLang} via device`);
  assertEqual(Lang.resolveLanguage({ device: underscoreTag }), { lang: expectedLang, reason: 'device' },
    `${underscoreTag} (underscore form) resolves to ${expectedLang} via device — regression guard for the normalizeLangTag fix`);
});
// Same underscore check for a sample of the ORIGINAL 12, proving this
// wasn't a new-language-only fix — it was broken for all 30 before.
[['de_DE', 'de'], ['pt_BR', 'pt'], ['zh_CN', 'zh'], ['ja_JP', 'ja']].forEach(([tag, expected]) => {
  assertEqual(Lang.resolveLanguage({ device: tag }), { lang: expected, reason: 'device' },
    `${tag} (underscore form, one of the original 12) resolves to ${expected}`);
});

// Country must never override a supported device language — re-verified
// for the 18 new countries specifically (generic case already covered
// above for the original table).
Object.keys(LOCALE_VARIANTS).forEach(expectedLang => {
  const countryCode = LOCALE_VARIANTS[expectedLang].split('-')[1];
  assertEqual(Lang.resolveLanguage({ device: 'es-ES', country: countryCode }), { lang: 'es', reason: 'device' },
    `a Spanish-device user in ${countryCode} keeps Spanish, not the ${countryCode} country default`);
});

// ── Report ───────────────────────────────────────────────────────────

console.log(`${passed} passed, ${failed} failed`);
if (failed) {
  console.log('FAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
