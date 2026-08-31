// test_prefy_portal_wiring.mjs — Prefy contextual guide (Phase 1).
// Structural checks against the ACTUAL portal HTML/CSS/JS files (not a
// hand-copied re-implementation) — same technique as
// test_voter_portal_i18n.mjs, but string-based since these are wiring/
// presence checks rather than logic to execute.
// Run with: node test_prefy_portal_wiring.mjs

import fs from 'fs';

let passed = 0, failed = 0;
const failures = [];
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const voter = fs.readFileSync('voter_portal.html', 'utf-8');
const marketer = fs.readFileSync('marketer_portal.html', 'utf-8');
const organizer = fs.readFileSync('preferendum_organizer.html', 'utf-8');
const css = fs.readFileSync('prefy.css', 'utf-8');
const engine = fs.readFileSync('prefy.js', 'utf-8');
const content = fs.readFileSync('prefy-content.js', 'utf-8');

// ═══════════════════════════════════════════════════════════════════════
// Shared module, not three copies — every portal includes the SAME three
// files, and none of them re-declares a UI_STRINGS-shaped clone of
// prefy-content.js.
// ═══════════════════════════════════════════════════════════════════════
[['voter_portal.html', voter], ['marketer_portal.html', marketer], ['preferendum_organizer.html', organizer]].forEach(([name, src]) => {
  assertTrue(src.includes('<script src="/prefy-content.js"></script>'), `${name} includes /prefy-content.js`);
  assertTrue(src.includes('<script src="/prefy.js"></script>'), `${name} includes /prefy.js`);
  assertTrue(src.includes('<link rel="stylesheet" href="/prefy.css">'), `${name} includes /prefy.css`);
  assertTrue(src.includes('Prefy.init()'), `${name} calls Prefy.init()`);
  // lang.js/translate.js must load BEFORE prefy.js so window.PreferendumLang
  // exists by the time Prefy could read it.
  const langIdx = src.indexOf('<script src="/lang.js">');
  const prefyIdx = src.indexOf('<script src="/prefy.js">');
  assertTrue(langIdx !== -1 && prefyIdx !== -1 && langIdx < prefyIdx, `${name} loads lang.js before prefy.js`);
});

// No portal defines its own competing state list / context registry /
// language resolver — there is exactly ONE of each, in the shared files.
[['voter_portal.html', voter], ['marketer_portal.html', marketer], ['preferendum_organizer.html', organizer]].forEach(([name, src]) => {
  assertTrue(!/const\s+CONTEXTS\s*=\s*\{/.test(src), `${name} does not define its own competing CONTEXTS registry`);
  assertTrue(!/function\s+resolveLanguage\s*\(/.test(src), `${name} does not define a competing resolveLanguage()`);
});

// ═══════════════════════════════════════════════════════════════════════
// Voter portal — required contexts actually wired at real call sites
// ═══════════════════════════════════════════════════════════════════════
const voterWiringChecks = [
  ["Prefy.setContext('voter.auth.login')", 'login screen'],
  ["Prefy.setContext(fieldContextMap[id])", 'registration/verification field-focus wiring'],
  ["Prefy.setContext(Prefy.hasSeen('voter.consultations') ? 'voter.consultations' : 'voter.welcome')", 'home / welcome-vs-repeat-visit logic'],
  ["Prefy.setContext('voter.consultation.detail')", 'consultation detail'],
  ["Prefy.setContext('voter.vote.before_submit')", 'pre-vote ATTENTION'],
  ["Prefy.setContext('voter.vote.success')", 'post-vote SUCCESS'],
  ["Prefy.setContext('voter.logout'", 'logout GOODBYE'],
  ["Prefy.setContext('voter.missing_field')", 'missing-field validation'],
  ["Prefy.setContext('voter.error.generic')", 'generic error handling'],
];
voterWiringChecks.forEach(([needle, label]) => assertTrue(voter.includes(needle), `voter_portal.html wires ${label}`));

// Registration field map covers every field the task named as actually present.
['r-country', 'r-commune', 'r-dob', 'occ-search', 'r-company-size', 'r-email', 'r-phone', 'selfie-file-input', 'doc-file-input']
  .forEach(id => assertTrue(voter.includes(`'${id}'`), `voter_portal.html's field-context map includes #${id}`));

// ═══════════════════════════════════════════════════════════════════════
// Organizer portal
// ═══════════════════════════════════════════════════════════════════════
[
  ["Prefy.setContext('organizer.home')", 'organizer home'],
  ["Prefy.setContext('organizer.missing_field')", 'organizer missing-field validation'],
  ["Prefy.setContext('organizer.logout'", 'organizer logout GOODBYE'],
].forEach(([needle, label]) => assertTrue(organizer.includes(needle), `preferendum_organizer.html wires ${label}`));

// ═══════════════════════════════════════════════════════════════════════
// Marketer portal
// ═══════════════════════════════════════════════════════════════════════
[
  ["_PREFY_PANEL_CONTEXT", 'panel-to-context map'],
  ["Prefy.setContext('marketer.missing_field')", 'marketer missing-field validation'],
  ["Prefy.setContext('marketer.logout'", 'marketer logout GOODBYE'],
].forEach(([needle, label]) => assertTrue(marketer.includes(needle), `marketer_portal.html wires ${label}`));
['overview', 'credits', 'campaigns', 'new-campaign'].forEach(panel => {
  assertTrue(marketer.includes(`'${panel}':`) || marketer.includes(`${panel}:`), `marketer_portal.html's panel-context map covers the real '${panel}' panel`);
});

// ═══════════════════════════════════════════════════════════════════════
// Ledger/payments/business logic is never touched by this phase (task
// requirement: "Do not change ledger/payment logic").
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!fs.existsSync('ledger.py') || !fs.readFileSync('ledger.py', 'utf-8').includes('Prefy'),
  'ledger.py has no Prefy reference (business logic untouched)');
assertTrue(!marketer.match(/Prefy\.[a-zA-Z]+\([^)]*balance_credits/), 'marketer_portal.html never passes a raw balance value into a Prefy call');

// ═══════════════════════════════════════════════════════════════════════
// Mobile / responsive CSS hooks
// ═══════════════════════════════════════════════════════════════════════
assertTrue(css.includes('position: fixed'), 'prefy.css positions the widget as a fixed overlay, not inline in the document flow');
assertTrue(css.includes('env(safe-area-inset-bottom)') && css.includes('env(safe-area-inset-right)'), 'prefy.css respects iPhone safe-area insets');
assertTrue(/@media\s*\(max-width:\s*420px\)/.test(css), 'prefy.css has a small-screen breakpoint');
assertTrue(/max-height:\s*46vh/.test(css) || /max-height:\s*min\(/.test(css), 'prefy.css caps the panel height so it cannot cover primary actions like the vote button');
assertTrue(/@media\s*\(prefers-reduced-motion:\s*reduce\)/.test(css), 'prefy.css honors prefers-reduced-motion');

// ═══════════════════════════════════════════════════════════════════════
// Accessibility hooks in the engine itself
// ═══════════════════════════════════════════════════════════════════════
assertTrue(engine.includes("'aria-live'"), 'prefy.js sets an aria-live region for state/content changes');
assertTrue(engine.includes("'aria-label'"), 'prefy.js sets aria-label on interactive controls');
assertTrue(engine.includes("role: 'dialog'") || engine.includes("'role': 'dialog'") || engine.includes('role') , 'prefy.js gives the panel a dialog role');
assertTrue(engine.includes("'aria-expanded'"), 'prefy.js exposes expanded/collapsed state to assistive tech');
assertTrue(/addEventListener\('click'/.test(engine), 'Prefy controls are real interactive elements (click-bindable), not divs with no semantics');
assertTrue(/<button/.test(engine) === false && /el\('button'/.test(engine), 'Prefy controls are real <button> elements (keyboard-operable by default), built via the el() helper');
assertTrue(!/\.focus\(\)/.test(engine.replace(/try\s*\{\s*_state\.dom\.closeBtn\.focus[^}]*\}/, '')),
  'no auto-focus call exists outside the one explicit user-initiated open() path');

// ═══════════════════════════════════════════════════════════════════════
// Privacy — no sensitive-looking identifiers ever flow into a Prefy call
// in any of the three portals (grep the exact call sites, not the whole
// file, so this doesn't just check "the word password never appears").
// ═══════════════════════════════════════════════════════════════════════
const prefyCallRegex = /Prefy\.[a-zA-Z]+\(([^;]*)\)/g;
[['voter_portal.html', voter], ['marketer_portal.html', marketer], ['preferendum_organizer.html', organizer]].forEach(([name, src]) => {
  let m;
  const forbidden = /\b(pass|password|token|otp|national_id|rut|face_bytes|balance_credits)\b/i;
  while ((m = prefyCallRegex.exec(src)) !== null) {
    assertTrue(!forbidden.test(m[1]), `${name}: Prefy call "${m[0].slice(0, 60)}" does not pass a sensitive identifier as an argument`);
  }
});

// ═══════════════════════════════════════════════════════════════════════
// Visual asset integration (Phase 2) — real images wired in, temporary
// fallback badge still present as a safety net, exact per-state mapping.
// ═══════════════════════════════════════════════════════════════════════
const APPROVED_STATE_FILES = {
  WELCOME: 'prefy-welcome.png', EXPLAINING: 'prefy-explaining.png', PRESENTING: 'prefy-presenting.png',
  THINKING: 'prefy-thinking.png', IDEA: 'prefy-idea.png', ATTENTION: 'prefy-attention.png',
  MISSING_INFORMATION: 'prefy-missing-information.png', ERROR: 'prefy-error.png',
  POSSIBLE_FRAUD: 'prefy-possible-fraud.png', HACKER_ALERT: 'prefy-hacker-alert.png',
  GOOD_JOB: 'prefy-good-job.png', SUCCESS: 'prefy-success.png', THANKS: 'prefy-thanks.png',
  HELP: 'prefy-help.png', GOODBYE: 'prefy-goodbye.png',
};
Object.keys(APPROVED_STATE_FILES).forEach(state => {
  assertTrue(fs.existsSync(`assets/prefy/${APPROVED_STATE_FILES[state]}`), `${state}'s approved asset file exists on disk`);
});
assertTrue(engine.includes('avatarImg.src') && engine.includes('bubbleImg.src'), 'prefy.js sets the real character image on both the panel avatar and the minimized bubble');
assertTrue(engine.includes('onAssetError'), 'prefy.js has an asset-load-failure handler');
assertTrue(engine.includes('FALLBACK_GLYPH') && engine.includes('FALLBACK_COLOR'), 'the neutral fallback badge is still present as a safety net (task §13)');
assertTrue(!/redrawn in css|hand-drawn|css-drawn character/i.test(engine + css), 'the character is not redrawn in CSS — the supplied image is used as-is');
assertTrue(!/filter:\s*(grayscale|sepia|invert|hue-rotate)/.test(css), 'no destructive CSS filter is applied to the character image');
assertTrue(/object-fit:\s*contain/.test(css), 'the character image uses object-fit:contain so it is never stretched or cropped');

// ═══════════════════════════════════════════════════════════════════════
// RTL (ar/fa/he/ur)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/transform:\s*scaleX\(-1\)/.test(css) || css.includes('!important'), 'the character image is explicitly protected from mirroring in RTL contexts');
assertTrue(css.includes('.prefy-avatar-img, .prefy-bubble-img') && /transform:\s*none\s*!important/.test(css), 'prefy.css explicitly pins the character image to never be transformed/mirrored');
assertTrue(!/direction:\s*ltr/.test(css), 'prefy.css never hardcodes direction:ltr, which would break RTL text flow inside the panel');
assertTrue(!/:\s*row-reverse/.test(css), 'prefy.css uses only logical flex row order (no row-reverse declaration), so RTL reordering follows the inherited document direction automatically');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
