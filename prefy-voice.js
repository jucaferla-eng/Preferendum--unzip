/**
 * prefy-voice.js — Prefy's optional speech layer (30-Language Voice phase).
 *
 * Adds spoken output for Prefy's own controlled contextual copy using the
 * browser's native Web Speech `speechSynthesis` API only — no external
 * voice provider, no API key, no new backend service, no new dependency.
 *
 * Loaded AFTER prefy-content.js and prefy.js. Registers a small set of
 * lifecycle hooks on `Prefy` (see prefy.js's `setVoiceHooks`) — prefy.js
 * itself has zero knowledge of speech synthesis, voices, or locales.
 * This file, in turn, has zero knowledge of motion, CSS classes, or DOM
 * layout beyond the one footer element it's handed to attach its own
 * mute control to.
 *
 * Architecture mirrors every other file in this project: a pure, DOM/
 * SpeechSynthesis-free core (fully unit-testable from Node — see
 * test_prefy_voice.mjs) plus thin browser-only wiring for the actual
 * `speechSynthesis`/localStorage/DOM calls.
 *
 * Reuses `window.PreferendumLang.currentLanguage()` (via Prefy's own
 * `currentLang()` convention) as the ONE source of truth for "what
 * language is active" — this file creates no second language resolver.
 *
 * Prefy may only ever speak the exact title/body text prefy.js already
 * decided to show on screen (see prefy.js's `onContentVisible` hook) —
 * never anything else, and never anything that fails the sensitive-data
 * guard below.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PrefyVoice = factory();
  }
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════
  // PURE CORE — no DOM, no speechSynthesis, no globals read. Every
  // function here takes plain values and returns plain values.
  // ═══════════════════════════════════════════════════════════════════════

  // Task §2: map each of Prefy's canonical 30 languages to a real,
  // defensible BCP-47 speech locale. A locale code existing here is NOT a
  // claim that a matching voice is installed anywhere — see selectVoice()
  // for the graceful-fallback algorithm that actually decides that.
  var SPEECH_LOCALES = {
    es: 'es-ES', en: 'en-US', pt: 'pt-BR', fr: 'fr-FR', de: 'de-DE',
    it: 'it-IT', ja: 'ja-JP', ko: 'ko-KR', zh: 'zh-CN', ar: 'ar-SA',
    ru: 'ru-RU', hi: 'hi-IN', nl: 'nl-NL', pl: 'pl-PL', tr: 'tr-TR',
    id: 'id-ID', vi: 'vi-VN', th: 'th-TH', fil: 'fil-PH', bn: 'bn-BD',
    ur: 'ur-PK', fa: 'fa-IR', he: 'he-IL', sv: 'sv-SE', da: 'da-DK',
    fi: 'fi-FI', el: 'el-GR', cs: 'cs-CZ', ro: 'ro-RO', uk: 'uk-UA',
  };
  var CANONICAL_LANGUAGES = Object.keys(SPEECH_LOCALES);

  // Task §3 step 3 ("an appropriate available language voice") — extra
  // base-language codes worth trying, in priority order, BEFORE giving up
  // on a language entirely. Every entry here is still genuinely the same
  // spoken language (regional/legacy tag variants), never a different
  // language standing in for it.
  var LANGUAGE_ALIASES = {
    pt: ['pt-pt', 'pt-br', 'pt'],
    zh: ['zh-cn', 'zh-hans', 'zh-tw', 'zh-hk', 'zh-hant', 'zh'],
    fil: ['fil', 'tl'], // some platforms still label Filipino voices 'tl' (Tagalog)
    he: ['he', 'iw'],   // legacy ISO code some engines still emit for Hebrew
  };

  function speechLocaleFor(langCode) {
    return SPEECH_LOCALES[langCode] || null;
  }

  function baseLang(bcp47) {
    return String(bcp47 || '').split('-')[0].toLowerCase();
  }

  /**
   * Graceful voice selection (task §3): exact locale match, then
   * base-language match, then an appropriate alias, then null — NEVER an
   * unrelated language's voice. `voices` is a plain array of
   * {lang, name, ...}-shaped objects (mirrors SpeechSynthesisVoice; the
   * browser wiring passes the real list, tests pass plain fixtures).
   */
  function selectVoice(voices, langCode) {
    var target = speechLocaleFor(langCode);
    if (!target || !voices || !voices.length) return null;
    var targetLower = target.toLowerCase();
    var targetBase = baseLang(target);

    var i;
    // 1) exact locale match
    for (i = 0; i < voices.length; i++) {
      if (String(voices[i].lang || '').toLowerCase() === targetLower) return voices[i];
    }
    // 2) base-language match
    for (i = 0; i < voices.length; i++) {
      if (baseLang(voices[i].lang) === targetBase) return voices[i];
    }
    // 3) an appropriate available alias for this language
    var aliases = LANGUAGE_ALIASES[langCode] || [];
    for (var a = 0; a < aliases.length; a++) {
      for (i = 0; i < voices.length; i++) {
        if (baseLang(voices[i].lang) === aliases[a]) return voices[i];
      }
    }
    // 4) no compatible voice — never substitute an unrelated language
    return null;
  }

  // Task §7: speech is decorative reinforcement of text ALREADY on
  // screen, and Prefy's real registry copy (verified below, across all
  // 30 languages) never contains a digit run this long, an email
  // address, or a money-shaped number — so these patterns exist purely
  // as a defense-in-depth net against a future caller passing arbitrary
  // text to Prefy.setState()'s `content` param (unlike setContext(), that
  // path is NOT limited to the static, pre-approved registry).
  var SENSITIVE_PATTERNS = [
    /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/, // email address
    /\d{4,}/,                                          // OTP/phone/ID/card/account-shaped digit run
    /\d+[.,]\d{2}\b/,                                  // a money-shaped decimal amount
  ];
  function containsSensitivePattern(text) {
    if (!text) return false;
    for (var i = 0; i < SENSITIVE_PATTERNS.length; i++) {
      if (SENSITIVE_PATTERNS[i].test(text)) return true;
    }
    return false;
  }

  // Task §6: Prefy may speak ONLY its title + body — never `why` (kept
  // out to keep speech short and restrained; `why` remains fully visible
  // in text) and never any field beyond what prefy.js already rendered
  // on screen.
  function buildUtteranceText(rendered) {
    if (!rendered) return '';
    return [rendered.title, rendered.body].filter(Boolean).join('. ').trim();
  }

  // Task §9: THINKING must never loop ("Thinking... Thinking..."). Pure
  // decision: never speak two THINKING announcements back to back: any
  // OTHER state in between resets this, so a later, genuinely fresh
  // THINKING episode still gets its one short phrase.
  function shouldSpeakForState(state, previousAnnouncedState) {
    if (state === 'THINKING' && previousAnnouncedState === 'THINKING') return false;
    return true;
  }

  /**
   * The ONE gate every speech attempt passes through, fully pure and
   * DOM/speechSynthesis-free — every browser-specific fact (muted,
   * unlocked, supported) is passed in as a plain value rather than read
   * from a global, so this is exhaustively testable from Node. Only
   * voice SELECTION (which needs the real installed-voice list) and the
   * actual `speechSynthesis.speak()` call happen after this, in the
   * browser-only wiring below.
   */
  function computeSpeakDecision(opts) {
    opts = opts || {};
    if (!shouldSpeakForState(opts.state, opts.previousAnnouncedState)) return { attempt: false, reason: 'thinking_no_repeat' };
    if (opts.muted) return { attempt: false, reason: 'muted' };
    if (!opts.supported) return { attempt: false, reason: 'unsupported' };
    if (!opts.unlocked) return { attempt: false, reason: 'locked' }; // task §5: never retried later — just skipped
    var text = buildUtteranceText(opts.rendered);
    if (!text) return { attempt: false, reason: 'empty_text' };
    if (containsSensitivePattern(text)) return { attempt: false, reason: 'sensitive_pattern' }; // task §7 safeguard
    return { attempt: true, reason: '', text: text };
  }

  // Task §13: conservative, centralized, natural defaults — never
  // exposed as unsafe amplification (volume capped at 1.0, the Web
  // Speech API's own ceiling). Kept in one place so a future phase can
  // tune these without touching call sites.
  var SPEECH_PARAMS = { rate: 1.0, pitch: 1.0, volume: 0.85 };

  var STORAGE_KEY_MUTED = 'pref_prefy_voice_muted';

  // ═══════════════════════════════════════════════════════════════════════
  // BROWSER-ONLY WIRING
  // ═══════════════════════════════════════════════════════════════════════

  function hasBrowser() {
    return typeof window !== 'undefined' && typeof document !== 'undefined';
  }
  function hasSpeechSynthesis() {
    return hasBrowser() && typeof window.speechSynthesis !== 'undefined' && typeof window.SpeechSynthesisUtterance === 'function';
  }
  function safeGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function safeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }

  function currentLang() {
    if (hasBrowser() && window.PreferendumLang && typeof window.PreferendumLang.currentLanguage === 'function') {
      return window.PreferendumLang.currentLanguage();
    }
    return 'es';
  }

  var _muted = false;       // task §4: "default behavior must NOT be annoying" — restrained, not silent;
                             // see the phase report for this product judgment call and how to flip it.
  var _unlocked = false;    // task §5: only a real Prefy user-gesture flips this, once, per page load.
  var _lastAnnouncedState = null;
  var _voicesCache = null;

  function isMuted() { return _muted; }

  function setMuted(value) {
    _muted = !!value;
    safeSet(STORAGE_KEY_MUTED, _muted ? '1' : '0');
    if (_muted && hasSpeechSynthesis()) window.speechSynthesis.cancel();
  }

  function toggleMuted() {
    setMuted(!_muted);
    return _muted;
  }

  function markUnlocked() {
    _unlocked = true;
  }

  function cancelSpeech() {
    if (hasSpeechSynthesis()) {
      try { window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    }
  }

  // Chrome (among others) populates getVoices() asynchronously the first
  // time — resolves as soon as a non-empty list is available, but never
  // hangs forever if a browser simply never fires 'voiceschanged' for an
  // already-complete list.
  function getVoicesAsync() {
    return new Promise(function (resolve) {
      if (!hasSpeechSynthesis()) { resolve([]); return; }
      var existing = window.speechSynthesis.getVoices();
      if (existing && existing.length) { resolve(existing); return; }
      var settled = false;
      var finish = function () {
        if (settled) return;
        settled = true;
        try { window.speechSynthesis.removeEventListener('voiceschanged', onChange); } catch (e) { /* ignore */ }
        resolve(window.speechSynthesis.getVoices() || []);
      };
      var onChange = function () { finish(); };
      try { window.speechSynthesis.addEventListener('voiceschanged', onChange); } catch (e) { /* ignore */ }
      setTimeout(finish, 300);
    });
  }

  /**
   * The one entry point prefy.js's `onContentVisible` hook calls. Every
   * check below can independently and silently decline to speak — never
   * throws, never blocks the (already-visible) UI, never retries.
   */
  function maybeSpeak(rendered, state, mySeq) {
    var previous = _lastAnnouncedState;
    _lastAnnouncedState = state;

    var decision = computeSpeakDecision({
      state: state,
      previousAnnouncedState: previous,
      muted: _muted,
      supported: hasSpeechSynthesis(),
      unlocked: _unlocked,
      rendered: rendered,
    });
    if (!decision.attempt) return;

    getVoicesAsync().then(function (voices) {
      // Re-check staleness AFTER the async voice lookup (task §8/K):
      // a newer transition may have started while voices were loading.
      if (window.Prefy && typeof window.Prefy.isStaleTransition === 'function' && typeof window.Prefy._transitionSeqValue === 'function') {
        if (window.Prefy.isStaleTransition(mySeq, window.Prefy._transitionSeqValue())) return;
      }
      if (_muted) return; // may have been muted while voices were loading

      var lang = currentLang();
      var voice = selectVoice(voices, lang);
      if (!voice) return; // task §3: never speak with an unrelated-language voice

      cancelSpeech();
      var utter = new window.SpeechSynthesisUtterance(decision.text);
      utter.voice = voice;
      utter.lang = speechLocaleFor(lang) || voice.lang;
      utter.rate = SPEECH_PARAMS.rate;
      utter.pitch = SPEECH_PARAMS.pitch;
      utter.volume = SPEECH_PARAMS.volume;
      window.speechSynthesis.speak(utter);
    }).catch(function () { /* never let a speech failure surface to the caller */ });
  }

  function el(tag, attrs) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    return e;
  }

  function localizedStr(key, fallback) {
    var lang = currentLang();
    return window.PrefyContent ? window.PrefyContent.str(lang, key) : fallback;
  }

  var _speakerBtn = null;
  function updateSpeakerBtnLabel() {
    if (!_speakerBtn || _speakerBtn.disabled) return;
    var label = localizedStr(_muted ? 'chrome.voice.unmute' : 'chrome.voice.mute', _muted ? 'Unmute' : 'Mute');
    _speakerBtn.setAttribute('aria-label', label);
    _speakerBtn.setAttribute('aria-pressed', String(!_muted));
    _speakerBtn.textContent = _muted ? '🔇' : '🔊';
  }

  /**
   * Mounts Prefy's voice control into the panel footer. Idempotent by
   * design (task §3): if a button is already attached anywhere in the
   * document, this is a no-op — calling it twice (e.g. from a future
   * re-entrant hook path) can never produce a second button.
   *
   * Task §2: an unsupported browser/device does NOT get an invisible
   * feature — it gets a visibly present, genuinely disabled control with
   * a localized explanation, so voice availability is always legible
   * instead of silently absent (which reads as "broken", not "N/A").
   */
  function onFooterReady(footer) {
    if (!hasBrowser() || !footer) return;
    if (_speakerBtn && document.body && document.body.contains(_speakerBtn)) return;

    var supported = hasSpeechSynthesis();
    _speakerBtn = el('button', { type: 'button', class: 'prefy-icon-btn prefy-voice-btn' });

    if (!supported) {
      _speakerBtn.disabled = true;
      _speakerBtn.classList.add('prefy-voice-btn-disabled');
      _speakerBtn.textContent = '🔇';
      _speakerBtn.setAttribute('aria-label', localizedStr('chrome.voice.unavailable', 'Voice is not available on this device or browser.'));
      _speakerBtn.setAttribute('aria-disabled', 'true');
      footer.insertBefore(_speakerBtn, footer.firstChild);
      return; // genuinely inert — no click handler, no lang-change listener needed
    }

    updateSpeakerBtnLabel();
    _speakerBtn.addEventListener('click', function () {
      markUnlocked();
      toggleMuted();
      updateSpeakerBtnLabel();
    });
    footer.insertBefore(_speakerBtn, footer.firstChild);
    document.addEventListener('preferendum:langchange', updateSpeakerBtnLabel);
  }

  function init() {
    if (!hasBrowser()) return;
    var storedMuted = safeGet(STORAGE_KEY_MUTED);
    _muted = storedMuted === '1';
    if (!window.Prefy || typeof window.Prefy.setVoiceHooks !== 'function') return;
    window.Prefy.setVoiceHooks({
      onTransitionStart: cancelSpeech,
      onContentVisible: maybeSpeak,
      onFooterReady: onFooterReady,
      onUserGesture: markUnlocked,
    });
  }

  return {
    init: init,

    // Pure — exposed for tests
    SPEECH_LOCALES: SPEECH_LOCALES,
    CANONICAL_LANGUAGES: CANONICAL_LANGUAGES,
    SPEECH_PARAMS: SPEECH_PARAMS,
    speechLocaleFor: speechLocaleFor,
    selectVoice: selectVoice,
    containsSensitivePattern: containsSensitivePattern,
    buildUtteranceText: buildUtteranceText,
    shouldSpeakForState: shouldSpeakForState,
    computeSpeakDecision: computeSpeakDecision,
    STORAGE_KEY_MUTED: STORAGE_KEY_MUTED,

    // Browser wiring — exposed for tests / manual QA console use
    isSpeechSupported: hasSpeechSynthesis,
    isMuted: isMuted,
    setMuted: setMuted,
    toggleMuted: toggleMuted,
    markUnlocked: markUnlocked,
    cancelSpeech: cancelSpeech,
    getVoicesAsync: getVoicesAsync,
    maybeSpeak: maybeSpeak,
    // Exposed for tests only (task §5: proving the mount is idempotent
    // means being able to call it again deliberately) — prefy.js never
    // calls this directly itself; it only ever reaches PrefyVoice through
    // the onFooterReady hook registered in init().
    onFooterReady: onFooterReady,

    // Introspection (tests, debugging) — state name only, never spoken text
    _debugState: function () { return { muted: _muted, unlocked: _unlocked, lastAnnouncedState: _lastAnnouncedState }; },
    _resetForTests: function () { _muted = false; _unlocked = false; _lastAnnouncedState = null; _voicesCache = null; },

    // Real runtime diagnostic (task §4) — a safe, read-only status
    // snapshot the human tester can call directly from the browser
    // console (`PrefyVoice._status()`) to see exactly why voice is or
    // isn't working, without exposing any spoken text, localStorage
    // content, or a way to mutate state. Not a production debug
    // backdoor: nothing here can change behavior, only report it.
    _status: function () {
      return {
        speechSynthesisSupported: hasSpeechSynthesis(),
        typeofSpeechSynthesis: hasBrowser() ? typeof window.speechSynthesis : 'no-window',
        typeofSpeechSynthesisUtterance: hasBrowser() ? typeof window.SpeechSynthesisUtterance : 'no-window',
        hooksRegisteredOnPrefy: !!(hasBrowser() && window.Prefy && typeof window.Prefy.setVoiceHooks === 'function'),
        buttonMounted: !!(_speakerBtn && hasBrowser() && document.body && document.body.contains(_speakerBtn)),
        buttonDisabled: !!(_speakerBtn && _speakerBtn.disabled),
        muted: _muted,
        unlocked: _unlocked,
      };
    },
  };
});
