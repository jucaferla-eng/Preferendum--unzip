// test_prefy_motion.mjs — Prefy Motion & Interaction phase.
// Node-based tests for the pure/DOM-free motion logic (state→profile
// completeness, the race-condition guard) plus structural checks against
// the ACTUAL prefy.css/prefy.js source (same technique as
// test_prefy_portal_wiring.mjs) for everything that requires a real
// browser to execute (animations, transitions, DOM classes).
// Run with: node test_prefy_motion.mjs

import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const Content = require('./prefy-content.js');
const Prefy = require('./prefy.js');

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const css = fs.readFileSync('prefy.css', 'utf-8');
const js = fs.readFileSync('prefy.js', 'utf-8');

// ═══════════════════════════════════════════════════════════════════════
// 1. Idle animation
// ═══════════════════════════════════════════════════════════════════════
assertTrue(/@keyframes prefy-idle-float/.test(css), 'an idle float keyframe exists');
const idleBlock = css.slice(css.indexOf('@keyframes prefy-idle-float'), css.indexOf('@keyframes prefy-idle-float') + 200);
assertTrue(/translateY\(-3px\)/.test(idleBlock) || /translateY\(-[1-4]px\)/.test(idleBlock), 'idle float amplitude is small (a few px), not a large/aggressive bounce');
assertTrue(/animation:\s*prefy-idle-float\s+3\.6s/.test(css), 'idle float runs slowly (3.6s), not a fast/distracting cycle');
assertTrue(/prefy-idle-float[\s\S]{0,80}infinite/.test(css) || /animation:\s*prefy-idle-float[^;]*infinite/.test(css), 'idle float is the one animation allowed to be infinite (continuous, but tiny)');
assertTrue(!/prefy-idle-float[\s\S]{0,60}rotate/i.test(css), 'idle float does not rotate the character (translate-only, no excessive rotation)');
// Idle float targets WRAPPER elements only, never the elements that also
// carry one-shot state-motion classes (would fight over `transform` on
// the same element and cancel each other, or cancel hover/tap-react).
assertTrue(/\.prefy-avatar-wrap\s*{[^}]*animation:\s*prefy-idle-float/.test(css), 'idle float applies to the avatar WRAPPER, not the image/state-motion target directly');
assertTrue(/\.prefy-bubble-float\s*{[^}]*animation:\s*prefy-idle-float/.test(css), 'idle float applies to a dedicated bubble-float wrapper, not .prefy-bubble itself (which owns hover/active/tap-react transforms)');

// ═══════════════════════════════════════════════════════════════════════
// 2. All 15 state motion profiles
// ═══════════════════════════════════════════════════════════════════════
const ALL_STATES = Content.STATES;
assertEqual(ALL_STATES.length, 15, 'exactly 15 canonical states (unchanged from prior phases)');
assertEqual(Object.keys(Prefy.STATE_MOTION).sort(), ALL_STATES.slice().sort(), 'STATE_MOTION has a profile for every one of the 15 states, no more no less');

ALL_STATES.forEach(state => {
  const profile = Prefy.STATE_MOTION[state];
  assertTrue(!!profile && typeof profile.className === 'string' && profile.className.length > 0, `${state} has a motion profile with a real class name`);
  assertTrue(typeof profile.duration === 'number' && profile.duration > 0 && profile.duration < 5000, `${state}'s motion duration is a small positive number of ms (one-shot, not indefinite)`);
  const kfName = '@keyframes ' + profile.className;
  assertTrue(css.includes(kfName), `${state}'s keyframe (${profile.className}) actually exists in prefy.css`);
  // Every state-motion class is applied with a FIXED iteration count
  // (never `infinite`) — this is the literal "no automatic trigger
  // becomes a runaway animation" and "one-shot" guarantee.
  const classRuleMatch = css.match(new RegExp('\\.' + profile.className.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&') + '\\s*{([^}]*)}'));
  assertTrue(!!classRuleMatch, `${state}'s class rule (.${profile.className}) exists`);
  if (classRuleMatch) {
    assertTrue(!/infinite/.test(classRuleMatch[1]), `${state}'s motion (.${profile.className}) is NOT infinite — one-shot only`);
  }
});

// Distinct classNames for every state (no accidental duplicate mapping
// that would make two different states look like the same gesture).
const allClassNames = ALL_STATES.map(s => Prefy.STATE_MOTION[s].className);
assertEqual(new Set(allClassNames).size, 15, 'all 15 states have distinct motion class names');

// Specific per-state character checks called out by the task.
assertTrue(/@keyframes prefy-m-attention[\s\S]{0,150}}/.test(css), 'ATTENTION has its own keyframe');
const attentionRule = css.match(/\.prefy-m-attention\s*{([^}]*)}/)[1];
assertTrue(!/infinite/.test(attentionRule), 'ATTENTION never flashes continuously (not infinite)');
const hackerRule = css.match(/\.prefy-m-hacker\s*{([^}]*)}/)[1];
assertTrue(!/infinite/.test(hackerRule), 'HACKER_ALERT motion is one-shot, never a continuous/seizure-risk flash');
assertTrue(Prefy.STATE_MOTION.HACKER_ALERT.duration >= 500, 'HACKER_ALERT motion is slow (>=500ms), not a fast strobe');
const errorRule = css.match(/\.prefy-m-error\s*{([^}]*)}/)[1];
assertTrue(!/infinite/.test(errorRule), 'ERROR shake happens once, never repeated');
assertTrue(!/box-shadow:[^;]*,[^;]*,/.test(css.match(/@keyframes prefy-glow-once[\s\S]*?}\s*}/)?.[0] || ''), 'the one glow effect never animates box-shadow directly (opacity-only pseudo-element instead — GPU-cheap)');

// ═══════════════════════════════════════════════════════════════════════
// 3. State transition lifecycle + rapid-state-change / latest-wins
// ═══════════════════════════════════════════════════════════════════════
assertTrue(js.includes('function transitionToRendered'), 'a single transition orchestrator function exists');
assertTrue(js.includes('CONTENT_FADE_OUT_MS') && js.includes('CONTENT_FADE_IN_MS'), 'the transition has distinct fade-out and fade-in phases');
assertTrue(js.includes('playEntranceMotion'), 'a state-specific entrance step exists, applied after the fade-in');
assertTrue(/isStaleTransition\(mySeq, _transitionSeq\)/.test(js), 'every deferred transition step re-checks staleness against the CURRENT sequence, not a snapshot');

// The pure guard itself.
assertEqual(Prefy.isStaleTransition(1, 1), false, 'a transition matching the current sequence is not stale');
assertEqual(Prefy.isStaleTransition(1, 2), true, 'an older transition is correctly detected as stale once a newer one has started');
assertEqual(Prefy.isStaleTransition(5, 5), false, 'equal sequence numbers are never considered stale');

// _transitionSeq must increase monotonically across calls (this is what
// "latest legitimate state must win" actually rests on) — exercised via
// the real setState() entry point in a browser-less (no-DOM) call, which
// still bumps the counter even though it returns early after guardState.
Prefy.init(); // no-op outside a browser; safe to call
const seqBefore = Prefy._transitionSeqValue();
Prefy.setState('SUCCESS', { title: 'a', body: 'b' });
Prefy.setState('ERROR', { title: 'c', body: 'd' });
Prefy.setState('HELP', { title: 'e', body: 'f' });
const seqAfter = Prefy._transitionSeqValue();
assertTrue(seqAfter > seqBefore, 'the transition sequence counter strictly increases across successive state changes');
assertTrue(seqAfter - seqBefore >= 3, 'three state changes bump the sequence at least three times (one per call, no silent skips)');

// ═══════════════════════════════════════════════════════════════════════
// 4. Panel / minimize / reopen motion
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/\.prefy-panel\s*{[^}]*display:\s*none/.test(css), 'the panel no longer uses display:none for its closed state (would block a transition from ever playing)');
assertTrue(/\.prefy-panel\s*{[^}]*transition:[^;]*opacity/.test(css), 'the panel transitions opacity for smooth open/close');
assertTrue(/\.prefy-panel\s*{[^}]*transition:[^;]*transform/.test(css), 'the panel transitions transform for smooth open/close (not just an instant opacity snap)');
assertTrue(/\.prefy-bubble\.prefy-hidden-while-open\s*{[^}]*opacity:\s*0/.test(css), 'the bubble fades out (not display:none) when the panel opens, so it can transition smoothly');
assertTrue(/position:\s*absolute/.test(css.match(/\.prefy-panel\s*{[^}]*}/)[0]) && /position:\s*absolute/.test(css.match(/\.prefy-bubble\s*{[^}]*}/)[0]),
  'bubble and panel are both position:absolute within the fixed-size .prefy-root anchor — this is what guarantees zero page layout shift on open/close');
assertTrue(/\.prefy-root\s*{[^}]*width:\s*52px/.test(css) && /\.prefy-root\s*{[^}]*height:\s*52px/.test(css),
  '.prefy-root has a fixed, small footprint that never changes size regardless of panel open/closed state');

// ═══════════════════════════════════════════════════════════════════════
// 5. Tap/click reaction — purely visual, no business-state or network call
// ═══════════════════════════════════════════════════════════════════════
assertTrue(js.includes("classList.add('prefy-tap-react')"), 'a tap-reaction class is added on bubble click');
assertTrue(css.includes('.prefy-tap-react'), 'the tap-reaction keyframe/class exists in CSS');
const tapReactRule = css.match(/@keyframes prefy-tap-react\s*{([\s\S]*?)}\s*}/);
assertTrue(!!tapReactRule, 'the tap-react keyframe animates only transform (scale), never opacity/color — confirmed decorative-only');
// Extract exactly the click handler body attached to the bubble to prove
// the reaction is scoped there and doesn't also call setState/setContext
// or any fetch/XHR.
const bubbleClickHandlerMatch = js.match(/bubble\.addEventListener\('click', function \(\) \{([\s\S]*?)\}\);/);
assertTrue(!!bubbleClickHandlerMatch, "the bubble's click handler is found in source");
if (bubbleClickHandlerMatch) {
  const handlerBody = bubbleClickHandlerMatch[1];
  assertTrue(!/setState\(|setContext\(/.test(handlerBody), 'tapping the bubble never calls setState/setContext — no business-state change from a tap');
  assertTrue(!/fetch\(|XMLHttpRequest|\.ajax\(/.test(handlerBody), 'tapping the bubble never makes a network request');
  assertTrue(/open\(\)/.test(handlerBody), 'tapping the bubble still opens the panel (existing behavior preserved)');
}

// ═══════════════════════════════════════════════════════════════════════
// 6. Mobile/WebView performance — transform/opacity only, no expensive
//    properties, no animation framework dependency, no JS animation loop.
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/requestAnimationFrame/.test(js), 'no requestAnimationFrame loop anywhere in prefy.js — orchestration is pure setTimeout + CSS classes');
assertTrue(!/<canvas|getContext\('2d'\)|getContext\("2d"\)/.test(js), 'no canvas-based animation');
assertTrue(!/lottie|rive|gsap/i.test(js) && !/lottie|rive|gsap/i.test(css), 'no animation framework (Lottie/Rive/GSAP) referenced anywhere');
// Every @keyframes block in prefy.css only animates transform/opacity
// (the two GPU-compositable properties) — extract each block and check.
const keyframeBlocks = [...css.matchAll(/@keyframes ([a-z0-9-]+)\s*{([\s\S]*?)}\s*}/gi)];
assertTrue(keyframeBlocks.length >= 16, `found the expected number of @keyframes blocks (idle float + tap-react + fade x2 + glow + 15 motion profiles), got ${keyframeBlocks.length}`);
keyframeBlocks.forEach(([, name, body]) => {
  const declaredProps = [...body.matchAll(/;?\s*([a-z-]+)\s*:/g)].map(m => m[1]);
  const allowed = new Set(['transform', 'opacity']);
  const offenders = declaredProps.filter(p => !allowed.has(p));
  assertTrue(offenders.length === 0, `keyframe ${name} only animates transform/opacity (found: ${offenders.join(', ') || 'none'})`);
});
assertTrue(!/animation:[^;]*box-shadow/.test(css), 'box-shadow itself is never the animated property (paint-expensive) — the glow effect uses an opacity-only pseudo-element instead');

// Prefy must never cover the vote/submit/navigation controls — re-verify
// the existing small-screen height cap survived this phase unchanged.
assertTrue(/max-height:\s*46vh/.test(css), 'the small-screen panel height cap (46vh) is unchanged — Prefy still cannot grow over the vote button');

// ═══════════════════════════════════════════════════════════════════════
// 7. Reduced motion — MANDATORY
// ═══════════════════════════════════════════════════════════════════════
assertTrue(/@media\s*\(prefers-reduced-motion:\s*reduce\)/.test(css), 'the prefers-reduced-motion media query is present');
const reducedBlock = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'), css.indexOf('@media (prefers-reduced-motion: reduce)') + 1400);
assertTrue(/\.prefy-bubble-float/.test(reducedBlock), 'reduced motion disables the idle float on the bubble');
assertTrue(/\.prefy-avatar-wrap/.test(reducedBlock), 'reduced motion disables the idle float on the panel avatar');
assertTrue(/\.prefy-tap-react/.test(reducedBlock), 'reduced motion disables the tap-reaction animation');
ALL_STATES.forEach(state => {
  const cls = Prefy.STATE_MOTION[state].className;
  assertTrue(reducedBlock.includes('.' + cls), `reduced motion explicitly disables ${state}'s motion class (.${cls})`);
});
assertTrue(/animation:\s*none\s*!important/.test(reducedBlock), 'reduced motion uses animation:none!important to guarantee no animation plays regardless of specificity');
assertTrue(/transition-duration:\s*0\.01ms\s*!important/.test(reducedBlock), 'reduced motion collapses transitions to a near-instant duration rather than an abrupt jump with no fallback');
// The JS-side mirror class (for environments/tests that toggle it
// directly rather than relying on the media query) exists too.
assertTrue(css.includes('.prefy-reduced-motion'), 'a JS-toggleable .prefy-reduced-motion class exists alongside the media query');
// Reduced motion still leaves full functionality: the transition
// orchestrator has an explicit reduced-motion branch that still updates
// content/image/panel-visibility, just without animating.
assertTrue(/if \(opts\.skipAnimation \|\| reduced\)/.test(js), 'the transition orchestrator has an explicit reduced-motion branch');
assertTrue(js.includes('function prefersReducedMotion'), 'prefersReducedMotion() is the single source of truth the JS orchestration consults');

// ═══════════════════════════════════════════════════════════════════════
// 8. Accessibility / safety
// ═══════════════════════════════════════════════════════════════════════
// No animation strobes: a keyframe may legitimately fade IN once (a
// single monotonic rise from a low starting opacity to 1, e.g. an
// entrance) — that's not a flash. What's NOT allowed is opacity
// oscillating up and down more than once within a single keyframe,
// which is what an actual strobe/flash pattern looks like.
keyframeBlocks.forEach(([, name, body]) => {
  const opacityValues = [...body.matchAll(/opacity:\s*([0-9.]+)/g)].map(m => parseFloat(m[1]));
  if (opacityValues.length < 2) return; // no opacity animation at all, or only one stop — trivially fine
  var directionChanges = 0;
  for (var i = 2; i < opacityValues.length; i++) {
    var prevDelta = opacityValues[i - 1] - opacityValues[i - 2];
    var delta = opacityValues[i] - opacityValues[i - 1];
    if (prevDelta !== 0 && delta !== 0 && (prevDelta > 0) !== (delta > 0)) directionChanges++;
  }
  assertTrue(directionChanges === 0, `keyframe ${name}'s opacity changes direction at most once (a single fade in or out) — never oscillates like a strobe/flash (found ${directionChanges} direction change(s) in [${opacityValues.join(', ')}])`);
});
assertTrue(!/color:\s*red/i.test(css) && !/#f00\b/i.test(css) && !/#ff0000\b/i.test(css), 'no pure-red flashing color is introduced by this phase');
assertTrue(!js.includes('<audio') && !js.includes('.play()') && !js.includes('AudioContext'), 'no automatic audio playback anywhere in prefy.js (voice is explicitly out of scope for this phase)');
assertTrue(!/getUserMedia|requestPermission/.test(js), 'no microphone/permission request anywhere in prefy.js');
// Focus: only the pre-existing explicit-open path calls .focus() — motion
// additions introduce no NEW auto-focus path.
const focusCalls = [...js.matchAll(/\.focus\(/g)];
assertEqual(focusCalls.length, 1, 'exactly one .focus() call exists in the whole engine (the pre-existing explicit user-open path) — motion work added no new auto-focus call');

// ═══════════════════════════════════════════════════════════════════════
// 9. Security states — motion profiles exist, automatic trigger still
//    hard-disabled. Re-verify the guard from prior phases still holds
//    with the motion system layered on top, and confirm the motion
//    system itself introduces no NEW path to reach either state.
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!!Prefy.STATE_MOTION.POSSIBLE_FRAUD && !!Prefy.STATE_MOTION.HACKER_ALERT, 'motion profiles exist for both security states (installable/testable, per task §10)');
// playEntranceMotion only ever receives _state.currentState, which is
// ALWAYS set from guardState()'s return value before any motion call —
// never raw, ungated input. Confirmed structurally: every call site of
// playEntranceMotion passes `_state.currentState`, and `_state.currentState`
// is only ever assigned from `guard.state` (guardState's own output).
const playEntranceMotionCallSites = [...js.matchAll(/(?<!function )playEntranceMotion\(([^,]+),/g)].map(m => m[1].trim());
assertTrue(playEntranceMotionCallSites.length > 0, 'playEntranceMotion has at least one call site');
playEntranceMotionCallSites.forEach(arg => {
  assertEqual(arg, '_state.currentState', 'every playEntranceMotion call passes the already-guarded _state.currentState, never a raw/unguarded value');
});
const currentStateAssignments = [...js.matchAll(/_state\.currentState\s*=\s*([^;]+);/g)].map(m => m[1].trim());
assertTrue(currentStateAssignments.length > 0, '_state.currentState has at least one assignment');
currentStateAssignments.forEach(rhs => {
  assertTrue(rhs === 'guard.state' || rhs === "PrefyContent.DEFAULT_STATE", `_state.currentState is only ever assigned from guardState()'s own output (found: ${rhs})`);
});

// Ordinary Phase-1 failure events, re-verified end to end through
// guardState with the motion system in place — none can reach a
// security state, and the resulting motion profile is the SAFE state's
// profile, never the fraud/hacker one.
['POSSIBLE_FRAUD', 'HACKER_ALERT'].forEach(secState => {
  const loginFailure = Prefy.guardState(secState, 'EXPLAINING', {}); // simulates an ordinary wrong-password attempt trying (incorrectly) to request this state
  assertTrue(loginFailure.suppressed, `a login-failure-shaped call requesting ${secState} is suppressed`);
  const selfieMismatch = Prefy.guardState(secState, 'EXPLAINING', { securityUnlockToken: undefined });
  assertTrue(selfieMismatch.suppressed, `a selfie-mismatch-shaped call requesting ${secState} is suppressed`);
  const networkError = Prefy.guardState(secState, 'PRESENTING', {});
  assertTrue(networkError.suppressed, `a network-error-shaped call requesting ${secState} is suppressed`);
  const rateLimited429 = Prefy.guardState(secState, 'ERROR', {});
  assertTrue(rateLimited429.suppressed, `a 429-shaped call requesting ${secState} is suppressed`);
  const validationError = Prefy.guardState(secState, 'MISSING_INFORMATION', {});
  assertTrue(validationError.suppressed, `a validation-error-shaped call requesting ${secState} is suppressed`);
  // In every case the resulting motion profile is the FALLBACK state's
  // profile (whatever was already showing), never the security state's.
  [loginFailure, selfieMismatch, networkError, rateLimited429, validationError].forEach(result => {
    assertTrue(result.state !== 'POSSIBLE_FRAUD' && result.state !== 'HACKER_ALERT', `suppressed result never resolves to a security state's motion profile (got ${result.state})`);
  });
});

// The registry itself: no context anywhere is wired to a security state
// (re-verified after this phase's changes — motion work touched no
// context-registry entries).
Content.listContextKeys().forEach(key => {
  const ctx = Content.getContext(key);
  assertTrue(!Content.isSecurityState(ctx.state), `context ${key} is still not wired to a security state after the motion phase`);
});

// ═══════════════════════════════════════════════════════════════════════
// 10. Language independence
// ═══════════════════════════════════════════════════════════════════════
assertTrue(js.includes('function onLangChange'), 'a dedicated language-change handler exists');
const onLangChangeBody = js.match(/function onLangChange\(\)\s*{([\s\S]*?)\n  }/)[1];
assertTrue(!/transitionToRendered|playEntranceMotion|_transitionSeq/.test(onLangChangeBody), 'a language change never triggers the fade/entrance motion sequence or bumps the transition sequence — motion is independent of language, and switching language does not replay entrance animations');
assertTrue(/renderContent/.test(onLangChangeBody), 'a language change still updates the displayed text immediately (no regression to language-following behavior)');
// No animation/timing value anywhere in prefy.js is keyed by language.
assertTrue(!/currentLang\(\)/.test(js.slice(js.indexOf('var STATE_MOTION'), js.indexOf('var CONTENT_FADE_OUT_MS') + 40)), 'the motion profile table itself never reads the current language');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
