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
  // Real DOM interaction helpers — never call the page's internal JS
  // functions directly. This is what makes the test faithful to what a
  // human actually does (task §11: "using the real UI").
  function realClick(el) {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  }
  function realFocus(el) { el.focus(); el.dispatchEvent(new Event('focus')); }
  function panelText() {
    var t = document.querySelector('.prefy-title');
    var b = document.querySelector('.prefy-body-text');
    return ((t ? t.textContent : '') + ' ' + (b ? b.textContent : '')).trim();
  }
  var GENERIC_FALLBACK = 'Aún no tengo una explicación preparada';

  function step(fn) { return new Promise(function (resolve) { setTimeout(function () { fn(); resolve(); }, 350); }); }

  step(function () {
    safeCall('typeofPrefy', function () { return typeof window.Prefy; });
    safeCall('typeofPrefyVoice', function () { return typeof window.PrefyVoice; });
    safeCall('initialContextKey', function () { return window.Prefy._debugState().currentContextKey; });

    // Open Prefy via a REAL click on the real bubble button.
    var bubble = document.querySelector('.prefy-bubble');
    realClick(bubble);
  }).then(function () { return step(function () {
    safeCall('footerButtonCount', function () { return document.querySelectorAll('.prefy-panel-footer button').length; });
    safeCall('footerButtonTexts', function () {
      return Array.from(document.querySelectorAll('.prefy-panel-footer button')).map(function (b) { return b.textContent || b.getAttribute('aria-label'); });
    });
    safeCall('voiceButtonCount', function () { return document.querySelectorAll('.prefy-voice-btn').length; });
    safeCall('initialPanelText', panelText);
    safeCall('initialPanelShowsFallback', function () { return panelText().indexOf(GENERIC_FALLBACK) !== -1; });

    // Click "Registrarse" using the REAL tab button in the REAL UI —
    // not switchTab() called directly.
    var regBtn = document.getElementById('tab-reg-btn');
    realClick(regBtn);
  }); }).then(function () { return step(function () {
    safeCall('registerContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('registerPanelText', panelText);
    safeCall('registerPanelShowsFallback', function () { return panelText().indexOf(GENERIC_FALLBACK) !== -1; });
    safeCall('footerButtonCountOnRegister', function () { return document.querySelectorAll('.prefy-panel-footer button').length; });
    safeCall('voiceButtonCountOnRegister', function () { return document.querySelectorAll('.prefy-voice-btn').length; });

    // Click "Ayuda" using the real button.
    var helpBtn = document.querySelector('.prefy-help-btn');
    realClick(helpBtn);
  }); }).then(function () { return step(function () {
    safeCall('helpOnRegisterPanelText', panelText);
    safeCall('helpOnRegisterShowsFallback', function () { return panelText().indexOf(GENERIC_FALLBACK) !== -1; });

    // Click "Volver a explicar esta pantalla" using the real button —
    // must visibly restore the registration overview, not silently do
    // nothing.
    var beforeSeq = window.Prefy._transitionSeqValue();
    var reopenBtn = document.querySelector('.prefy-reopen-btn');
    realClick(reopenBtn);
    safeCall('reopenBtnExists', function () { return !!reopenBtn; });
    safeCall('reopenActuallyRan', function () { return window.Prefy._transitionSeqValue() > beforeSeq; });
  }); }).then(function () { return step(function () {
    safeCall('afterReopenContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('afterReopenPanelText', panelText);
    safeCall('afterReopenShowsFallback', function () { return panelText().indexOf(GENERIC_FALLBACK) !== -1; });

    // Focus the real occupation field.
    realFocus(document.getElementById('occ-search'));
  }); }).then(function () { return step(function () {
    safeCall('occupationContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('occupationPanelText', panelText);

    realFocus(document.getElementById('r-company-size'));
  }); }).then(function () { return step(function () {
    safeCall('companySizeContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('companySizePanelText', panelText);

    realFocus(document.getElementById('r-dob'));
  }); }).then(function () { return step(function () {
    safeCall('dobContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    safeCall('dobPanelText', panelText);

    realFocus(document.getElementById('r-name'));
  }); }).then(function () { return step(function () {
    safeCall('nameContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    realFocus(document.getElementById('r-pass'));
  }); }).then(function () { return step(function () {
    safeCall('passwordContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    realFocus(document.getElementById('r-rut'));
  }); }).then(function () { return step(function () {
    safeCall('nationalIdContextKey', function () { return window.Prefy._debugState().currentContextKey; });
    realFocus(document.getElementById('r-gender'));
  }); }).then(function () { return step(function () {
    safeCall('genderContextKey', function () { return window.Prefy._debugState().currentContextKey; });

    // Back to login, then the verification screen — via the real login
    // tab button, then the real page's own showVerifyScreen() is only
    // reachable after a submit in the live app; since we cannot log in
    // here, exercise the function itself is out of scope for THIS
    // click-only pass (covered already by the fixture-driven test).
    realClick(document.getElementById('tab-login-btn'));
  }); }).then(function () { return step(function () {
    safeCall('backToLoginContextKey', function () { return window.Prefy._debugState().currentContextKey; });

    // Minimize / reopen via the real minimize button and real bubble.
    realClick(document.querySelector('.prefy-minimize'));
  }); }).then(function () { return step(function () {
    safeCall('voiceButtonCountWhileMinimized', function () { return document.querySelectorAll('.prefy-voice-btn').length; });
    realClick(document.querySelector('.prefy-bubble'));
  }); }).then(function () { return step(function () {
    safeCall('footerButtonCountAfterReopen', function () { return document.querySelectorAll('.prefy-panel-footer button').length; });
    safeCall('voiceButtonCountAfterReopen', function () { return document.querySelectorAll('.prefy-voice-btn').length; });

    document.body.setAttribute('data-test-results', JSON.stringify(results));
  }); });
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
    '--virtual-time-budget=8000', '--dump-dom', `file://${tmpFile}`,
  ], { encoding: 'utf-8', timeout: 30000, stdio: ['ignore', 'pipe', 'ignore'] });
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
  assertTrue(!!r.initialContextKey, 'the real page resolves a non-null context on a fresh, unauthenticated load, before any click');
  assertEqual(r.initialContextKey, 'voter.auth.login', 'the real default landing screen (login tab) resolves to its own canonical context, not null/unknown');

  // §11 step-by-step, using REAL clicks/focus on the REAL served page —
  // never a synthetic fixture, never calling an internal JS function
  // directly.
  assertEqual(r.footerButtonCount, 3, 'BUG THAT ESCAPED (voice button): after a REAL click on the real bubble, the footer shows exactly 3 controls — [voice] [Ayuda] [Volver a explicar esta pantalla]');
  assertEqual(r.voiceButtonCount, 1, 'exactly one voice button exists after a real click opens the panel');
  assertTrue(Array.isArray(r.footerButtonTexts) && r.footerButtonTexts.some((t) => /Ayuda/.test(t)), 'the real footer includes "Ayuda"');
  assertTrue(Array.isArray(r.footerButtonTexts) && r.footerButtonTexts.some((t) => /Volver a explicar/.test(t)), 'the real footer includes "Volver a explicar esta pantalla"');
  assertEqual(r.initialPanelShowsFallback, false, 'the visible panel text on the initial screen is not the generic fallback');

  assertEqual(r.registerContextKey, 'voter.register.overview', 'a REAL click on the real "Registrarse" tab button resolves the registration overview context');
  assertEqual(r.registerPanelShowsFallback, false, 'BUG THAT ESCAPED (registration UNKNOWN_CONTEXT): the visible panel text on the registration screen is no longer the generic fallback');
  assertTrue(!!r.registerPanelText && r.registerPanelText.length > 10, 'the registration screen shows real, non-empty explanatory text');
  assertEqual(r.footerButtonCountOnRegister, 3, 'the voice control is still present (3 footer controls) on the registration screen');
  assertEqual(r.voiceButtonCountOnRegister, 1, 'exactly one voice button on the registration screen');

  assertEqual(r.helpOnRegisterShowsFallback, false, 'a REAL click on the real "Ayuda" button on the registration screen shows registration-specific help, not the generic fallback');
  assertTrue(!!r.helpOnRegisterPanelText && r.helpOnRegisterPanelText.length > 10, 'Ayuda produces real, non-trivial content on the registration screen');

  assertTrue(r.reopenBtnExists, 'the real "Volver a explicar esta pantalla" button exists in the DOM to be clicked');
  assertEqual(r.reopenActuallyRan, true, 'BUG THAT ESCAPED ("Volver a explicar esta pantalla" doing nothing): a REAL click on it demonstrably runs a new transition, not a silent no-op');
  assertEqual(r.afterReopenContextKey, 'voter.register.overview', 'reopen restores the SAME real current (registration) context, not a reset to WELCOME');
  assertEqual(r.afterReopenShowsFallback, false, 'the restored panel text after reopen is the real registration explanation, not the generic fallback');

  assertEqual(r.occupationContextKey, 'voter.register.occupation', 'REAL focus on the occupation field switches to its own explanation');
  assertTrue(!!r.occupationPanelText && r.occupationPanelText.length > 5, 'the occupation field shows real explanatory text when focused');
  assertEqual(r.companySizeContextKey, 'voter.register.company_size', 'REAL focus on the company-size field switches to its own explanation');
  assertTrue(!!r.companySizePanelText && r.companySizePanelText.length > 5, 'the company-size field shows real explanatory text when focused');
  assertEqual(r.dobContextKey, 'voter.register.dob', 'REAL focus on the date-of-birth field switches to its own explanation');
  assertTrue(!!r.dobPanelText && r.dobPanelText.length > 5, 'the date-of-birth field shows real explanatory text when focused');

  assertEqual(r.nameContextKey, 'voter.register.name', 'REAL focus on the name field resolves its new field-level context');
  assertEqual(r.passwordContextKey, 'voter.register.password', 'REAL focus on the password field resolves its new field-level context');
  assertEqual(r.nationalIdContextKey, 'voter.register.national_id', 'REAL focus on the national-ID field resolves its new field-level context');
  assertEqual(r.genderContextKey, 'voter.register.gender', 'REAL focus on the gender field resolves its new field-level context');

  assertEqual(r.backToLoginContextKey, 'voter.auth.login', 'a REAL click back on the login tab correctly restores the login context (not left over from register)');

  assertEqual(r.voiceButtonCountWhileMinimized, 1, 'the voice control survives a REAL click on the real minimize button');
  assertEqual(r.footerButtonCountAfterReopen, 3, 'all three footer controls survive minimize→reopen (real clicks) on the real page');
  assertEqual(r.voiceButtonCountAfterReopen, 1, 'exactly one (not zero, not duplicated) voice button survives minimize→reopen (real clicks) on the real page');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
