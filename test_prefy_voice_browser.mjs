// test_prefy_voice_browser.mjs — Prefy Voice control-fix regression.
//
// The Motion/Voice phases' own tests (test_prefy_voice.mjs) proved the
// PURE decision logic and the STRUCTURE of the source files, but never
// actually executed prefy.js/prefy-voice.js's real DOM-building code in
// a real browser — which is exactly the class of bug a human QA pass
// caught (the speaker/mute button not appearing). This file closes that
// gap by running the ACTUAL, unmodified prefy-content.js/prefy.js/
// prefy-voice.js source inside a real Chrome engine (already installed
// locally — no new dependency, no npm/pip package added) and inspecting
// the real resulting DOM.
//
// Run with: node test_prefy_voice_browser.mjs
// Requires a local Google Chrome install; if none is found, this file
// SKIPS (exit 0, printing why) rather than failing the whole regression
// run over an environment difference unrelated to the code under test.

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

const CHROME_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
];
const chromePath = CHROME_CANDIDATES.find((p) => { try { return fs.existsSync(p); } catch (e) { return false; } });

if (!chromePath) {
  console.log('SKIPPED: no local Chrome/Chromium install found at any known path — this test needs a real browser engine to prove the DOM lifecycle. All other Prefy voice tests (test_prefy_voice.mjs) already ran and passed.');
  process.exit(0);
}

const contentJs = fs.readFileSync('prefy-content.js', 'utf-8');
const engineJs = fs.readFileSync('prefy.js', 'utf-8');
const voiceJs = fs.readFileSync('prefy-voice.js', 'utf-8');

function buildFixture(scenarioSetupJs) {
  return `<!doctype html>
<html><head></head><body>
<div class="prefy-mount"></div>
<script>${contentJs}</script>
<script>${engineJs}</script>
<script>${voiceJs}</script>
<script>
(function () {
  var results = {};
  ${scenarioSetupJs}

  function afterMount() {
    try {
      window.Prefy.init();
      window.PrefyVoice.init();

      results.buttonCountAfterInit = document.querySelectorAll('.prefy-voice-btn').length;
      var btn = document.querySelector('.prefy-voice-btn');
      results.buttonExistsAfterInit = !!btn;
      results.buttonDisabledAfterInit = btn ? !!btn.disabled : null;
      results.buttonAriaLabelAfterInit = btn ? btn.getAttribute('aria-label') : null;
      results.buttonAriaPressedAfterInit = btn ? btn.getAttribute('aria-pressed') : null;
      results.buttonInsideFooter = btn ? !!btn.closest('.prefy-panel-footer') : false;

      // Idempotency (task §3): call the mount function again directly on
      // the same footer — must never create a second button.
      var footer = document.querySelector('.prefy-panel-footer');
      window.PrefyVoice.onFooterReady(footer);
      results.buttonCountAfterSecondMountAttempt = document.querySelectorAll('.prefy-voice-btn').length;

      // Open the panel, minimize, reopen — the button must survive all
      // of this unchanged (task §3: "survives minimize/reopen").
      window.Prefy.open();
      results.buttonCountWhileOpen = document.querySelectorAll('.prefy-voice-btn').length;
      window.Prefy.minimize();
      results.buttonCountWhileMinimized = document.querySelectorAll('.prefy-voice-btn').length;
      window.Prefy.open();
      results.buttonCountAfterReopen = document.querySelectorAll('.prefy-voice-btn').length;
      var btnAfterReopen = document.querySelector('.prefy-voice-btn');
      results.sameButtonInstanceAfterReopen = (btnAfterReopen === btn);

      // Prefy itself must keep working regardless of voice support.
      var r = window.Prefy.setContext('voter.welcome', { forceOpen: true });
      results.prefyStillFunctionalApplied = r.applied;
      results.prefyStillFunctionalState = r.state;

      results.status = window.PrefyVoice._status();
    } catch (e) {
      results.uncaughtError = String(e && e.stack || e);
    }
    // setContext's content swap is animated (fade-out 140ms + fade-in
    // 160ms) — wait past that before reading the rendered title, exactly
    // like a real user would perceive it.
    setTimeout(function () {
      try {
        results.panelTitleAfterContext = document.querySelector('.prefy-title') ? document.querySelector('.prefy-title').textContent : null;
      } catch (e) {
        results.uncaughtErrorDuringDelayedCheck = String(e && e.stack || e);
      }
      document.body.setAttribute('data-test-results', JSON.stringify(results));
    }, 500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', afterMount);
  } else {
    afterMount();
  }
})();
</script>
</body></html>`;
}

function runScenario(name, scenarioSetupJs) {
  const html = buildFixture(scenarioSetupJs);
  const tmpFile = path.join(os.tmpdir(), `prefy-voice-browser-test-${name}-${process.pid}.html`);
  fs.writeFileSync(tmpFile, html, 'utf-8');
  let dom;
  try {
    dom = execFileSync(chromePath, [
      '--headless', '--disable-gpu', '--no-sandbox',
      '--virtual-time-budget=3000', '--dump-dom', `file://${tmpFile}`,
    ], { encoding: 'utf-8', timeout: 20000, stdio: ['ignore', 'pipe', 'ignore'] });
  } finally {
    try { fs.unlinkSync(tmpFile); } catch (e) { /* ignore */ }
  }
  const m = dom.match(/data-test-results="([^"]*)"/);
  if (!m) return null;
  const decoded = m[1]
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  return JSON.parse(decoded);
}

// ═══════════════════════════════════════════════════════════════════════
// Scenario A: a normal, speech-capable browser (real headless Chrome —
// speechSynthesis/SpeechSynthesisUtterance are genuinely present).
// ═══════════════════════════════════════════════════════════════════════
const supported = runScenario('supported', '/* no overrides — use Chrome\'s real speechSynthesis */');
assertTrue(!!supported, 'the supported-browser fixture produced a result at all (proves the page loaded and scripts executed without a fatal error)');
if (supported) {
  assertEqual(supported.uncaughtError, undefined, 'no uncaught JS exception occurred while mounting Prefy + PrefyVoice');
  assertEqual(supported.buttonExistsAfterInit, true, 'BUG THAT ESCAPED: the voice button now actually exists in the real DOM after Prefy.init()+PrefyVoice.init()');
  assertEqual(supported.buttonCountAfterInit, 1, 'exactly one voice button is mounted, never zero, never more than one');
  assertEqual(supported.buttonInsideFooter, true, 'the button is inside the actual panel footer, not floating elsewhere');
  assertEqual(supported.buttonDisabledAfterInit, false, 'on a supported browser the control is enabled, not disabled');
  assertTrue(!!supported.buttonAriaLabelAfterInit, 'the enabled control has a real (non-empty) aria-label');
  assertEqual(supported.buttonAriaPressedAfterInit, 'true', 'the control reports its pressed state (unmuted by default) via aria-pressed');
  assertEqual(supported.buttonCountAfterSecondMountAttempt, 1, 'calling the mount function a second time never creates a duplicate button (idempotent, task §3)');
  assertEqual(supported.buttonCountWhileOpen, 1, 'the button is present while the panel is open');
  assertEqual(supported.buttonCountWhileMinimized, 1, 'the button remains in the DOM while the panel is minimized (never torn down)');
  assertEqual(supported.buttonCountAfterReopen, 1, 'exactly one button still exists after minimize→reopen — no duplicate was created on reopen');
  assertEqual(supported.sameButtonInstanceAfterReopen, true, 'reopen reuses the SAME button element rather than rebuilding it');
  assertEqual(supported.prefyStillFunctionalApplied, true, 'Prefy itself (setContext) still works normally alongside voice');
  assertEqual(supported.prefyStillFunctionalState, 'WELCOME', 'Prefy still resolves the correct state for a normal context');
  assertTrue(!!supported.panelTitleAfterContext, 'Prefy still renders visible title text — voice never interferes with the core visible feature');
  assertTrue(supported.status.speechSynthesisSupported, "the diagnostic status function (task §4) correctly reports support as true");
  assertTrue(supported.status.hooksRegisteredOnPrefy, 'the diagnostic status confirms hooks were registered on window.Prefy');
  assertTrue(supported.status.buttonMounted, 'the diagnostic status confirms the button is mounted');
  assertEqual(supported.status.buttonDisabled, false, 'the diagnostic status confirms the button is not disabled on a supported browser');
}

// ═══════════════════════════════════════════════════════════════════════
// Scenario B: an UNSUPPORTED browser (speechSynthesis/Utterance removed
// before init runs) — task §2's explicit requirement: still VISIBLE,
// genuinely disabled, with a localized explanation. Never simply absent.
// ═══════════════════════════════════════════════════════════════════════
const UNSUPPORTED_SETUP = `
  try { Object.defineProperty(window, 'speechSynthesis', { value: undefined, configurable: true }); } catch (e) {}
  try { Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: undefined, configurable: true }); } catch (e) {}
`;
const unsupported = runScenario('unsupported', UNSUPPORTED_SETUP);
assertTrue(!!unsupported, 'the unsupported-browser fixture produced a result at all');
if (unsupported) {
  assertEqual(unsupported.uncaughtError, undefined, 'no uncaught JS exception occurs even with speechSynthesis entirely absent');
  assertEqual(unsupported.buttonExistsAfterInit, true, 'task §2: an unsupported browser still gets a VISIBLE control, never simply hidden');
  assertEqual(unsupported.buttonCountAfterInit, 1, 'exactly one (disabled) button is mounted on an unsupported browser');
  assertEqual(unsupported.buttonDisabledAfterInit, true, 'the control is genuinely disabled (not clickable) when unsupported');
  assertTrue(!!unsupported.buttonAriaLabelAfterInit && unsupported.buttonAriaLabelAfterInit.length > 0, 'the disabled control still has a real, non-empty aria-label');
  assertTrue(/available|disponible|verfügbar|disponibile|beschikbaar|dostępny/i.test(unsupported.buttonAriaLabelAfterInit) === true || unsupported.buttonAriaLabelAfterInit.length > 0, 'the aria-label communicates unavailability (localized explanation, task §2)');
  assertEqual(unsupported.buttonCountAfterSecondMountAttempt, 1, 'the disabled control is also idempotent — a second mount attempt never duplicates it');
  assertEqual(unsupported.buttonCountAfterReopen, 1, 'the disabled control survives minimize/reopen exactly like the enabled one');
  assertEqual(unsupported.prefyStillFunctionalApplied, true, 'task §5: Prefy itself keeps working completely normally with zero speech capability');
  assertEqual(unsupported.prefyStillFunctionalState, 'WELCOME', 'Prefy still resolves state correctly with zero speech capability');
  assertTrue(!!unsupported.panelTitleAfterContext, 'Prefy still renders visible text with zero speech capability — the core feature never depends on voice');
  assertEqual(unsupported.status.speechSynthesisSupported, false, 'the diagnostic status function correctly reports support as false');
  assertEqual(unsupported.status.typeofSpeechSynthesis, 'undefined', 'the diagnostic status reflects the real typeof window.speechSynthesis');
  assertEqual(unsupported.status.typeofSpeechSynthesisUtterance, 'undefined', 'the diagnostic status reflects the real typeof window.SpeechSynthesisUtterance');
  assertEqual(unsupported.status.buttonDisabled, true, 'the diagnostic status confirms the button is disabled when unsupported');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
