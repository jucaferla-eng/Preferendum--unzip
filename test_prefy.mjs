// test_prefy.mjs — Prefy contextual guide (Phase 1). Node-based unit tests
// for prefy-content.js (pure data/lookups) and prefy.js's pure core
// (guardState, nextUIState, shouldAutoOpen) — the same split lang.js uses,
// tested the same way. Run with: node test_prefy.mjs
// Exits 0 on all-pass, 1 on any failure (mutation-testing friendly).

import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const Content = require('./prefy-content.js');
const Prefy = require('./prefy.js');

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

// ═══════════════════════════════════════════════════════════════════════
// 1. All 15 states registered
// ═══════════════════════════════════════════════════════════════════════
const EXPECTED_STATES = [
  'WELCOME', 'EXPLAINING', 'PRESENTING', 'THINKING', 'IDEA', 'ATTENTION',
  'MISSING_INFORMATION', 'ERROR', 'POSSIBLE_FRAUD', 'HACKER_ALERT',
  'GOOD_JOB', 'SUCCESS', 'THANKS', 'HELP', 'GOODBYE',
];
assertEqual(Content.STATES.length, 15, 'exactly 15 canonical states');
EXPECTED_STATES.forEach(s => assertTrue(Content.STATES.indexOf(s) !== -1, `state ${s} is registered`));
EXPECTED_STATES.forEach(s => assertTrue(!!Content.ASSETS[s], `state ${s} has a documented asset entry`));
EXPECTED_STATES.forEach(s => {
  assertTrue(typeof Content.ASSETS[s].width === 'number' && Content.ASSETS[s].width > 0, `state ${s} asset has a documented width`);
  assertTrue(typeof Content.ASSETS[s].height === 'number' && Content.ASSETS[s].height > 0, `state ${s} asset has a documented height`);
  assertTrue(/^\/assets\/prefy\/prefy-[a-z-]+\.png$/.test(Content.ASSETS[s].png), `state ${s} asset filename follows the documented convention`);
});

// Every one of the 15 states maps to its OWN distinct approved image file
// — never one image reused for two states (task requirement, Phase 2 §3).
const assetPaths = EXPECTED_STATES.map(s => Content.ASSETS[s].png);
assertEqual(new Set(assetPaths).size, 15, 'all 15 states map to distinct asset files (no file reused across states)');

// The exact state -> filename mapping the task specified.
const EXPECTED_ASSET_FILE = {
  WELCOME: 'prefy-welcome.png', EXPLAINING: 'prefy-explaining.png', PRESENTING: 'prefy-presenting.png',
  THINKING: 'prefy-thinking.png', IDEA: 'prefy-idea.png', ATTENTION: 'prefy-attention.png',
  MISSING_INFORMATION: 'prefy-missing-information.png', ERROR: 'prefy-error.png',
  POSSIBLE_FRAUD: 'prefy-possible-fraud.png', HACKER_ALERT: 'prefy-hacker-alert.png',
  GOOD_JOB: 'prefy-good-job.png', SUCCESS: 'prefy-success.png', THANKS: 'prefy-thanks.png',
  HELP: 'prefy-help.png', GOODBYE: 'prefy-goodbye.png',
};
EXPECTED_STATES.forEach(s => {
  assertEqual(Content.ASSETS[s].png, '/assets/prefy/' + EXPECTED_ASSET_FILE[s], `${s} maps to the exact approved filename ${EXPECTED_ASSET_FILE[s]}`);
});

// All 15 approved image files actually exist on disk and are non-empty.
EXPECTED_STATES.forEach(s => {
  const diskPath = 'assets/prefy/' + EXPECTED_ASSET_FILE[s];
  assertTrue(fs.existsSync(diskPath), `${diskPath} exists on disk`);
  if (fs.existsSync(diskPath)) {
    assertTrue(fs.statSync(diskPath).size > 1000, `${diskPath} is a real, non-empty image file`);
  }
});

// ═══════════════════════════════════════════════════════════════════════
// 2. Unknown state / unknown context safe fallback
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Content.isValidState('NOT_A_REAL_STATE'), false, 'bogus state is invalid');
assertEqual(Content.getContext('nonexistent.key'), null, 'unregistered context key returns null via getContext');
const unknownRendered = Content.render('nonexistent.key', 'es');
assertEqual(unknownRendered.key, '_unknown', 'render() falls back to the _unknown context key');
assertEqual(unknownRendered.state, 'HELP', 'unknown context renders a safe HELP state, never a security state');
assertTrue(unknownRendered.title.length > 0 && unknownRendered.body.length > 0, 'unknown context still has non-empty title/body');

const guardUnknown = Prefy.guardState('NOT_A_REAL_STATE', 'PRESENTING', {});
assertEqual(guardUnknown.state, Content.DEFAULT_STATE, 'guardState falls back to DEFAULT_STATE for a bogus state name');
assertTrue(guardUnknown.suppressed, 'a bogus state is reported as suppressed');

// ═══════════════════════════════════════════════════════════════════════
// 3. Context registry completeness — every entry's state is valid, every
//    titleKey/bodyKey (and whyKey, if present) resolves to REAL text in
//    BOTH fully-authored languages (es/en), never falling through to the
//    raw key itself (which would mean a typo/missing string).
// ═══════════════════════════════════════════════════════════════════════
const allKeys = Content.listContextKeys();
assertTrue(allKeys.length >= 30, `context registry has a substantial number of entries (got ${allKeys.length})`);
allKeys.forEach(key => {
  const ctx = Content.getContext(key);
  assertTrue(Content.isValidState(ctx.state), `context ${key} has a valid state (${ctx.state})`);
  assertTrue(!Content.isSecurityState(ctx.state), `context ${key} is NOT registered under a security state`);
  ['es', 'en'].forEach(lang => {
    const title = Content.str(lang, ctx.titleKey);
    const body = Content.str(lang, ctx.bodyKey);
    assertTrue(title !== ctx.titleKey, `context ${key} titleKey resolves to real text in ${lang}`);
    assertTrue(body !== ctx.bodyKey, `context ${key} bodyKey resolves to real text in ${lang}`);
    if (ctx.whyKey) {
      const why = Content.str(lang, ctx.whyKey);
      assertTrue(why !== ctx.whyKey, `context ${key} whyKey resolves to real text in ${lang}`);
    }
  });
});

// No context anywhere in the registry is allowed to use a security state —
// this is the structural half of guarantee "S" (the runtime guard in
// guardState is the other half, tested below).
assertTrue(allKeys.every(k => !Content.isSecurityState(Content.getContext(k).state)),
  'NO context in the registry is wired to POSSIBLE_FRAUD or HACKER_ALERT');

// ═══════════════════════════════════════════════════════════════════════
// 4. Minimize / reopen — pure reducer
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Prefy.nextUIState('open', 'minimize'), 'minimized', 'minimize from open -> minimized');
assertEqual(Prefy.nextUIState('minimized', 'open'), 'open', 'open from minimized -> open');
assertEqual(Prefy.nextUIState('open', 'toggle'), 'minimized', 'toggle from open -> minimized');
assertEqual(Prefy.nextUIState('minimized', 'toggle'), 'open', 'toggle from minimized -> open');
assertEqual(Prefy.nextUIState('open', 'unknown-action'), 'open', 'unrecognized action is a no-op');

// ═══════════════════════════════════════════════════════════════════════
// 5. First-visit behavior
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Prefy.shouldAutoOpen({ firstVisitAutoOpen: true }, false), true, 'auto-opens on first visit when registry says so');
assertEqual(Prefy.shouldAutoOpen({ firstVisitAutoOpen: true }, true), false, 'does NOT auto-open once already seen — avoids repeating itself');
assertEqual(Prefy.shouldAutoOpen({ firstVisitAutoOpen: false }, false), false, 'does not auto-open a context the registry marked as not-auto-open');
assertEqual(Prefy.shouldAutoOpen(null, false), false, 'a missing context entry never auto-opens');

// ═══════════════════════════════════════════════════════════════════════
// 6. Persistence key naming — pref_* convention, no sensitive data in the
//    key names themselves (values are booleans/flags only — see the
//    browser-integration tests in test_voter_portal_prefy.mjs-equivalent
//    section below for the "no sensitive VALUE stored" guarantee).
// ═══════════════════════════════════════════════════════════════════════
assertTrue(Prefy.STORAGE_KEY_MINIMIZED.indexOf('pref_prefy_') === 0, 'minimized-state key follows the pref_* convention');
assertTrue(Prefy.storageKeySeen('voter.welcome').indexOf('pref_prefy_seen_') === 0, 'seen-context key follows the pref_prefy_seen_ convention');
assertEqual(Prefy.storageKeySeen('voter.welcome'), Prefy.storageKeySeen('voter.welcome'), 'seen-key derivation is deterministic per context key');
assertTrue(Prefy.storageKeySeen('voter.welcome') !== Prefy.storageKeySeen('voter.profile'), 'different contexts get different seen-keys (no cross-context leakage)');

// ═══════════════════════════════════════════════════════════════════════
// 7. SECURITY — ordinary Phase 1 events can NEVER reach POSSIBLE_FRAUD or
//    HACKER_ALERT. This is the test the task explicitly required.
// ═══════════════════════════════════════════════════════════════════════
['POSSIBLE_FRAUD', 'HACKER_ALERT'].forEach(secState => {
  // No caller in this codebase ever has a real unlock token — simulate
  // every combination of "ordinary caller behavior" and confirm all of
  // them are refused.
  const noOptsResult = Prefy.guardState(secState, 'PRESENTING', {});
  assertTrue(noOptsResult.suppressed, `${secState} with no opts at all is suppressed`);
  assertEqual(noOptsResult.state, 'PRESENTING', `${secState} suppressed -> stays on the previously-active state`);

  const nullTokenResult = Prefy.guardState(secState, 'PRESENTING', { securityUnlockToken: null });
  assertTrue(nullTokenResult.suppressed, `${secState} with an explicit null token is suppressed`);

  const guessedTokenResult = Prefy.guardState(secState, 'PRESENTING', { securityUnlockToken: 'guessed-token' });
  assertTrue(guessedTokenResult.suppressed, `${secState} with a guessed/made-up token is suppressed`);

  const emptyStringResult = Prefy.guardState(secState, 'PRESENTING', { securityUnlockToken: '' });
  assertTrue(emptyStringResult.suppressed, `${secState} with an empty-string token is suppressed`);

  // Falls back to DEFAULT_STATE when there was no prior state either.
  const noPriorState = Prefy.guardState(secState, null, {});
  assertEqual(noPriorState.state, Content.DEFAULT_STATE, `${secState} with no prior state falls back to DEFAULT_STATE (${Content.DEFAULT_STATE})`);
});

// Ordinary auth failure -> ERROR, never a security state. This mirrors
// EXACTLY what voter_portal.html's doLogin()/doRegister() do: on any
// non-2xx response they call Prefy.setContext('voter.error.generic'),
// never setState with a security state.
const ordinaryAuthFailureCtx = Content.getContext('voter.error.generic');
assertEqual(ordinaryAuthFailureCtx.state, 'ERROR', 'the context real login/registration failures use is ERROR');
assertTrue(!Content.isSecurityState(ordinaryAuthFailureCtx.state), 'ERROR is not a security state — a single wrong password cannot trigger POSSIBLE_FRAUD/HACKER_ALERT');

// Selfie/document mismatch contexts are EXPLAINING (informational), never
// wired to a security state anywhere in the registry.
['voter.verify.selfie', 'voter.verify.document'].forEach(key => {
  const ctx = Content.getContext(key);
  assertTrue(!Content.isSecurityState(ctx.state), `${key} is not a security state — a single selfie/document mismatch cannot trigger POSSIBLE_FRAUD`);
});

// A 429 (rate limit) is never in the registry and the guard refuses it by
// construction even if some future caller mistakenly tried:
const rateLimitAttempt = Prefy.guardState('HACKER_ALERT', 'ERROR', {});
assertTrue(rateLimitAttempt.suppressed, 'an ordinary 429-style event cannot flip Prefy into HACKER_ALERT in Phase 1');

// ═══════════════════════════════════════════════════════════════════════
// 8. Registration explanations — accuracy spot-checks (each references
//    ONLY what CHANGE-002/003 actually implement; no invented business
//    rule, no exact number/coefficient exposed).
// ═══════════════════════════════════════════════════════════════════════
const occ = Content.render('voter.register.occupation', 'en');
assertTrue(/occupation/i.test(occ.title), 'occupation context title mentions occupation');
assertTrue(/income/i.test(occ.body), 'occupation explanation mentions its real role in income estimation');
assertTrue(/targeting|criterion/i.test(occ.body), 'occupation explanation mentions its real role as a targeting criterion');
assertTrue(/never show|never share/i.test(occ.why), 'occupation explanation states it is not shared with other users');

const companySize = Content.render('voter.register.company_size', 'en');
assertTrue(/income/i.test(companySize.body), 'company size explanation mentions income estimation');
assertTrue(/not every|not all/i.test(companySize.body.toLowerCase()) || /where implemented/i.test(companySize.body), 'company size explanation does not overclaim universal use');

const selfie = Content.render('voter.verify.selfie', 'en');
assertTrue(/never receives|never (see|store)s?/i.test(selfie.body), 'selfie explanation explicitly denies Prefy access to facial data');

const doc = Content.render('voter.verify.document', 'en');
assertTrue(/never reads|never displays|never shows/i.test(doc.body), 'document explanation explicitly denies Prefy reading/showing document values');

// ═══════════════════════════════════════════════════════════════════════
// 9. Consultation / matching explanation
// ═══════════════════════════════════════════════════════════════════════
const consultations = Content.render('voter.consultations', 'en');
assertTrue(/eligible/i.test(consultations.body), 'consultation list explanation mentions eligibility');
assertTrue(/not every/i.test(consultations.body), 'consultation list explanation avoids claiming every consultation uses the same criteria');

// ═══════════════════════════════════════════════════════════════════════
// 10. Voting ATTENTION / SUCCESS-THANKS
// ═══════════════════════════════════════════════════════════════════════
const beforeVote = Content.render('voter.vote.before_submit', 'en');
assertEqual(beforeVote.state, 'ATTENTION', 'pre-submit vote context uses ATTENTION');
assertTrue(!/option [a-z0-9]/i.test(beforeVote.body), 'pre-submit copy never echoes back a specific selected option');

const voteSuccess = Content.render('voter.vote.success', 'en');
assertEqual(voteSuccess.state, 'SUCCESS', 'post-vote context uses SUCCESS');

// ═══════════════════════════════════════════════════════════════════════
// 11. Missing-field / general error states
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Content.getContext('voter.missing_field').state, 'MISSING_INFORMATION', 'voter missing-field context uses MISSING_INFORMATION');
assertEqual(Content.getContext('organizer.missing_field').state, 'MISSING_INFORMATION', 'organizer missing-field context uses MISSING_INFORMATION');
assertEqual(Content.getContext('marketer.missing_field').state, 'MISSING_INFORMATION', 'marketer missing-field context uses MISSING_INFORMATION');
assertEqual(Content.getContext('voter.error.generic').state, 'ERROR', 'voter generic error context uses ERROR');

// ═══════════════════════════════════════════════════════════════════════
// 12. DEMO/REAL marketer explanation — never claims conversion is possible
// ═══════════════════════════════════════════════════════════════════════
const credits = Content.render('marketer.panel.credits', 'en');
assertTrue(/DEMO/.test(credits.body) && /REAL/.test(credits.body), 'credits explanation names both REAL and DEMO');
assertTrue(/never.*(used as|converted)/i.test(credits.body) || /can never/i.test(credits.body), 'credits explanation states DEMO can never become REAL money');
assertTrue(!/\$[\d,]+/.test(credits.body), 'credits explanation never hardcodes/reveals a specific balance figure');

// ═══════════════════════════════════════════════════════════════════════
// 13. Organizer / marketer surface coverage (structural — every surface
//     this phase targets has at least a home/entry, a create/action, and
//     a logout context, matching the shared architecture requirement).
// ═══════════════════════════════════════════════════════════════════════
['organizer', 'marketer'].forEach(surface => {
  const keys = allKeys.filter(k => Content.getContext(k).surface === surface);
  assertTrue(keys.length >= 3, `${surface} surface has at least 3 registered contexts (got ${keys.length})`);
  assertTrue(keys.some(k => Content.getContext(k).state === 'GOODBYE'), `${surface} surface has a GOODBYE context`);
});
const voterKeys = allKeys.filter(k => Content.getContext(k).surface === 'voter');
assertTrue(voterKeys.length >= 15, `voter surface has thorough coverage (got ${voterKeys.length} contexts)`);

// ═══════════════════════════════════════════════════════════════════════
// 14. LANGUAGE EXPANSION — Prefy now has controlled copy in the full 30
//      canonical Preferendum languages (not just es/en). Prove: exactly
//      30, every one complete (no missing/blank/raw-key value for any of
//      the 81 keys), and a genuinely unsupported code still falls back
//      safely to Spanish rather than to a blank bubble.
// ═══════════════════════════════════════════════════════════════════════
const CANONICAL_30 = [
  'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
  'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
  'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
];
assertEqual(CANONICAL_30.length, 30, 'the canonical language list itself has exactly 30 entries');
assertEqual(Object.keys(Content.STRINGS).sort(), CANONICAL_30.slice().sort(), 'Prefy STRINGS has exactly the 30 canonical languages — no more, no fewer');

const esKeys = Object.keys(Content.STRINGS.es).sort();
CANONICAL_30.forEach(lang => {
  const keys = Object.keys(Content.STRINGS[lang]).sort();
  assertEqual(keys, esKeys, `${lang} has exactly the same 81 string keys as es (no missing/extra key)`);
  esKeys.forEach(key => {
    const value = Content.STRINGS[lang][key];
    assertTrue(typeof value === 'string' && value.length > 0, `${lang}.${key} is a non-empty string`);
    assertTrue(value !== key, `${lang}.${key} is real text, not the raw key itself`);
  });
});

// No two languages are byte-identical copy-paste placeholders — each is
// genuinely its own translation (spot-check a content-bearing key).
const distinctWelcomeBodies = new Set(CANONICAL_30.map(l => Content.STRINGS[l]['ctx.voter.welcome.title']));
assertEqual(distinctWelcomeBodies.size, 30, 'all 30 languages have a genuinely distinct welcome title (no copy-paste duplicate)');

// A code OUTSIDE the canonical 30 still falls back to Spanish, never a
// blank bubble or the raw key.
const notReallyASupportedLang = 'xx';
const fallbackRendered = Content.render('voter.welcome', notReallyASupportedLang);
assertEqual(fallbackRendered.title, Content.str('es', 'ctx.voter.welcome.title'), 'a code outside the canonical 30 falls back to Spanish, never a blank string');
['zz', 'qq', ''].forEach(bogus => {
  assertEqual(Content.str(bogus, 'ctx.voter.welcome.title'), Content.str('es', 'ctx.voter.welcome.title'), `bogus code '${bogus}' falls back to Spanish`);
});

// ═══════════════════════════════════════════════════════════════════════
// 15. Prefy uses ONLY the canonical Preferendum language resolver — no
//     competing detector. Structural: prefy.js's source never reads
//     navigator.language and never defines its own country->language
//     table; it only ever calls window.PreferendumLang.currentLanguage().
// ═══════════════════════════════════════════════════════════════════════
const prefyEngineSrc = fs.readFileSync('prefy.js', 'utf-8');
assertTrue(!/navigator\.language/.test(prefyEngineSrc), 'prefy.js never reads navigator.language directly');
assertTrue(!/COUNTRY_DEFAULT_LANGUAGE|resolveLanguage\s*\(/.test(prefyEngineSrc), 'prefy.js defines no competing country table or resolver function');
assertTrue(/window\.PreferendumLang\s*&&/.test(prefyEngineSrc) && /\.currentLanguage\s*\(\s*\)/.test(prefyEngineSrc), 'prefy.js reads the language exclusively via window.PreferendumLang.currentLanguage()');
assertTrue(!/setCountry/.test(prefyEngineSrc), 'prefy.js never calls PreferendumLang.setCountry — that stays business logic\'s responsibility, not Prefy\'s');

// ═══════════════════════════════════════════════════════════════════════
// 16. RTL languages — ar/fa/he/ur. Structural (the character image must
//     never be mirrored; the panel's text handling is exercised via the
//     canonical lang.js resolver, which already sets document dir= for
//     the whole page — see test_lang_resolver.mjs's RTL assertions).
// ═══════════════════════════════════════════════════════════════════════
const RTL_LANGS = ['ar', 'fa', 'he', 'ur'];
RTL_LANGS.forEach(lang => {
  const rendered = Content.render('voter.welcome', lang);
  assertTrue(rendered.title.length > 0 && rendered.body.length > 0, `RTL language ${lang} renders real, non-empty content`);
});
assertTrue(!/transform:\s*scaleX\(-1\)/.test(fs.readFileSync('prefy.css', 'utf-8')), 'prefy.css never mirrors the character image for RTL');

// ═══════════════════════════════════════════════════════════════════════
// Summary
// ═══════════════════════════════════════════════════════════════════════
console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
