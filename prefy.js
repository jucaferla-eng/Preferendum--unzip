/**
 * prefy.js — Preferendum's shared contextual guide engine.
 *
 * Used identically by voter_portal.html, marketer_portal.html, and
 * preferendum_organizer.html (one module, not three copies — per the
 * Phase 1 product decision). Depends on prefy-content.js (state list +
 * context registry + copy) and, in a browser, on lang.js
 * (window.PreferendumLang) for the CURRENT resolved language — this file
 * never resolves language itself and never guesses country/device
 * language on its own.
 *
 * Architecture mirrors lang.js and eligibility.py/socioeconomic.py: a pure,
 * DOM-free core (fully unit-testable from Node — see test_prefy.mjs) plus
 * thin browser-only wiring for the DOM/localStorage/events. The pure core
 * is what enforces the one rule that must never regress: POSSIBLE_FRAUD
 * and HACKER_ALERT can never be applied by an ordinary Phase 1 event.
 *
 * Prefy explains; it never decides. Nothing in this file computes a tier,
 * an income estimate, an eligibility result, a fraud signal, or a balance
 * — it only ever renders copy that PrefyContent.render() already prepared
 * from a context key the CALLER chose after ITS OWN business logic ran.
 *
 * Exported as CommonJS (Node tests) AND attached to `window.Prefy` in a
 * browser — same file, same logic, no drift.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(typeof require === 'function' ? require('./prefy-content.js') : null);
  } else {
    root.Prefy = factory(root.PrefyContent);
  }
})(typeof window !== 'undefined' ? window : this, function (PrefyContent) {
  'use strict';

  if (!PrefyContent) {
    throw new Error('prefy.js requires prefy-content.js to be loaded first');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // PURE CORE — no DOM, no localStorage, no globals read. Every function
  // here takes plain values and returns plain values, so it can be tested
  // with zero browser/mocking machinery.
  // ═══════════════════════════════════════════════════════════════════════

  // Phase 1 NEVER assigns a real unlock token anywhere in this codebase.
  // A future, explicit, separately-reviewed security-event contract would
  // be the only legitimate way to give a caller a matching token — nothing
  // in this phase's portal wiring holds one, by construction.
  var SECURITY_UNLOCK_TOKEN_PHASE1 = null;

  /**
   * The ONE gate every state change passes through. Returns the state that
   * is actually safe to apply, plus whether the request was suppressed.
   * A security-classified state is suppressed unless the caller supplies
   * the exact Phase-1 token — which is `null`, and `null !== null` is
   * false, so this is unconditionally blocking in Phase 1 regardless of
   * what any caller passes.
   */
  function guardState(requestedState, currentState, opts) {
    opts = opts || {};
    if (!PrefyContent.isValidState(requestedState)) {
      return { state: PrefyContent.DEFAULT_STATE, suppressed: true, reason: 'unknown_state' };
    }
    if (PrefyContent.isSecurityState(requestedState)) {
      var tokenOk = opts.securityUnlockToken !== undefined
        && opts.securityUnlockToken !== null
        && SECURITY_UNLOCK_TOKEN_PHASE1 !== null
        && opts.securityUnlockToken === SECURITY_UNLOCK_TOKEN_PHASE1;
      if (!tokenOk) {
        // Never escalate into an unrequested state — fall back to whatever
        // was already showing, or the safe default if nothing was.
        return { state: currentState || PrefyContent.DEFAULT_STATE, suppressed: true, reason: 'security_state_locked_phase1' };
      }
    }
    return { state: requestedState, suppressed: false, reason: '' };
  }

  /** Pure minimize/open reducer. */
  function nextUIState(current, action) {
    if (action === 'minimize') return 'minimized';
    if (action === 'open') return 'open';
    if (action === 'toggle') return current === 'open' ? 'minimized' : 'open';
    return current;
  }

  /**
   * Decides whether a context should auto-expand right now.
   * Never auto-expands a context the registry didn't mark
   * firstVisitAutoOpen, and never auto-expands a context already seen —
   * that's what keeps Prefy from repeating itself on every visit.
   */
  function shouldAutoOpen(contextEntry, hasSeenBefore) {
    return !!(contextEntry && contextEntry.firstVisitAutoOpen && !hasSeenBefore);
  }

  var STORAGE_PREFIX = 'pref_prefy_';
  function storageKeySeen(contextKey) { return STORAGE_PREFIX + 'seen_' + contextKey; }
  var STORAGE_KEY_MINIMIZED = STORAGE_PREFIX + 'minimized';

  // ═══════════════════════════════════════════════════════════════════════
  // BROWSER-ONLY WIRING
  // ═══════════════════════════════════════════════════════════════════════

  function hasBrowser() {
    return typeof window !== 'undefined' && typeof document !== 'undefined';
  }

  function safeGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function safeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }
  function safeRemove(key) {
    try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ }
  }

  function hasSeen(contextKey) {
    return safeGet(storageKeySeen(contextKey)) === '1';
  }
  function markSeen(contextKey) {
    safeSet(storageKeySeen(contextKey), '1');
  }
  function forgetContext(contextKey) {
    safeRemove(storageKeySeen(contextKey));
  }
  function forgetAll() {
    if (!hasBrowser()) return;
    PrefyContent.listContextKeys().forEach(forgetContext);
  }

  function currentLang() {
    if (hasBrowser() && window.PreferendumLang && typeof window.PreferendumLang.currentLanguage === 'function') {
      return window.PreferendumLang.currentLanguage();
    }
    return 'es'; // lang.js not loaded — safe, honest default, not a guess (same convention voter_portal.html's own getViewerLang() uses)
  }

  function prefersReducedMotion() {
    if (!hasBrowser() || typeof window.matchMedia !== 'function') return false;
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  // Emoji glyphs are the SAFETY-NET fallback (task §13 / Phase 1 §E) —
  // shown only if a real Prefy PNG (prefy-content.js's ASSETS map, now
  // pointing at the 15 approved, installed images under assets/prefy/)
  // fails to load. Reuses the same circular-badge visual language as
  // voter_portal.html's pre-existing .welcome-avatar element rather than
  // inventing a new look, so a failed image degrades gracefully instead
  // of breaking the page.
  var FALLBACK_GLYPH = {
    WELCOME: '👋', EXPLAINING: '💬', PRESENTING: '📋',
    THINKING: '💭', IDEA: '💡', ATTENTION: '⚠️',
    MISSING_INFORMATION: '✏️', ERROR: '❗', POSSIBLE_FRAUD: '🔍',
    HACKER_ALERT: '🚨', GOOD_JOB: '👍', SUCCESS: '✅',
    THANKS: '🙏', HELP: '❓', GOODBYE: '👋',
  };
  var FALLBACK_COLOR = {
    WELCOME: '#2d6eff', EXPLAINING: '#2d6eff', PRESENTING: '#2d6eff',
    THINKING: '#5b6478', IDEA: '#c49a2a', ATTENTION: '#c49a2a',
    MISSING_INFORMATION: '#c49a2a', ERROR: '#c0392b', POSSIBLE_FRAUD: '#c0392b',
    HACKER_ALERT: '#c0392b', GOOD_JOB: '#1a7a4a', SUCCESS: '#1a7a4a',
    THANKS: '#1a7a4a', HELP: '#2d6eff', GOODBYE: '#2d6eff',
  };

  // ═══════════════════════════════════════════════════════════════════════
  // MOTION — one profile per canonical state (task: "controlled motion
  // profiles for all 15 states"). Every className below is a ONE-SHOT
  // CSS animation (see prefy.css) — never `infinite`, always removed
  // after `duration` ms. POSSIBLE_FRAUD/HACKER_ALERT have real profiles
  // (installable/testable) but reaching them still goes through
  // guardState() above, which is the ONLY thing that decides whether
  // they can ever actually play — nothing here grants a new way in.
  // ═══════════════════════════════════════════════════════════════════════
  var STATE_MOTION = {
    WELCOME:              { className: 'prefy-m-welcome',   duration: 700 },
    EXPLAINING:           { className: 'prefy-m-explaining',duration: 450 },
    PRESENTING:           { className: 'prefy-m-presenting',duration: 420 },
    THINKING:             { className: 'prefy-m-thinking',  duration: 3200 },
    IDEA:                 { className: 'prefy-m-idea',      duration: 380 },
    ATTENTION:            { className: 'prefy-m-attention', duration: 450 },
    MISSING_INFORMATION:  { className: 'prefy-m-missing',   duration: 500 },
    ERROR:                { className: 'prefy-m-error',     duration: 350 },
    POSSIBLE_FRAUD:       { className: 'prefy-m-fraud',     duration: 500 },
    HACKER_ALERT:         { className: 'prefy-m-hacker',    duration: 700 },
    GOOD_JOB:             { className: 'prefy-m-good-job',  duration: 450 },
    SUCCESS:              { className: 'prefy-m-success',   duration: 600 },
    THANKS:               { className: 'prefy-m-thanks',    duration: 550 },
    HELP:                 { className: 'prefy-m-help',      duration: 450, glow: true },
    GOODBYE:              { className: 'prefy-m-goodbye',   duration: 500 },
  };
  var CONTENT_FADE_OUT_MS = 140;
  var CONTENT_FADE_IN_MS = 160;

  /** Pure — the ONE check every deferred transition step makes before
   * touching the DOM. A newer setContext/setState call always bumps the
   * sequence counter, so a stale (superseded) timeout's `mySeq` will
   * never match `currentSeq` again — this is what guarantees "the latest
   * legitimate state must win" and that no timer can leave Prefy showing
   * an obsolete state, without needing to cancel any actual timers. */
  function isStaleTransition(mySeq, currentSeq) {
    return mySeq !== currentSeq;
  }

  var _state = {
    ui: 'minimized',          // 'open' | 'minimized'
    currentContextKey: null,
    currentState: PrefyContent.DEFAULT_STATE,
    initialized: false,
    dom: null,
  };
  var _transitionSeq = 0;

  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }

  // Tracks, per canonical state name, whether that state's real image has
  // ever failed to load — once true, we stop trying to show the broken
  // image and just render the neutral fallback badge for that state for
  // the rest of the session (task §13: "do not break the page").
  var _failedAssetStates = {};

  function buildDom() {
    var root = el('div', { class: 'prefy-root', 'aria-live': 'polite' });

    var bubble = el('button', {
      type: 'button', class: 'prefy-bubble',
      'aria-label': PrefyContent.str(currentLang(), 'chrome.name'),
      'aria-expanded': 'false',
    });
    // Real character art + emoji-badge fallback, both present; CSS/JS
    // toggles which one is visible (see updateAssetVisibility()).
    var bubbleImg = el('img', { class: 'prefy-bubble-img', alt: '' });
    var bubbleGlyph = el('span', { class: 'prefy-bubble-glyph', 'aria-hidden': 'true' });
    // Idle float lives on this inner wrapper, not on the button itself —
    // see prefy.css's comment on .prefy-bubble-float for why (the button
    // already owns `transform` for hover/active/tap-react).
    var bubbleFloat = el('div', { class: 'prefy-bubble-float', 'aria-hidden': 'true' }, [bubbleImg, bubbleGlyph]);
    bubbleImg.addEventListener('error', function () { onAssetError(_state.currentState); });
    bubble.appendChild(bubbleFloat);
    bubble.addEventListener('click', function () {
      // One-shot friendly reaction (task §5) — purely visual, never
      // touches business state and never fires a network request.
      if (!prefersReducedMotion()) {
        bubble.classList.remove('prefy-tap-react');
        void bubble.offsetWidth; // force reflow so a rapid repeat tap restarts the animation
        bubble.classList.add('prefy-tap-react');
        setTimeout(function () { bubble.classList.remove('prefy-tap-react'); }, 220);
      }
      open();
    });

    var panel = el('div', { class: 'prefy-panel', role: 'dialog', 'aria-label': PrefyContent.str(currentLang(), 'chrome.name') });

    var header = el('div', { class: 'prefy-panel-header' });
    // alt="" (decorative) — the visible, aria-live title text right next
    // to the character already conveys the same information; giving the
    // image its own alt text too would announce it twice to a screen
    // reader. Character identity/expression is supplementary, not the
    // primary information channel here.
    var avatarImg = el('img', { class: 'prefy-avatar-img', alt: '' });
    var avatar = el('span', { class: 'prefy-avatar', 'aria-hidden': 'true' });
    avatarImg.addEventListener('error', function () { onAssetError(_state.currentState); });
    var avatarWrap = el('div', { class: 'prefy-avatar-wrap' }, [avatarImg, avatar]);
    var titleWrap = el('div', { class: 'prefy-title-wrap' });
    var title = el('div', { class: 'prefy-title' });
    titleWrap.appendChild(title);
    var closeBtn = el('button', { type: 'button', class: 'prefy-icon-btn prefy-minimize', 'aria-label': PrefyContent.str(currentLang(), 'chrome.minimize'), text: '–' });
    closeBtn.addEventListener('click', function () { minimize(); });
    header.appendChild(avatarWrap);
    header.appendChild(titleWrap);
    header.appendChild(closeBtn);

    var body = el('div', { class: 'prefy-body' });
    var bodyText = el('div', { class: 'prefy-body-text' });
    var whyText = el('div', { class: 'prefy-why-text' });
    body.appendChild(bodyText);
    body.appendChild(whyText);

    var footer = el('div', { class: 'prefy-panel-footer' });
    var helpBtn = el('button', { type: 'button', class: 'prefy-help-btn', text: PrefyContent.str(currentLang(), 'chrome.help') });
    helpBtn.addEventListener('click', function () { openHelp(); });
    var reopenBtn = el('button', { type: 'button', class: 'prefy-reopen-btn', text: PrefyContent.str(currentLang(), 'chrome.reopen') });
    reopenBtn.addEventListener('click', function () { reopenCurrent(); });
    footer.appendChild(helpBtn);
    footer.appendChild(reopenBtn);

    panel.appendChild(header);
    panel.appendChild(body);
    panel.appendChild(footer);

    root.appendChild(bubble);
    root.appendChild(panel);

    return {
      root: root, bubble: bubble, bubbleFloat: bubbleFloat, bubbleImg: bubbleImg, bubbleGlyph: bubbleGlyph, panel: panel,
      avatarWrap: avatarWrap, avatarImg: avatarImg, avatar: avatar, title: title, bodyText: bodyText, whyText: whyText,
      closeBtn: closeBtn,
    };
  }

  function onAssetError(state) {
    if (_failedAssetStates[state]) return;
    _failedAssetStates[state] = true;
    updateAssetVisibility();
  }

  function updateAssetVisibility() {
    if (!hasBrowser() || !_state.dom) return;
    var failed = !!_failedAssetStates[_state.currentState];
    _state.dom.avatarImg.style.display = failed ? 'none' : '';
    _state.dom.avatar.style.display = failed ? '' : 'none';
    _state.dom.bubbleImg.style.display = failed ? 'none' : '';
    _state.dom.bubbleGlyph.style.display = failed ? '' : 'none';
  }

  function applyStateVisuals(state) {
    if (!hasBrowser() || !_state.dom) return;
    var asset = PrefyContent.ASSETS[state] || PrefyContent.ASSETS[PrefyContent.DEFAULT_STATE];
    var color = FALLBACK_COLOR[state] || FALLBACK_COLOR[PrefyContent.DEFAULT_STATE];
    var glyph = FALLBACK_GLYPH[state] || FALLBACK_GLYPH[PrefyContent.DEFAULT_STATE];
    if (asset && asset.png) {
      _state.dom.avatarImg.src = asset.png;
      _state.dom.bubbleImg.src = asset.png;
    }
    _state.dom.avatar.textContent = glyph;
    _state.dom.avatar.style.background = color;
    _state.dom.bubbleGlyph.textContent = glyph;
    _state.dom.bubble.style.background = color;
    _state.dom.root.setAttribute('data-prefy-state', state);
    updateAssetVisibility();
  }

  // Panel-open-vs-minimized visibility only — CSS `transition` (not
  // `animation`) on .prefy-panel/.prefy-bubble handles the actual smooth
  // open/close/minimize motion purely from this class toggle, so a rapid
  // double-toggle naturally interrupts/reverses cleanly (a browser
  // transition always animates from its current interpolated value, not
  // from scratch) with no JS-side race to guard against here.
  function updatePanelVisibility() {
    if (!hasBrowser() || !_state.dom) return;
    var isOpen = _state.ui === 'open';
    _state.dom.panel.classList.toggle('prefy-visible', isOpen);
    _state.dom.bubble.classList.toggle('prefy-hidden-while-open', isOpen);
    _state.dom.bubble.setAttribute('aria-expanded', String(isOpen));
  }

  function render() {
    if (!hasBrowser() || !_state.dom) return;
    updatePanelVisibility();
    applyStateVisuals(_state.currentState);
  }

  function renderContent(rendered) {
    if (!hasBrowser() || !_state.dom) return;
    _state.dom.title.textContent = rendered.title;
    _state.dom.bodyText.textContent = rendered.body;
    _state.dom.whyText.textContent = rendered.why || '';
    _state.dom.whyText.style.display = rendered.why ? 'block' : 'none';
  }

  var _allMotionClassNames = Object.keys(STATE_MOTION).map(function (k) { return STATE_MOTION[k].className; });

  /**
   * The one-shot "character reacts to its new state" motion (task §2).
   * Always a FIXED, small number of iterations (see prefy.css — never
   * `infinite`), always cleaned up after its own duration. Skipped
   * entirely under prefers-reduced-motion (task §7).
   */
  function playEntranceMotion(state, mySeq) {
    if (!hasBrowser() || !_state.dom || prefersReducedMotion()) return;
    var profile = STATE_MOTION[state] || STATE_MOTION[PrefyContent.DEFAULT_STATE];
    if (!profile) return;
    var targets = [_state.dom.avatarImg, _state.dom.avatar, _state.dom.bubbleImg, _state.dom.bubbleGlyph];
    targets.forEach(function (t) {
      _allMotionClassNames.forEach(function (c) { t.classList.remove(c); });
      void t.offsetWidth; // force reflow so re-adding the SAME class still restarts the animation
      t.classList.add(profile.className);
    });
    if (profile.glow) _state.dom.avatarWrap.classList.add('prefy-glow-once');
    setTimeout(function () {
      // No staleness check needed here: this only ever removes the EXACT
      // class name it added above. If a newer transition already started,
      // it already stripped this class itself before adding its own —
      // this is then a harmless no-op, never a removal of the wrong class.
      targets.forEach(function (t) { t.classList.remove(profile.className); });
      if (profile.glow) _state.dom.avatarWrap.classList.remove('prefy-glow-once');
    }, profile.duration);
  }

  /**
   * Task §3's full sequence: fade/scale out → asset+content swap → fade
   * in → state-specific entrance → idle. Every async step is guarded by
   * `isStaleTransition`, so if setContext/setState is called again before
   * an earlier call's steps finish, only the LATEST call's steps ever
   * touch the DOM — an old call simply stops silently, never overwriting
   * newer content and never leaving a half-applied obsolete state.
   */
  function transitionToRendered(rendered, mySeq, opts) {
    opts = opts || {};
    if (!hasBrowser() || !_state.dom) return;

    var reduced = prefersReducedMotion();
    if (opts.skipAnimation || reduced) {
      renderContent(rendered);
      applyStateVisuals(_state.currentState);
      updatePanelVisibility();
      return;
    }

    var contentEls = [_state.dom.title, _state.dom.bodyText, _state.dom.whyText];
    contentEls.forEach(function (elx) {
      elx.classList.remove('prefy-content-fade-in');
      elx.classList.add('prefy-content-fade-out');
    });

    setTimeout(function () {
      if (isStaleTransition(mySeq, _transitionSeq)) return;
      renderContent(rendered);
      applyStateVisuals(_state.currentState);
      updatePanelVisibility();
      contentEls.forEach(function (elx) {
        elx.classList.remove('prefy-content-fade-out');
        elx.classList.add('prefy-content-fade-in');
      });

      setTimeout(function () {
        if (isStaleTransition(mySeq, _transitionSeq)) return;
        contentEls.forEach(function (elx) { elx.classList.remove('prefy-content-fade-in'); });
        playEntranceMotion(_state.currentState, mySeq);
      }, CONTENT_FADE_IN_MS);
    }, CONTENT_FADE_OUT_MS);
  }

  function setContext(contextKey, opts) {
    opts = opts || {};
    // Bumped unconditionally, even before the hasBrowser() early-return —
    // this counter tracks "which call is the latest legitimate one",
    // independent of whether there's a DOM to paint into right now.
    var mySeq = ++_transitionSeq;
    var entry = PrefyContent.getContext(contextKey);
    var effectiveKey = entry ? contextKey : PrefyContent.UNKNOWN_CONTEXT_KEY;
    var rendered = PrefyContent.render(contextKey, currentLang());
    var guard = guardState(rendered.state, _state.currentState, opts);

    // Only play the fade/entrance sequence for a GENUINE change — reduces
    // to an instant re-paint if called again with identical context+state
    // (e.g. a redundant setContext from a caller that doesn't itself
    // track "did this actually change"), never re-plays the entrance
    // motion pointlessly.
    var isRealChange = effectiveKey !== _state.currentContextKey || guard.state !== _state.currentState;

    _state.currentContextKey = effectiveKey;
    _state.currentState = guard.state;

    if (!hasBrowser()) return { applied: !guard.suppressed, state: guard.state, contextKey: effectiveKey };

    var seenBefore = hasSeen(effectiveKey);
    markSeen(effectiveKey);

    var minimizedPref = safeGet(STORAGE_KEY_MINIMIZED);
    if (opts.forceOpen) {
      _state.ui = 'open';
    } else if (shouldAutoOpen(PrefyContent.getContext(effectiveKey), seenBefore) && minimizedPref !== '1') {
      _state.ui = 'open';
    } else if (_state.ui !== 'open') {
      _state.ui = 'minimized';
    }
    transitionToRendered(rendered, mySeq, { skipAnimation: !isRealChange });
    return { applied: !guard.suppressed, state: guard.state, contextKey: effectiveKey };
  }

  function setState(state, content, opts) {
    opts = opts || {};
    var mySeq = ++_transitionSeq;
    var guard = guardState(state, _state.currentState, opts);
    _state.currentContextKey = null;
    _state.currentState = guard.state;
    if (!hasBrowser()) return { applied: !guard.suppressed, state: guard.state };
    if (opts.forceOpen) _state.ui = 'open';
    transitionToRendered({ title: (content && content.title) || '', body: (content && content.body) || '', why: content && content.why }, mySeq, {});
    return { applied: !guard.suppressed, state: guard.state };
  }

  function openHelp() {
    var mySeq = ++_transitionSeq;
    var lang = currentLang();
    var key = _state.currentContextKey || PrefyContent.UNKNOWN_CONTEXT_KEY;
    var rendered = PrefyContent.render(key, lang);
    var qa = [
      PrefyContent.str(lang, 'chrome.help.whereAmI') + ' ' + rendered.title,
      PrefyContent.str(lang, 'chrome.help.whatCanIDo') + ' ' + rendered.body,
    ];
    if (rendered.why) qa.push(PrefyContent.str(lang, 'chrome.help.why') + ' ' + rendered.why);
    qa.push(PrefyContent.str(lang, 'chrome.help.how') + ' ' + rendered.body);

    var guard = guardState('HELP', _state.currentState, {});
    _state.currentState = guard.state;
    if (!hasBrowser()) return { applied: true, state: guard.state, qa: qa };
    _state.ui = 'open';
    transitionToRendered({ title: PrefyContent.str(lang, 'chrome.name') + ' — ' + PrefyContent.str(lang, 'chrome.help'), body: qa.join(' ') }, mySeq, {});
    return { applied: true, state: guard.state, qa: qa };
  }

  function reopenCurrent() {
    if (!_state.currentContextKey) { open(); return; }
    setContext(_state.currentContextKey, { forceOpen: true });
  }

  function minimize() {
    _state.ui = nextUIState(_state.ui, 'minimize');
    safeSet(STORAGE_KEY_MINIMIZED, '1');
    render();
  }

  function open() {
    _state.ui = nextUIState(_state.ui, 'open');
    safeSet(STORAGE_KEY_MINIMIZED, '0');
    render();
    // Focus management: move focus into the panel ONLY on an explicit user
    // action (clicking the bubble / help button), never during an ordinary
    // contextual update (setContext never calls this) — no auto-focus
    // stealing while someone is mid-typing in a form field.
    if (hasBrowser() && _state.dom) {
      try { _state.dom.closeBtn.focus({ preventScroll: true }); } catch (e) { /* older WebView */ }
    }
  }

  function toggle() {
    _state.ui = nextUIState(_state.ui, 'toggle');
    safeSet(STORAGE_KEY_MINIMIZED, _state.ui === 'open' ? '0' : '1');
    render();
  }

  function onLangChange() {
    if (!_state.currentContextKey) return;
    var rendered = PrefyContent.render(_state.currentContextKey, currentLang());
    renderContent(rendered);
  }

  function init(opts) {
    opts = opts || {};
    if (!hasBrowser()) return;
    if (_state.initialized) return;
    var mount = function () {
      _state.dom = buildDom();
      (opts.mountTo || document.body).appendChild(_state.dom.root);
      if (prefersReducedMotion()) _state.dom.root.classList.add('prefy-reduced-motion');
      var minimizedPref = safeGet(STORAGE_KEY_MINIMIZED);
      _state.ui = minimizedPref === '0' ? 'open' : 'minimized';
      document.addEventListener('preferendum:langchange', onLangChange);
      _state.initialized = true;
      if (opts.initialContext) setContext(opts.initialContext);
      else render();
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mount);
    } else {
      mount();
    }
  }

  return {
    // Public API (per the Phase 1 spec)
    init: init,
    setContext: setContext,
    setState: setState,
    show: open,
    minimize: minimize,
    open: open,
    toggle: toggle,
    openHelp: openHelp,
    reopenCurrent: reopenCurrent,
    hasSeen: hasSeen,
    forgetContext: forgetContext,
    forgetAll: forgetAll,

    // Exposed for tests / advanced callers — pure, DOM-free
    guardState: guardState,
    nextUIState: nextUIState,
    shouldAutoOpen: shouldAutoOpen,
    storageKeySeen: storageKeySeen,
    STORAGE_KEY_MINIMIZED: STORAGE_KEY_MINIMIZED,

    // Motion (task: Prefy Motion & Interaction phase) — pure/DOM-free
    // pieces exposed for testing: the state→profile table (completeness
    // + no-security-state-motion-mapping-abuse checks) and the exact
    // race-condition guard every deferred transition step uses.
    STATE_MOTION: STATE_MOTION,
    isStaleTransition: isStaleTransition,
    prefersReducedMotion: prefersReducedMotion,

    // Introspection (tests, debugging) — never sensitive: state name and
    // context key strings only, never a user-data value.
    _debugState: function () { return { ui: _state.ui, currentContextKey: _state.currentContextKey, currentState: _state.currentState }; },
    _transitionSeqValue: function () { return _transitionSeq; },

    // Asset-failure fallback (task §13) — exposed so a test can force the
    // exact failure path (onAssetError) without needing a real browser
    // image-load event, and inspect whether the fallback badge is what's
    // actually showing afterward.
    _simulateAssetError: function (state) { onAssetError(state); },
    _hasAssetFallbackActive: function (state) { return !!_failedAssetStates[state]; },
    _resetAssetFailures: function () { _failedAssetStates = {}; },
  };
});
