/**
 * prefy-video.js — Prefy's HeyGen video-based presentation (Phase 1:
 * "welcome" context only). Product decision: replaces the paused CSS/PNG
 * + Web Speech engine (prefy.js/prefy-voice.js — kept in the repo for
 * history, no longer loaded by any portal). The HeyGen MP4 already
 * contains the animation, lip sync, and voice, so there is no
 * speechSynthesis call anywhere in this file.
 *
 * One MP4 per language, fetched only once the user actually opens Prefy
 * and taps play (preload="none") — never all 30 languages, never more
 * than the active one in flight.
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
  // (/prefy/video/{context}/{lang} — see main.py's PREFY_MEDIA_BASE_URL)
  // rather than any specific host/CDN, so the actual storage provider
  // can change without touching this file. Adding a future context
  // (registration, voting, ...) is a one-line addition here once real
  // files for it exist — never ahead of time.
  var CONTEXTS = {
    welcome: { urlPattern: '/prefy/video/welcome/{lang}' },
  };

  var ACTIVE_CONTEXT = 'welcome';
  var root, bubble, panel, video, playBtn, muteBtn;
  var isOpen = false;

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

    document.addEventListener('preferendum:langchange', onLangChange);
  }

  function open() {
    isOpen = true;
    panel.hidden = false;
    bubble.setAttribute('aria-expanded', 'true');
    if (!video.getAttribute('src')) {
      loadSource(ACTIVE_CONTEXT, currentLang());
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

  function show() {
    if (!root) mount();
    if (root) root.style.display = '';
  }

  function togglePlay() {
    if (!video) return;
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
    loadSource(ACTIVE_CONTEXT, lang);
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
