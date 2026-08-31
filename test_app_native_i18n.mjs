// test_app_native_i18n.mjs — I18N FINAL HARDENING Section 7.
// Extracts and executes the ACTUAL native-locale resolution functions
// from App.js (not a re-implementation) to verify the exact bug found via
// real iOS Simulator inspection (`defaults read -g AppleLocale` returns
// "es_CL", underscore-separated) stays fixed, plus the general
// precedence/fallback shape. React/JSX itself is NOT executed here (no
// RN runtime in this environment) -- only the plain-JS helper functions.
// Run with: node test_app_native_i18n.mjs

import fs from 'fs';
import vm from 'vm';

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const src = fs.readFileSync('App.js', 'utf-8');

function extractBlock(startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  if (start === -1) throw new Error(`marker not found: ${startMarker}`);
  const end = src.indexOf(endMarker, start);
  if (end === -1) throw new Error(`end marker not found after ${startMarker}: ${endMarker}`);
  return src.slice(start, end + endMarker.length);
}

const constsBlock = extractBlock('const SUPPORTED_LANGUAGES', "const BRIDGED_LANG_KEY = 'pref_lang_bridged_from_webview';");
const nativeStringsBlock = extractBlock('const NATIVE_STRINGS = {', '\n};');
const normalizeBlock = extractBlock('function normalizeLangTag(tag) {', '\n}');
const resolveBlock = extractBlock('function resolveNativeLanguage(bridgedLang, deviceTag) {', '\n}');

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(
  constsBlock + '\n' + nativeStringsBlock + '\n' + normalizeBlock + '\n' + resolveBlock +
  '\nthis.SUPPORTED_LANGUAGES = SUPPORTED_LANGUAGES; this.GLOBAL_FALLBACK_LANGUAGE = GLOBAL_FALLBACK_LANGUAGE; ' +
  'this.NATIVE_STRINGS = NATIVE_STRINGS; this.normalizeLangTag = normalizeLangTag; this.resolveNativeLanguage = resolveNativeLanguage;',
  sandbox
);

// ── The actual bug found via real iOS Simulator inspection ─────────────

assertEqual(sandbox.normalizeLangTag('es_CL'), 'es',
  'AppleLocale format (underscore, e.g. "es_CL" from a real simulator) must normalize to "es"');
assertEqual(sandbox.normalizeLangTag('es-CL'), 'es',
  'AppleLanguages[0] format (hyphen/BCP-47) must also normalize to "es"');
assertEqual(sandbox.normalizeLangTag('zh_CN'), 'zh', 'zh_CN (underscore) normalizes to zh');
assertEqual(sandbox.normalizeLangTag('zh-TW'), 'zh', 'zh-TW (hyphen) normalizes to zh');
assertEqual(sandbox.normalizeLangTag(''), '', 'empty stays empty');
assertEqual(sandbox.normalizeLangTag(null), '', 'null stays empty, no crash');

// ── SUPPORTED_LANGUAGES matches lang.js's list exactly (no drift) ──────

const REQUIRED = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi'];
assertEqual(sandbox.SUPPORTED_LANGUAGES.slice().sort(), REQUIRED.slice().sort(),
  "App.js's SUPPORTED_LANGUAGES must match lang.js's exactly");

// ── NATIVE_STRINGS covers all 12 languages with both required fields ──

for (const lang of REQUIRED) {
  assertTrue(!!sandbox.NATIVE_STRINGS[lang], `NATIVE_STRINGS missing ${lang}`);
  assertTrue(!!sandbox.NATIVE_STRINGS[lang].brand, `NATIVE_STRINGS.${lang}.brand missing`);
  assertTrue(!!sandbox.NATIVE_STRINGS[lang].offline, `NATIVE_STRINGS.${lang}.offline missing`);
}

// ── resolveNativeLanguage precedence: bridged (explicit) > device > fallback ──

assertEqual(sandbox.resolveNativeLanguage('fr', 'de-DE'), 'fr', 'bridged explicit choice wins over device');
assertEqual(sandbox.resolveNativeLanguage(null, 'de-DE'), 'de', 'device wins when no bridged value');
assertEqual(sandbox.resolveNativeLanguage(null, 'es_CL'), 'es', 'device in AppleLocale underscore format resolves correctly');
assertEqual(sandbox.resolveNativeLanguage(null, 'xx-XX'), 'es', 'unsupported device language falls back to global default');
assertEqual(sandbox.resolveNativeLanguage(null, null), 'es', 'nothing available -> global fallback, no crash');
assertEqual(sandbox.resolveNativeLanguage('not-real', 'de-DE'), 'de', 'unsupported bridged value ignored, falls through to device');

// ── No infinite message/reload loop: onMessage handler must not call
// injectJavaScript or otherwise talk back to the WebView in response to
// a langchange message (verified structurally: the handler only calls
// local state setters and SecureStore, never webRef.current.*). ────────

const onMessageBlock = extractBlock('onMessage={(e) => {', '        }}');
assertTrue(!onMessageBlock.includes('injectJavaScript'),
  'onMessage handler must not call injectJavaScript (would risk a message/reload loop)');
assertTrue(!onMessageBlock.includes('.reload'),
  'onMessage handler must not reload the WebView (would reset the user\'s position in the voting flow)');
assertTrue(onMessageBlock.includes('setNativeLang'), 'onMessage handler updates native state');
assertTrue(onMessageBlock.includes('SecureStore.setItemAsync'), 'onMessage handler persists the bridged language');

console.log(`${passed} passed, ${failed} failed`);
if (failed) {
  console.log('FAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
