// test_voter_portal_i18n.mjs — COMPLETE INTERNATIONALIZATION REMEDIATION
// Extracts and executes the actual UI_STRINGS/t()/getViewerLang()/
// detectContentLang() functions from voter_portal.html (not a
// hand-copied re-implementation) against a minimal stub DOM, to catch
// reference errors / logic bugs a plain syntax check would miss.
// Run with: node test_voter_portal_i18n.mjs

import fs from 'fs';
import vm from 'vm';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const html = fs.readFileSync('voter_portal.html', 'utf-8');

function extractBlock(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  if (start === -1) throw new Error(`marker not found: ${startMarker}`);
  const end = html.indexOf(endMarker, start);
  if (end === -1) throw new Error(`end marker not found after ${startMarker}: ${endMarker}`);
  return html.slice(start, end + endMarker.length);
}

// Extract UI_STRINGS + t() + getViewerLang() + detectContentLang() as they
// actually appear in the file, in file order, and eval them together.
const uiStringsBlock = extractBlock('const UI_STRINGS = {', '\n};');
const tFnBlock = extractBlock('function t(key)', '\n}');
const getViewerLangBlock = extractBlock('function getViewerLang() {', '\n}');
const detectLangBlock = extractBlock('function detectContentLang(text) {', '\n}');

const sandbox = {
  window: {},
  navigator: { language: 'en-US' },
  userCountry: '',
  console,
};
sandbox.window.PreferendumLang = null; // simulate lang.js not loaded, by default
vm.createContext(sandbox);

// vm contexts don't hoist top-level const/let onto the context object
// (a Node quirk) -- explicitly re-expose what the tests need afterward.
vm.runInContext(
  uiStringsBlock + '\n' + tFnBlock + '\n' + getViewerLangBlock + '\n' + detectLangBlock +
  '\nthis.UI_STRINGS = UI_STRINGS; this.t = t; this.getViewerLang = getViewerLang; this.detectContentLang = detectContentLang;',
  sandbox
);

// ── UI_STRINGS: all 30 canonical languages present with identical key
// sets (LANGUAGE EXPANSION — extended from the original 12; the 18
// additions close the gap disclosed in the prior Prefy integration
// report, where these languages were already reachable via lang.js's
// resolver but UI_STRINGS itself had never been translated for them). ──

const REQUIRED_LANGS = [
  'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
  'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
  'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
];
assertEqual(REQUIRED_LANGS.length, 30, 'the required-language list itself has exactly 30 entries');
const uiStringsLangs = Object.keys(sandbox.UI_STRINGS).sort();
assertEqual(uiStringsLangs, REQUIRED_LANGS.slice().sort(), 'UI_STRINGS must have exactly the 30 required languages');

const esKeys = Object.keys(sandbox.UI_STRINGS.es).sort();
assertEqual(esKeys.length, 29, 'the canonical es block has exactly 29 keys (verified count, not assumed)');
for (const lang of REQUIRED_LANGS) {
  const keys = Object.keys(sandbox.UI_STRINGS[lang]).sort();
  assertEqual(keys, esKeys, `UI_STRINGS.${lang} must have the exact same key set as UI_STRINGS.es`);
  for (const k of keys) {
    const v = sandbox.UI_STRINGS[lang][k];
    assertTrue(typeof v === 'string' && v.length > 0, `UI_STRINGS.${lang}.${k} must be a non-empty string`);
  }
}

// No fallback counts as coverage: none of the 18 newly-added languages
// may be a byte-identical copy of the Spanish block (that would mean
// "translated" was actually just "copy-pasted the fallback").
const NEWLY_ADDED_18 = ['nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he', 'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk'];
assertEqual(NEWLY_ADDED_18.length, 18, 'exactly 18 newly-added languages, matching the disclosed gap');
for (const lang of NEWLY_ADDED_18) {
  const identicalToEs = esKeys.every(k => sandbox.UI_STRINGS[lang][k] === sandbox.UI_STRINGS.es[k]);
  assertTrue(!identicalToEs, `UI_STRINGS.${lang} is genuinely translated, not a copy of es (would indicate silent fallback counted as coverage)`);
}
// And no two of the 18 are copies of EACH OTHER either (catches a
// copy-paste-then-forgot-to-translate mistake across languages).
for (let i = 0; i < NEWLY_ADDED_18.length; i++) {
  for (let j = i + 1; j < NEWLY_ADDED_18.length; j++) {
    const a = NEWLY_ADDED_18[i], b = NEWLY_ADDED_18[j];
    const identical = esKeys.every(k => sandbox.UI_STRINGS[a][k] === sandbox.UI_STRINGS[b][k]);
    assertTrue(!identical, `UI_STRINGS.${a} and UI_STRINGS.${b} are not accidentally identical to each other`);
  }
}

// ── t(): falls back to lang.js failing gracefully ───────────────────────

sandbox.window.PreferendumLang = null;
assertEqual(sandbox.getViewerLang(), 'es', 'getViewerLang falls back to es honestly when lang.js is absent');
assertEqual(sandbox.t('votes'), 'votos', 't() resolves through the fallback');

// ── t()/getViewerLang() actually call into window.PreferendumLang when present ──

let capturedCountry = null;
sandbox.window.PreferendumLang = {
  setCountry: (c) => { capturedCountry = c; },
  currentLanguage: () => 'fr',
};
sandbox.userCountry = 'FR';
assertEqual(sandbox.getViewerLang(), 'fr', 'getViewerLang delegates to PreferendumLang.currentLanguage()');
assertEqual(capturedCountry, 'FR', 'getViewerLang reports userCountry to PreferendumLang.setCountry()');
assertEqual(sandbox.t('votes'), 'votes', 't() uses the delegated language (French->votes key)');

// ── detectContentLang(): script-based detection is unambiguous ─────────

assertEqual(sandbox.detectContentLang('这是一个测试'), 'zh', 'Chinese script detected');
assertEqual(sandbox.detectContentLang('これはテストです'), 'ja', 'Japanese script detected');
assertEqual(sandbox.detectContentLang('이것은 테스트입니다'), 'ko', 'Korean script detected');
assertEqual(sandbox.detectContentLang('هذا اختبار'), 'ar', 'Arabic script detected');
assertEqual(sandbox.detectContentLang('Это тест'), 'ru', 'Russian (Cyrillic) script detected');
assertEqual(sandbox.detectContentLang('यह एक परीक्षण है'), 'hi', 'Hindi (Devanagari) script detected');
assertEqual(sandbox.detectContentLang('Esto es una prueba'), 'es', 'Latin script -> documented es fallback');
assertEqual(sandbox.detectContentLang(''), 'es', 'empty text -> es fallback, no crash');
assertEqual(sandbox.detectContentLang(null), 'es', 'null text -> es fallback, no crash');

// ── RTL (ar/fa/he/ur) — voter UI must not hardcode a physical
// left/right alignment that breaks in a mirrored layout; logical
// text-align:start/end (or none at all, relying on inherited
// `direction`) is required instead. ────────────────────────────────────
assertTrue(!/text-align:\s*left/.test(html), 'voter_portal.html has no hardcoded text-align:left (would misalign in RTL for ar/fa/he/ur)');
const Lang = require('./lang.js');
['ar', 'fa', 'he', 'ur'].forEach(code => {
  assertTrue(Lang.RTL_LANGUAGES[code] === true, `${code} is marked RTL in the canonical resolver (voter UI relies on this, not its own table)`);
});

console.log(`${passed} passed, ${failed} failed`);
if (failed) {
  console.log('FAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
