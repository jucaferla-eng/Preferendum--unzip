// test_cross_system_language_consistency.mjs — 30-LANGUAGE UI PARITY.
// Confirms the authoritative 30-language set is byte-for-byte identical
// across every place it's declared: lang.js (web canonical resolver),
// App.js (native shell), main.py (backend resolver), voter_portal.html's
// UI_STRINGS, and Prefy's own content — no duplicate/competing list has
// silently drifted from the others.
// Run with: node test_cross_system_language_consistency.mjs

import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const Lang = require('./lang.js');
const Content = require('./prefy-content.js');

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const CANONICAL_30 = [
  'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
  'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
  'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
].sort();
assertEqual(CANONICAL_30.length, 30, 'the canonical list itself has exactly 30 entries');

// ── lang.js ──────────────────────────────────────────────────────────
assertEqual(Lang.SUPPORTED_LANGUAGES.slice().sort(), CANONICAL_30, 'lang.js.SUPPORTED_LANGUAGES matches the canonical 30');

// ── App.js (native shell) ───────────────────────────────────────────
const appJsSrc = fs.readFileSync('App.js', 'utf-8');
const appJsMatch = appJsSrc.match(/const SUPPORTED_LANGUAGES = \[([\s\S]*?)\];/);
assertTrue(!!appJsMatch, 'App.js declares SUPPORTED_LANGUAGES');
const appJsSet = [...appJsMatch[1].matchAll(/'([a-z]{2,3})'/g)].map(m => m[1]).sort();
assertEqual(appJsSet, CANONICAL_30, 'App.js.SUPPORTED_LANGUAGES matches the canonical 30');

// ── main.py (backend resolver) ──────────────────────────────────────
const mainPySrc = fs.readFileSync('main.py', 'utf-8');
const mainPyMatch = mainPySrc.match(/_SUPPORTED_LANGUAGES = frozenset\(\{([\s\S]*?)\}\)/);
assertTrue(!!mainPyMatch, 'main.py declares _SUPPORTED_LANGUAGES');
const mainPySet = [...mainPyMatch[1].matchAll(/'([a-z]{2,3})'/g)].map(m => m[1]).sort();
assertEqual(mainPySet, CANONICAL_30, 'main.py._SUPPORTED_LANGUAGES matches the canonical 30');

// backend OTP catalogs must also cover all 30 (a resolver entry with no
// template would silently fall back to Spanish for a "supported" language).
const otpEmailMatch = mainPySrc.match(/_OTP_EMAIL_STRINGS = \{([\s\S]*?)\n\}/);
const otpEmailLangs = [...otpEmailMatch[1].matchAll(/^\s*'([a-z]{2,3})':\s*\{/gm)].map(m => m[1]).sort();
assertEqual(otpEmailLangs, CANONICAL_30, '_OTP_EMAIL_STRINGS covers the canonical 30');
const otpSmsMatch = mainPySrc.match(/_OTP_SMS_TEMPLATES = \{([\s\S]*?)\n\}/);
const otpSmsLangs = [...otpSmsMatch[1].matchAll(/^\s*'([a-z]{2,3})':/gm)].map(m => m[1]).sort();
assertEqual(otpSmsLangs, CANONICAL_30, '_OTP_SMS_TEMPLATES covers the canonical 30');

// ── voter_portal.html UI_STRINGS ────────────────────────────────────
const voterHtml = fs.readFileSync('voter_portal.html', 'utf-8');
const uiStart = voterHtml.indexOf('const UI_STRINGS = {');
const uiEnd = voterHtml.indexOf('\nfunction t(key)');
const voterSet = [...voterHtml.slice(uiStart, uiEnd).matchAll(/^\s{2}([a-z]{2,3}): \{/gm)].map(m => m[1]).sort();
assertEqual(voterSet, CANONICAL_30, 'voter_portal.html UI_STRINGS matches the canonical 30 (the closed gap)');

// ── Prefy's own content ─────────────────────────────────────────────
assertEqual(Object.keys(Content.STRINGS).sort(), CANONICAL_30, "Prefy's STRINGS matches the canonical 30");

// ── No duplicate/competing list: exactly one SUPPORTED_LANGUAGES-shaped
// declaration per file (catches an accidental second array left behind
// by a partial edit). ────────────────────────────────────────────────
assertEqual((appJsSrc.match(/const SUPPORTED_LANGUAGES = \[/g) || []).length, 1, 'App.js declares SUPPORTED_LANGUAGES exactly once');
assertEqual((mainPySrc.match(/_SUPPORTED_LANGUAGES = frozenset\(/g) || []).length, 1, 'main.py declares _SUPPORTED_LANGUAGES exactly once');
assertEqual((fs.readFileSync('lang.js', 'utf-8').match(/var SUPPORTED_LANGUAGES = \[/g) || []).length, 1, 'lang.js declares SUPPORTED_LANGUAGES exactly once');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
