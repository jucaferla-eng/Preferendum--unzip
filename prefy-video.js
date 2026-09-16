/**
 * prefy-video.js — Prefy's HeyGen video-based presentation. Two approved
 * contexts today: "welcome" (root landing page only) and "campaign"
 * (marketer_portal.html's Campaigns workflow only) — each a completely
 * separate page load, so only one context is ever active per document,
 * but the catalog/API stay context-generic. Product decision: replaces
 * the paused CSS/PNG + Web Speech engine (prefy.js/prefy-voice.js — kept
 * in the repo for history, no longer loaded by any portal). The HeyGen
 * MP4 already contains the animation, lip sync, and voice, so there is
 * no speechSynthesis call anywhere in this file.
 *
 * One MP4 per language, fetched only once the user actually opens Prefy
 * and taps play (preload="none") — never all 30 languages, never more
 * than the active one in flight. Switching between screens that share
 * the same context+language (e.g. campaigns -> new-campaign ->
 * deployment, all "campaign") never re-fetches — see loadedContext/
 * loadedLang below.
 *
 * Language comes from the SAME resolver every other Preferendum surface
 * uses (window.PreferendumLang.currentLanguage(), see lang.js) and the
 * SAME 'preferendum:langchange' document event lang.js already
 * dispatches on every explicit language change — no second language
 * system.
 *
 * Context catalog is a flat map so a future context (registration,
 * occupation, company-size, date-of-birth, consultations, voting,
 * results, ...) is a one-line addition here, not a player rewrite.
 */
(function () {
  'use strict';

  // urlPattern points at the backend's storage-abstracted route
  // (/prefy/video/{context}/{lang} — see main.py's S3/GitHub/local-disk
  // precedence) rather than any specific host/CDN, so the actual storage
  // provider can change without touching this file. Adding a future
  // context (registration, voting, ...) is a one-line addition here once
  // real files for it exist — never ahead of time.
  var CONTEXTS = {
    welcome:  { urlPattern: '/prefy/video/welcome/{lang}' },
    campaign: { urlPattern: '/prefy/video/campaign/{lang}' },
  };

  var ACTIVE_CONTEXT = 'welcome';
  var root, bubble, panel, video, playBtn, muteBtn;
  var isOpen = false;
  // What's actually loaded into the <video> element right now — distinct
  // from ACTIVE_CONTEXT (which screen wants Prefy visible). Only these
  // two changing is what should ever trigger a new fetch.
  var loadedContext = null, loadedLang = null;

  function currentLang() {
    try {
      if (window.PreferendumLang && typeof window.PreferendumLang.currentLanguage === 'function') {
        return window.PreferendumLang.currentLanguage() || 'es';
      }
    } catch (e) { /* fall through to the document-level hint below */ }
    return (document.documentElement.getAttribute('lang') || 'es').split(/[-_]/)[0];
  }

  function videoUrlFor(context, lang) {
    var ctx = CONTEXTS[context];
    if (!ctx) return null;
    return ctx.urlPattern.replace('{lang}', lang);
  }

  function loadSource(context, lang) {
    var url = videoUrlFor(context, lang);
    if (!url || !video) return;
    video.pause();
    video.src = url; // preload="none" — this does not fetch the file yet
    video.load();     // resets element state to the new source, still no fetch
    setPlayLabel(false);
    loadedContext = context;
    loadedLang = lang;
  }

  // True only when the video element would need a different source than
  // what's already loaded — the single idempotency check every caller
  // below goes through, so "already showing this context+language" never
  // re-triggers a fetch of a (possibly 100MB+) file.
  function needsReload(context, lang) {
    return context !== loadedContext || lang !== loadedLang;
  }

  function setPlayLabel(playing) {
    if (playBtn) playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
  }

  function build() {
    root = document.createElement('div');
    root.className = 'prefy-video-root';

    bubble = document.createElement('button');
    bubble.type = 'button';
    bubble.className = 'prefy-video-bubble';
    bubble.setAttribute('aria-label', 'Prefy');
    var img = document.createElement('img');
    img.src = '/assets/prefy/prefy-welcome.png';
    img.alt = 'Prefy';
    bubble.appendChild(img);
    bubble.addEventListener('click', open);

    panel = document.createElement('div');
    panel.className = 'prefy-video-panel';
    panel.hidden = true;

    var header = document.createElement('div');
    header.className = 'prefy-video-header';
    var title = document.createElement('span');
    title.className = 'prefy-video-title';
    title.textContent = 'Prefy';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'prefy-video-close';
    closeBtn.setAttribute('aria-label', 'Minimize');
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', close);
    header.appendChild(title);
    header.appendChild(closeBtn);

    var stage = document.createElement('div');
    stage.className = 'prefy-video-stage';
    video = document.createElement('video');
    video.className = 'prefy-video-el';
    video.setAttribute('playsinline', '');
    video.setAttribute('webkit-playsinline', '');
    video.preload = 'none';
    video.controls = false;
    stage.appendChild(video);

    var controls = document.createElement('div');
    controls.className = 'prefy-video-controls';
    playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.className = 'prefy-video-btn prefy-video-play';
    setPlayLabel(false);
    playBtn.addEventListener('click', togglePlay);
    muteBtn = document.createElement('button');
    muteBtn.type = 'button';
    muteBtn.className = 'prefy-video-btn prefy-video-mute';
    muteBtn.textContent = '🔊 Mute';
    muteBtn.addEventListener('click', toggleMute);
    controls.appendChild(playBtn);
    controls.appendChild(muteBtn);

    panel.appendChild(header);
    panel.appendChild(stage);
    panel.appendChild(controls);

    root.appendChild(panel);
    root.appendChild(bubble);
    document.body.appendChild(root);

    video.addEventListener('ended', function () { setPlayLabel(false); playBtn.textContent = '↻ Replay'; });
    video.addEventListener('play', function () { setPlayLabel(true); });
    video.addEventListener('pause', function () { if (!video.ended) setPlayLabel(false); });
    // A failed load (bad URL, network error, access denied, ...) must
    // never leave the player silently black forever — small, isolated
    // safeguard: reuse the same plain hardcoded-label convention already
    // used for Play/Mute/Replay above (this player has no localized
    // strings today, so this introduces no new i18n gap), and let the
    // same tap that shows "Retry" actually retry.
    video.addEventListener('error', function () {
      setPlayLabel(false);
      playBtn.textContent = '⚠ Retry';
    });

    document.addEventListener('preferendum:langchange', onLangChange);
  }

  function open() {
    isOpen = true;
    panel.hidden = false;
    bubble.setAttribute('aria-expanded', 'true');
    var lang = currentLang();
    if (needsReload(ACTIVE_CONTEXT, lang)) {
      loadSource(ACTIVE_CONTEXT, lang);
    }
  }

  function close() {
    isOpen = false;
    panel.hidden = true;
    bubble.setAttribute('aria-expanded', 'false');
    if (video) video.pause();
  }

  // hide()/show() remove the ENTIRE widget (bubble included, not just the
  // panel) — for a host page where Prefy is only supposed to exist on one
  // screen/section of a single-page flow (e.g. a landing page's "concept"
  // step, gone once the visitor moves past it). close() alone isn't
  // enough for that: it collapses the panel but leaves the bubble
  // visible. hide() also guarantees no audio/video keeps running once
  // Prefy is supposed to be gone.
  function hide() {
    close();
    if (root) root.style.display = 'none';
  }

  function show(context) {
    if (context) ACTIVE_CONTEXT = context;
    if (!root) mount();
    if (root) root.style.display = '';
    // Only reload if the panel is already open AND the context actually
    // changed since what's loaded — covers a host page that keeps Prefy
    // open across a context switch. The common case (panel closed,
    // switching between screens that share the same context, e.g.
    // campaigns -> new-campaign -> deployment) never touches the network
    // here at all — loading stays deferred to the next open() tap.
    if (isOpen && video) {
      var lang = currentLang();
      if (needsReload(ACTIVE_CONTEXT, lang)) {
        loadSource(ACTIVE_CONTEXT, lang);
      }
    }
  }

  function togglePlay() {
    if (!video) return;
    if (video.error) {
      // Retry: force a genuine reload (a plain video.play() retry does
      // nothing useful once the element is in an error state) of the
      // SAME context/language that failed — not a different one.
      loadedContext = null;
      loadedLang = null;
      loadSource(ACTIVE_CONTEXT, currentLang());
      video.play().catch(function () { /* still may need another user tap on some browsers — no-op */ });
      return;
    }
    if (video.paused || video.ended) {
      if (video.ended) video.currentTime = 0;
      video.play().catch(function () { /* blocked without a user gesture — button click IS the gesture, so this is only a defensive no-op */ });
    } else {
      video.pause();
    }
  }

  function toggleMute() {
    if (!video) return;
    video.muted = !video.muted;
    muteBtn.textContent = video.muted ? '🔇 Unmute' : '🔊 Mute';
  }

  function onLangChange(e) {
    var lang = (e && e.detail && e.detail.lang) || currentLang();
    if (needsReload(ACTIVE_CONTEXT, lang)) {
      loadSource(ACTIVE_CONTEXT, lang);
    }
  }

  function mount() {
    if (root) return; // idempotent — never build a second player instance
    build();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  window.PrefyVideo = { open: open, close: close, mount: mount, hide: hide, show: show };
})();
