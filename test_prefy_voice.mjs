// test_prefy_voice.mjs — Prefy 30-Language Voice phase.
// Node-based tests for prefy-voice.js's pure decision logic (locale
// mapping, voice selection, sensitive-data guard, THINKING no-repeat,
// the one gate every speech attempt passes through) plus structural
// checks against the ACTUAL prefy-voice.js/prefy.js source for anything
// that requires a real browser (speechSynthesis, DOM, events) — same
// technique as test_prefy_motion.mjs / test_prefy_portal_wiring.mjs.
// Run with: node test_prefy_voice.mjs

import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const Content = require('./prefy-content.js');
const Prefy = require('./prefy.js');
const Voice = require('./prefy-voice.js');
const Lang = require('./lang.js');

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const js = fs.readFileSync('prefy-voice.js', 'utf-8');
const engineJs = fs.readFileSync('prefy.js', 'utf-8');
const css = fs.readFileSync('prefy.css', 'utf-8');
const voterHtml = fs.readFileSync('voter_portal.html', 'utf-8');
const marketerHtml = fs.readFileSync('marketer_portal.html', 'utf-8');
const organizerHtml = fs.readFileSync('preferendum_organizer.html', 'utf-8');
const mainPy = fs.readFileSync('main.py', 'utf-8');

const CANONICAL_30 = Lang.SUPPORTED_LANGUAGES.slice().sort();

// ═══════════════════════════════════════════════════════════════════════
// 1. Canonical 30 language → speech locale mappings (task §2/§17)
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Object.keys(Voice.SPEECH_LOCALES).sort(), CANONICAL_30, 'SPEECH_LOCALES covers exactly the canonical 30 languages, no more, no less');
assertEqual(Voice.CANONICAL_LANGUAGES.slice().sort(), CANONICAL_30, 'CANONICAL_LANGUAGES matches lang.js.SUPPORTED_LANGUAGES exactly');
assertEqual(Object.keys(Content.STRINGS).sort(), CANONICAL_30, "Voice's language set still matches Prefy's own content languages (no drift)");
Object.keys(Voice.SPEECH_LOCALES).forEach((lang) => {
  const locale = Voice.SPEECH_LOCALES[lang];
  assertTrue(/^[a-z]{2,3}-[A-Z]{2}$/.test(locale), `${lang} maps to a well-formed BCP-47 locale (got "${locale}")`);
  assertTrue(locale.toLowerCase().startsWith(lang === 'fil' ? 'fil' : lang), `${lang}'s locale's base language matches the language code itself (${locale})`);
});
// Spot-check the task's own worked examples aren't contradicted.
assertEqual(Voice.speechLocaleFor('es'), 'es-ES', "es maps to es-ES per the task's own example");
assertEqual(Voice.speechLocaleFor('en'), 'en-US', "en maps to en-US per the task's own example");
assertEqual(Voice.speechLocaleFor('fr'), 'fr-FR', "fr maps to fr-FR per the task's own example");
assertEqual(Voice.speechLocaleFor('de'), 'de-DE', "de maps to de-DE per the task's own example");
assertEqual(Voice.speechLocaleFor('ja'), 'ja-JP', "ja maps to ja-JP per the task's own example");
assertEqual(Voice.speechLocaleFor('ko'), 'ko-KR', "ko maps to ko-KR per the task's own example");
assertEqual(Voice.speechLocaleFor('ru'), 'ru-RU', "ru maps to ru-RU per the task's own example");
assertEqual(Voice.speechLocaleFor('hi'), 'hi-IN', "hi maps to hi-IN per the task's own example");
assertTrue(['ar-SA'].includes(Voice.speechLocaleFor('ar')), "ar maps to a defensible Arabic locale");
assertTrue(['pt-BR', 'pt-PT'].includes(Voice.speechLocaleFor('pt')), "pt maps to a defensible Portuguese locale (BR or PT, per the task's own 'or defensible existing locale' allowance)");
assertTrue(['zh-CN', 'zh-TW', 'zh-HK'].includes(Voice.speechLocaleFor('zh')), 'zh maps to a defensible Chinese locale');
assertEqual(Voice.speechLocaleFor('not-a-real-lang'), null, 'an unknown language code maps to null, never a guessed locale');

// ═══════════════════════════════════════════════════════════════════════
// 2. Voice selection — exact / base-language / alias / none (task §3/§17)
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Voice.selectVoice([{ lang: 'es-ES' }, { lang: 'en-US' }], 'es'), { lang: 'es-ES' }, 'an exact locale match wins over any other candidate');
assertEqual(Voice.selectVoice([{ lang: 'es-MX' }], 'es'), { lang: 'es-MX' }, 'a base-language match is used when no exact locale is installed');
assertEqual(Voice.selectVoice([{ lang: 'ES-mx' }], 'es'), { lang: 'ES-mx' }, 'matching is case-insensitive');
assertEqual(Voice.selectVoice([{ lang: 'tl-PH' }], 'fil'), { lang: 'tl-PH' }, "fil falls back to an appropriate 'tl' (Tagalog) alias when no fil-tagged voice exists");
assertEqual(Voice.selectVoice([{ lang: 'zh-TW' }], 'zh'), { lang: 'zh-TW' }, 'zh falls back to an appropriate Chinese regional alias');
assertEqual(Voice.selectVoice([{ lang: 'iw-IL' }], 'he'), { lang: 'iw-IL' }, "he falls back to the legacy 'iw' alias some engines still emit");
assertEqual(Voice.selectVoice([{ lang: 'de-DE' }, { lang: 'fr-FR' }], 'ja'), null, 'no compatible voice installed → null, never an unrelated-language voice');
assertEqual(Voice.selectVoice([], 'es'), null, 'an empty voice list → null');
assertEqual(Voice.selectVoice(null, 'es'), null, 'a missing voice list → null, never a crash');
assertEqual(Voice.selectVoice([{ lang: 'es-ES' }], 'not-a-real-lang'), null, 'an unrecognized language code → null, never an arbitrary voice');
CANONICAL_30.forEach((lang) => {
  const locale = Voice.speechLocaleFor(lang);
  const v = Voice.selectVoice([{ lang: locale }], lang);
  assertTrue(!!v && v.lang === locale, `an exact-match voice for ${lang}'s own locale (${locale}) is always selected`);
});
CANONICAL_30.forEach((lang) => {
  assertEqual(Voice.selectVoice([{ lang: 'xx-XX' }], lang), null, `${lang}: a voice list containing only an unrelated language never matches`);
});

// ═══════════════════════════════════════════════════════════════════════
// 3. Sensitive-data safeguards (task §7/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(Voice.containsSensitivePattern('reach me at voter@example.com'), 'an email address trips the guard');
assertTrue(Voice.containsSensitivePattern('your code is 483920'), 'a 6-digit OTP-shaped run trips the guard');
assertTrue(Voice.containsSensitivePattern('call +1 415 555 1234'), 'a phone-shaped digit run trips the guard');
assertTrue(Voice.containsSensitivePattern('balance: 1234.56'), 'a money-shaped decimal amount trips the guard');
assertTrue(Voice.containsSensitivePattern('id 12.34 units'), 'a small decimal-shaped number still trips the guard (defense in depth)');
assertTrue(!Voice.containsSensitivePattern('Welcome to Preferendum! I am Prefy, your guide.'), 'ordinary prose does not trip the guard');
assertTrue(!Voice.containsSensitivePattern(''), 'empty text does not trip the guard');
assertTrue(!Voice.containsSensitivePattern(null), 'null text does not trip the guard (never crashes)');
// The decisive proof: not ONE of Prefy's real, static, translated
// title/body/why strings — across all 30 languages — ever trips the
// guard. If this ever fails, a translation accidentally embedded
// something number/email-shaped, not that the guard is too strict.
let realStringTrips = [];
Object.keys(Content.STRINGS).forEach((lang) => {
  Object.keys(Content.STRINGS[lang]).forEach((key) => {
    const v = Content.STRINGS[lang][key];
    if (Voice.containsSensitivePattern(v)) realStringTrips.push(`${lang}/${key}`);
  });
});
assertEqual(realStringTrips, [], 'zero real registry strings (any language, any key) trip the sensitive-data guard');
// What Prefy must NEVER speak (task §7) — every rendered context across
// every language, run through the exact same guard maybeSpeak() uses.
Content.listContextKeys().forEach((key) => {
  CANONICAL_30.forEach((lang) => {
    const rendered = Content.render(key, lang);
    const text = Voice.buildUtteranceText(rendered);
    assertTrue(!Voice.containsSensitivePattern(text), `rendered context ${key}/${lang} never trips the sensitive-data guard`);
  });
});

// ═══════════════════════════════════════════════════════════════════════
// 4. What Prefy may speak (task §6) — title + body only, never "why"
// ═══════════════════════════════════════════════════════════════════════
assertEqual(Voice.buildUtteranceText({ title: 'A', body: 'B', why: 'C' }), 'A. B', 'speech is built from title + body only, never why (kept visible-only, per task restraint guidance)');
assertEqual(Voice.buildUtteranceText({ title: '', body: 'B' }), 'B', 'a missing title degrades to body alone');
assertEqual(Voice.buildUtteranceText({}), '', 'no title/body → empty string, never undefined/null/[object Object]');
assertEqual(Voice.buildUtteranceText(null), '', 'a missing rendered object → empty string, never a crash');

// ═══════════════════════════════════════════════════════════════════════
// 5. computeSpeakDecision — the one gate every speech attempt passes
//    through (task §4/§5/§7/§9/§17)
// ═══════════════════════════════════════════════════════════════════════
function decide(overrides) {
  return Voice.computeSpeakDecision(Object.assign({
    state: 'WELCOME', previousAnnouncedState: null, muted: false,
    supported: true, unlocked: true, rendered: { title: 'Hi', body: 'There' },
  }, overrides));
}
assertTrue(decide({}).attempt, 'a normal, permitted, non-repeat state attempts to speak');
assertEqual(decide({ muted: true }).attempt, false, 'muted blocks speech (task §4: mute must always work)');
assertEqual(decide({ supported: false }).attempt, false, 'unsupported browsers never attempt speech');
assertEqual(decide({ unlocked: false }).attempt, false, 'a locked (no user-gesture-yet) state never attempts speech (task §5)');
assertEqual(decide({ state: 'THINKING', previousAnnouncedState: 'THINKING' }).attempt, false, 'THINKING never repeats back-to-back (task §9)');
assertTrue(decide({ state: 'THINKING', previousAnnouncedState: 'WELCOME' }).attempt, 'a fresh THINKING episode (preceded by a different state) still speaks once');
assertTrue(decide({ state: 'THINKING', previousAnnouncedState: null }).attempt, 'the very first THINKING episode of a session speaks');
assertEqual(decide({ rendered: { title: '', body: '' } }).attempt, false, 'empty rendered content never attempts speech');
assertEqual(decide({ rendered: { title: 'call me at 5551234567', body: '' } }).attempt, false, 'sensitive-looking content is refused even if everything else permits speech');
// Priority ordering sanity: muted still wins even if also unsupported/locked (order shouldn't matter for the final "no").
assertEqual(decide({ muted: true, supported: false, unlocked: false }).attempt, false, 'any single blocking condition is sufficient to prevent speech');

// ═══════════════════════════════════════════════════════════════════════
// 6. Security states remain protected (task §10/§17) — voice introduces
//    NO new path to POSSIBLE_FRAUD/HACKER_ALERT.
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/setState\(\s*['"]POSSIBLE_FRAUD['"]/.test(js), 'prefy-voice.js never itself requests POSSIBLE_FRAUD');
assertTrue(!/setState\(\s*['"]HACKER_ALERT['"]/.test(js), 'prefy-voice.js never itself requests HACKER_ALERT');
assertTrue(!/guardState/.test(js), "prefy-voice.js never touches guardState() directly — it only ever reacts to a state prefy.js's own guard already approved");
// The voice hooks fire from prefy.js's transition lifecycle, downstream
// of guardState() — re-confirm that gate is still unconditionally
// blocking in Phase 1 with the voice hooks wired in.
['POSSIBLE_FRAUD', 'HACKER_ALERT'].forEach((secState) => {
  const result = Prefy.guardState(secState, 'EXPLAINING', {});
  assertTrue(result.suppressed, `${secState} is still suppressed by guardState() after the voice phase`);
});

// ═══════════════════════════════════════════════════════════════════════
// 7. No network dependency (task §16/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/fetch\(|XMLHttpRequest|\.ajax\(|axios/i.test(js), 'prefy-voice.js contains no fetch/XHR/ajax call anywhere');
assertTrue(!/https?:\/\//.test(js), 'prefy-voice.js contains no hardcoded external URL (no third-party voice endpoint)');
const externalProviders = ['elevenlabs', 'heygen', 'openai', 'azure', 'polly', 'google.*cloud.*tts', 'gcp'];
externalProviders.forEach((p) => {
  assertTrue(!new RegExp(p, 'i').test(js), `prefy-voice.js never references the external provider pattern "${p}"`);
});
assertTrue(!/api[_-]?key/i.test(js), 'prefy-voice.js never references an API key of any kind');

// ═══════════════════════════════════════════════════════════════════════
// 8. No microphone / no speech recognition (task §15/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/getUserMedia|MediaRecorder|SpeechRecognition|webkitSpeechRecognition|requestPermission\(\s*['"]?microphone/i.test(js), 'prefy-voice.js requests no microphone access and uses no speech-recognition API — output only');
assertTrue(js.includes('SpeechSynthesisUtterance'), 'prefy-voice.js does use the Web Speech OUTPUT (synthesis) API, as intended');

// ═══════════════════════════════════════════════════════════════════════
// 9. No new dependency (task §11 of the Motion phase, still binding)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/lottie|rive|gsap/i.test(js), 'prefy-voice.js adds no animation-framework dependency');
assertTrue(!/require\(\s*['"](?!\.\/prefy)/.test(js), "prefy-voice.js's only require() calls (if any) are for this project's own files, never a third-party package");

// ═══════════════════════════════════════════════════════════════════════
// 10. Speech ON/OFF, immediate cancel, persistence (task §4/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(js.includes(`STORAGE_KEY_MUTED = '${Voice.STORAGE_KEY_MUTED}'`) || js.includes('STORAGE_KEY_MUTED'), 'a dedicated, namespaced localStorage key exists for the mute preference');
assertTrue(/pref_prefy_voice/.test(Voice.STORAGE_KEY_MUTED), "the mute preference key follows this project's 'pref_prefy_' storage-key convention, in its own voice-specific namespace");
assertTrue(typeof Voice.setMuted === 'function' && typeof Voice.isMuted === 'function' && typeof Voice.toggleMuted === 'function', 'mute ON/OFF/toggle controls exist and are exported');
assertTrue(typeof Voice.cancelSpeech === 'function', 'an immediate-cancel function exists and is exported');
assertTrue(/window\.speechSynthesis\.cancel\(\)/.test(js), 'cancelSpeech() calls the real speechSynthesis.cancel() API');
assertTrue(/function setMuted[\s\S]{0,300}?window\.speechSynthesis\.cancel\(\)/.test(js), 'muting immediately cancels any in-progress speech (task §4: "mute immediately stops current speech")');
// Node has no `window`, so these never throw even without a browser —
// exactly the same DOM-optional convention as prefy.js's own safeGet/Set.
let threw = false;
try { Voice.setMuted(true); Voice.isMuted(); Voice.toggleMuted(); Voice.cancelSpeech(); } catch (e) { threw = true; }
assertTrue(!threw, 'mute/cancel controls never throw even with no browser/window present');

// ═══════════════════════════════════════════════════════════════════════
// 11. Latest-state-wins for speech + language-switch cancellation
//     (task §8/§11/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(engineJs.includes('_voiceHooks'), 'prefy.js exposes a voice-hook lifecycle');
assertTrue(engineJs.includes('setVoiceHooks: setVoiceHooks'), 'setVoiceHooks is part of the public API');
assertTrue(/onTransitionStart/.test(engineJs) && /onContentVisible/.test(engineJs), 'both required lifecycle hooks (cancel-on-start, speak-on-visible) exist in prefy.js');
// onTransitionStart is invoked at the top of every state-changing call —
// i.e. speech is cancelled the instant a NEW transition begins, before
// the new content is even rendered.
const setContextBody = engineJs.slice(engineJs.indexOf('function setContext('), engineJs.indexOf('function setState('));
assertTrue(/notifyTransitionStart\(\)/.test(setContextBody), 'setContext() cancels obsolete speech via the transition-start hook');
const onLangChangeBody = engineJs.match(/function onLangChange\(\)\s*{([\s\S]*?)\n  }/)[1];
assertTrue(/notifyTransitionStart\(\)/.test(onLangChangeBody), 'a language change also cancels any in-progress speech (task §11: stop speech in the previous language)');
assertTrue(!/notifyContentVisible/.test(onLangChangeBody), 'a language change never itself triggers a NEW speech announcement — only the next genuine state change does, in the new language');
// maybeSpeak re-checks staleness after its async voice lookup — this is
// what actually implements "only the latest legitimate message is
// spoken" when voice loading is slow.
assertTrue(/isStaleTransition/.test(js), 'prefy-voice.js re-checks transition staleness before actually speaking (guards against a slow async voice lookup outliving a newer transition)');
assertTrue(/getVoicesAsync\(\)\.then/.test(js), 'the staleness re-check happens after the async voice lookup, not before (the only point where it could otherwise go stale)');
// Live exercise: three rapid setState calls only ever leave the engine's
// own sequence counter pointing at the LAST call — voice re-checks this
// exact counter, so it inherits the guarantee for free.
const seqBefore = Prefy._transitionSeqValue();
Prefy.setState('THINKING', { title: 'A', body: 'A' });
Prefy.setState('ATTENTION', { title: 'B', body: 'B' });
Prefy.setState('SUCCESS', { title: 'C', body: 'C' });
assertTrue(Prefy._transitionSeqValue() >= seqBefore + 3, 'rapid consecutive calls each bump the shared sequence counter that speech staleness checks against');

// ═══════════════════════════════════════════════════════════════════════
// 12. Reduced-motion independence (task §17) — speech is a completely
//     separate concern from prefers-reduced-motion; muting motion must
//     never silently mute voice, and vice versa.
// ═══════════════════════════════════════════════════════════════════════
assertTrue(!/prefers-reduced-motion/.test(js), 'prefy-voice.js never reads prefers-reduced-motion itself — speech and motion are independent axes (task §12 principle extended to voice)');
assertTrue(!/reducedMotion|prefersReducedMotion/.test(js), 'prefy-voice.js has no reduced-motion-conditional logic of its own');

// ═══════════════════════════════════════════════════════════════════════
// 13. Rate/pitch/volume — conservative, centralized (task §13/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(Voice.SPEECH_PARAMS.rate >= 0.85 && Voice.SPEECH_PARAMS.rate <= 1.15, 'speech rate stays within a natural, non-comedic, non-rushed range');
assertTrue(Voice.SPEECH_PARAMS.pitch >= 0.85 && Voice.SPEECH_PARAMS.pitch <= 1.15, 'speech pitch stays within a natural range (not chipmunk-high or robotically low)');
assertTrue(Voice.SPEECH_PARAMS.volume > 0 && Voice.SPEECH_PARAMS.volume <= 1.0, 'speech volume is within the Web Speech API\'s own safe [0,1] ceiling — never amplified beyond it');
assertTrue(/utter\.rate = SPEECH_PARAMS\.rate/.test(js) && /utter\.pitch = SPEECH_PARAMS\.pitch/.test(js) && /utter\.volume = SPEECH_PARAMS\.volume/.test(js), 'every utterance reads rate/pitch/volume from the one centralized SPEECH_PARAMS object, not a magic number inline');

// ═══════════════════════════════════════════════════════════════════════
// 14. RTL languages use their correct locale; RTL affects text only,
//     never motion/artwork (task §12/§17)
// ═══════════════════════════════════════════════════════════════════════
const RTL_LANGS = ['ar', 'fa', 'he', 'ur'];
RTL_LANGS.forEach((lang) => {
  const locale = Voice.speechLocaleFor(lang);
  assertTrue(!!locale, `${lang} (RTL) has a speech locale mapped`);
  assertTrue(baseOf(locale) === (lang === 'he' ? 'he' : lang), `${lang} (RTL)'s speech locale's base language is itself (${locale})`);
});
function baseOf(bcp47) { return bcp47.split('-')[0].toLowerCase(); }
// The RTL/motion boundary itself was already proven in
// test_prefy_motion.mjs (no scaleX(-1) mirroring anywhere); re-confirm
// voice adds nothing that touches transform/motion.
assertTrue(!/transform|keyframes|rotate|scale\(/i.test(js), 'prefy-voice.js contains no transform/animation logic of its own — motion and artwork are untouched by voice');

// ═══════════════════════════════════════════════════════════════════════
// 15. Accessibility controls (task §14/§17)
// ═══════════════════════════════════════════════════════════════════════
assertTrue(/aria-label/.test(js), 'the voice control sets an aria-label');
assertTrue(/aria-pressed/.test(js), 'the voice control exposes its on/off state via aria-pressed');
assertTrue(/document\.createElement\('button'\)|el\('button'/.test(js), 'the voice control is a real <button>, keyboard-focusable and activatable by default — no custom non-semantic control needed');
assertTrue(!/tabindex\s*=\s*["']?-1/.test(js), 'the voice control is never explicitly removed from the tab order');
assertTrue(js.includes("'chrome.voice.mute'") && js.includes("'chrome.voice.unmute'"), 'the voice control label is drawn from the localized content registry, not a hardcoded English string');
assertEqual(Object.keys(Content.STRINGS).filter((l) => !('chrome.voice.mute' in Content.STRINGS[l]) || !('chrome.voice.unmute' in Content.STRINGS[l])), [], 'every one of the 30 languages has both chrome.voice.mute and chrome.voice.unmute translated (no silent fallback-to-Spanish gap)');

// ═══════════════════════════════════════════════════════════════════════
// 16. Voter/organizer/marketer integration (task §17)
// ═══════════════════════════════════════════════════════════════════════
[
  ['voter_portal.html', voterHtml],
  ['marketer_portal.html', marketerHtml],
  ['preferendum_organizer.html', organizerHtml],
].forEach(([name, html]) => {
  assertTrue(html.includes('/prefy-voice.js'), `${name} loads /prefy-voice.js`);
  assertTrue(/prefy\.js["']><\/script>\s*\n<script src=["']\/prefy-voice\.js/.test(html), `${name} loads prefy-voice.js AFTER prefy.js (dependency order)`);
  assertTrue(/PrefyVoice\.init\(\)/.test(html), `${name} calls PrefyVoice.init()`);
  assertTrue(/if\s*\(\s*window\.PrefyVoice\s*\)\s*PrefyVoice\.init\(\)/.test(html), `${name} guards the PrefyVoice.init() call the same defensive way Prefy.init() itself is guarded`);
});
assertTrue(mainPy.includes("@app.get('/prefy-voice.js')"), 'main.py serves /prefy-voice.js');
assertTrue(css.includes('.prefy-voice-btn'), 'prefy.css styles the voice control');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
