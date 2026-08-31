// test_prefy_real_page.mjs — Prefy real-browser QA remediation.
//
// The human tester's failures (missing voice button, dead "explain
// again" button, Help showing the generic missing-explanation fallback)
// were never caught because every prior automated test either checked
// pure logic or a SYNTHETIC fixture — never the ACTUAL bytes this
// server sends for GET /voter, exercised through the page's OWN real
// bootstrap/view-switching functions. This file closes that gap.
//
// Technique: fetch the live HTTP response for /voter (the literal bytes
// a browser receives — not a copy of the source file), rewrite its
// three Prefy <script>/<link> tags to absolute http://127.0.0.1:8000/...
// URLs (so they still load correctly when the page itself is opened via
// file://, which is what lets us append a driver script and read
// results back via --dump-dom), and run the result in real headless
// Chrome (already installed locally — no new dependency). Every
// function invoked by the driver (switchTab, showVerifyScreen,
// Prefy.openHelp, Prefy.reopenCurrent, Prefy.minimize/open) is the
// REAL, unmodified function from the real served page — nothing here
// reimplements any application logic.
//
// Requires the local server to already be running at
// http://127.0.0.1:8000 (see the phase report for how to start it).
//
// Run with: node test_prefy_real_page.mjs

import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFileSync } from 'child_process';

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const SERVER = 'http://127.0.0.1:8000';

const CHROME_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
];
const chromePath = CHROME_CANDIDATES.find((p) => { try { return fs.existsSync(p); } catch (e) { return false; } });

if (!chromePath) {
  console.log('SKIPPED: no local Chrome/Chromium install found — cannot exercise the real served page in a real browser engine.');
  process.exit(0);
}

let serverUp = false;
try {
  const r = await fetch(`${SERVER}/voter`);
  serverUp = r.ok;
} catch (e) { serverUp = false; }

if (!serverUp) {
  console.log(`SKIPPED: no local server responding at ${SERVER}/voter. Start it (see the phase's own instructions) and re-run this file.`);
  process.exit(0);
}

const realHtml = await (await fetch(`${SERVER}/voter`)).text();
assertTrue(realHtml.length > 1000, 'fetched a real, non-trivial HTML response from the live server');
assertTrue(realHtml.includes('/prefy-voice.js'), 'the LIVE served page currently references /prefy-voice.js (not a stale pre-voice-phase copy)');

// Rewrite the Prefy resource references to absolute URLs so this exact
// HTML still loads/executes correctly from a file:// origin (needed so
// we can append a driver script and read results via --dump-dom without
// a full CDP/WebSocket driver or any new dependency). Everything else in
// the page — every function under test — is untouched.
const rewritten = realHtml
  .replace('<script src="/prefy-content.js"></script>', `<script src="${SERVER}/prefy-content.js"></script>`)
  .replace('<script src="/prefy.js"></script>', `<script src="${SERVER}/prefy.js"></script>`)
  .replace('<script src="/prefy-voice.js"></script>', `<script src="${SERVER}/prefy-voice.js"></script>`)
  .replace('<link rel="stylesheet" href="/prefy.css">', `<link rel="stylesheet" href="${SERVER}/prefy.css">`);
assertTrue(rewritten !== realHtml, 'the resource-URL rewrite actually changed something (proves the expected tags were found in the real response)');

const DRIVER = `
<script>
(function () {
  var results = {};
  function safeCall(name, fn) {
    try { results[name] = fn(); } catch (e) { results[name + '_error'] = String(e && e.stack || e); }
  }

  setTimeout(function () {
    safeCall('typeofPrefy', function () { return typeof window.Prefy; });
    safeCall('typeofPrefyVoice', function () { return typeof window.PrefyVoice; });

    // Fresh, unauthenticated load: the auth screen's login tab is the
    // real default (per the static markup + the bootstrap fix) — Prefy
    // must already know this BEFORE any click.
    safeCall('initialContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('initialState', function () { return window.Prefy._debugState().currentState; });

    window.Prefy.open();
    safeCall('footerButtonCount', function () { return document.querySelectorAll('.prefy-panel-footer button').length; });
    safeCall('footerButtonTexts', function () {
      return Array.from(document.querySelectorAll('.prefy-panel-footer button')).map(function (b) { return b.textContent || b.getAttribute('aria-label'); });
    });
    safeCall('voiceButtonCount', function () { return document.querySelectorAll('.prefy-voice-btn').length; });

    // Help, on the real initial screen — must NOT be the generic fallback.
    var helpResult = window.Prefy.openHelp();
    safeCall('helpQaJoined', function () { return helpResult.qa.join(' | '); });
    safeCall('helpShowsGenericFallback', function () {
      return helpResult.qa.join(' ').indexOf('Aún no tengo una explicación preparada') !== -1;
    });

    // "Volver a explicar esta pantalla" — must be a real, observable
    // re-render, not a no-op.
    var beforeSeq = window.Prefy._transitionSeqValue();
    window.Prefy.reopenCurrent();
    safeCall('reopenActuallyRan', function () { return window.Prefy._transitionSeqValue() > beforeSeq; });
    safeCall('contextAfterReopen', function () { return window.Prefy._debugState().currentContextKey; });

    // Registration tab — a distinct, correctly-registered context (not
    // the generic fallback, not left over from login).
    window.switchTab('register');
    safeCall('registerContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    var helpOnRegister = window.Prefy.openHelp();
    safeCall('helpOnRegisterShowsFallback', function () {
      return helpOnRegister.qa.join(' ').indexOf('Aún no tengo una explicación preparada') !== -1;
    });

    // Back to login, then the verification screen (a real, unmodified
    // page function; its one conditional fetch is gated on a truthy
    // token, which is absent here, so no network call is made).
    window.switchTab('login');
    window.showVerifyScreen();
    safeCall('verifyContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    var helpOnVerify = window.Prefy.openHelp();
    safeCall('helpOnVerifyShowsFallback', function () {
      return helpOnVerify.qa.join(' ').indexOf('Aún no tengo una explicación preparada') !== -1;
    });

    // Minimize / reopen must retain all three footer controls.
    window.Prefy.minimize();
    safeCall('voiceButtonCountWhileMinimized', function () { return document.querySelectorAll('.prefy-voice-btn').length; });
    window.Prefy.open();
    safeCall('footerButtonCountAfterReopen', function () { return document.querySelectorAll('.prefy-panel-footer button').length; });
    safeCall('voiceButtonCountAfterReopen', function () { return document.querySelectorAll('.prefy-voice-btn').length; });

    document.body.setAttribute('data-test-results', JSON.stringify(results));
  }, 800);
})();
</script>
</body>`;

const finalHtml = rewritten.replace('</body>', DRIVER);

const tmpFile = path.join(os.tmpdir(), `prefy-real-page-test-${process.pid}.html`);
fs.writeFileSync(tmpFile, finalHtml, 'utf-8');
let dom;
try {
  dom = execFileSync(chromePath, [
    '--headless', '--disable-gpu', '--no-sandbox',
    '--virtual-time-budget=4000', '--dump-dom', `file://${tmpFile}`,
  ], { encoding: 'utf-8', timeout: 20000, stdio: ['ignore', 'pipe', 'ignore'] });
} finally {
  try { fs.unlinkSync(tmpFile); } catch (e) { /* ignore */ }
}

const m = dom.match(/data-test-results="([^"]*)"/);
assertTrue(!!m, 'the driver script produced a result at all (the real page loaded and ran without a fatal parse error)');

if (m) {
  const decoded = m[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  const r = JSON.parse(decoded);

  assertEqual(r.typeofPrefy, 'object', 'window.Prefy exists on the real page (the module namespace object, per its factory return)');
  assertEqual(r.typeofPrefyVoice, 'object', 'window.PrefyVoice exists on the real page');

  assertEqual(r.footerButtonCount, 3, 'BUG THAT ESCAPED (voice button): the real served page shows exactly 3 footer controls — [voice] [Ayuda] [Volver a explicar esta pantalla]');
  assertEqual(r.voiceButtonCount, 1, 'exactly one voice button exists on the real served page');
  assertTrue(Array.isArray(r.footerButtonTexts) && r.footerButtonTexts.some((t) => /Ayuda/.test(t)), 'the real footer includes "Ayuda"');
  assertTrue(Array.isArray(r.footerButtonTexts) && r.footerButtonTexts.some((t) => /Volver a explicar/.test(t)), 'the real footer includes "Volver a explicar esta pantalla"');

  assertTrue(!!r.initialContextKey, 'BUG THAT ESCAPED (current-context resolution): the real page resolves a non-null context on a fresh, unauthenticated load, before any click');
  assertEqual(r.initialContextKey, 'voter.auth.login', 'the real default landing screen (login tab) resolves to its own canonical context, not null/unknown');

  assertEqual(r.helpShowsGenericFallback, false, 'BUG THAT ESCAPED (Help): Help on the real initial screen no longer shows "Aún no tengo una explicación preparada..."');
  assertTrue(!!r.helpQaJoined && r.helpQaJoined.length > 20, 'Help produces real, non-trivial explanatory content on the real initial screen');

  assertEqual(r.reopenActuallyRan, true, 'BUG THAT ESCAPED ("Volver a explicar esta pantalla"): clicking it (reopenCurrent) now demonstrably runs a new transition, not a silent no-op');
  assertEqual(r.contextAfterReopen, 'voter.auth.login', 'reopen replays the SAME real current context, not a reset to WELCOME');

  assertEqual(r.registerContextKey, 'voter.register.overview', 'switching to the registration tab on the real page resolves its own canonical context');
  assertEqual(r.helpOnRegisterShowsFallback, false, 'Help on the real registration tab no longer shows the generic missing-explanation fallback');

  assertEqual(r.verifyContextKey, 'voter.verify.overview', 'the real showVerifyScreen() function resolves its own canonical context');
  assertEqual(r.helpOnVerifyShowsFallback, false, 'Help on the real verification screen no longer shows the generic missing-explanation fallback');

  assertEqual(r.voiceButtonCountWhileMinimized, 1, 'the voice control survives minimize on the real page');
  assertEqual(r.footerButtonCountAfterReopen, 3, 'all three footer controls survive minimize→reopen on the real page');
  assertEqual(r.voiceButtonCountAfterReopen, 1, 'exactly one (not zero, not duplicated) voice button survives minimize→reopen on the real page');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
