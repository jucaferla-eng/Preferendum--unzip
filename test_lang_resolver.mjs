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

// ── Supported language list matches the 12 languages this task names ───

const REQUIRED = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi'];
assertEqual(Lang.SUPPORTED_LANGUAGES.slice().sort(), REQUIRED.slice().sort(),
  'SUPPORTED_LANGUAGES must be exactly the 12 required languages');

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

// ── Report ───────────────────────────────────────────────────────────

console.log(`${passed} passed, ${failed} failed`);
if (failed) {
  console.log('FAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
