// test_voter_portal_i18n.mjs — COMPLETE INTERNATIONALIZATION REMEDIATION
// Extracts and executes the actual UI_STRINGS/t()/getViewerLang()/
// detectContentLang() functions from voter_portal.html (not a
// hand-copied re-implementation) against a minimal stub DOM, to catch
// reference errors / logic bugs a plain syntax check would miss.
// Run with: node test_voter_portal_i18n.mjs

import fs from 'fs';
import vm from 'vm';

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

// ── UI_STRINGS: all 12 languages present with identical key sets ───────

const REQUIRED_LANGS = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi'];
const uiStringsLangs = Object.keys(sandbox.UI_STRINGS).sort();
assertEqual(uiStringsLangs, REQUIRED_LANGS.slice().sort(), 'UI_STRINGS must have exactly the 12 required languages');

const esKeys = Object.keys(sandbox.UI_STRINGS.es).sort();
for (const lang of REQUIRED_LANGS) {
  const keys = Object.keys(sandbox.UI_STRINGS[lang]).sort();
  assertEqual(keys, esKeys, `UI_STRINGS.${lang} must have the exact same key set as UI_STRINGS.es`);
  for (const k of keys) {
    assertTrue(typeof sandbox.UI_STRINGS[lang][k] === 'string' && sandbox.UI_STRINGS[lang][k].length > 0,
      `UI_STRINGS.${lang}.${k} must be a non-empty string`);
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

console.log(`${passed} passed, ${failed} failed`);
if (failed) {
  console.log('FAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
