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
 *
 * PLAYBACK-RELIABILITY HARDENING (this revision) — root cause of "Prefy
 * starts talking and then stops" on a slow connection: a prior version
 * of this file called video.play() the instant the user tapped Play,
 * with no check that enough of the file had buffered. Fixed below with
 * an ADAPTIVE buffered-seconds-ahead gate: the required initial buffer
 * scales to the connection's own measured download rate (estimated
 * entirely from the <video> element's native buffered/currentTime
 * signals — no fetch(), no byte counting, no CORS dependency), between
 * a reasonable floor and a capped ceiling (dynamicInitialBufferTarget).
 * EVERY readiness-related event — progress, canplaythrough, canplay —
 * funnels through that one same check (sufficientlyBuffered); none of
 * them, including canplaythrough, has an independent "good enough, play
 * now" path of its own, so no single event can authorize playback while
 * the adaptive target hasn't actually been reached. Separately, real
 * handling of a mid-playback stall (waiting/stalled) pauses, shows a
 * clear "buffering" state, and either auto-resumes once re-buffered or
 * — after repeated stalls on a genuinely bad connection — stops
 * auto-retrying and asks for an explicit tap, rather than visibly
 * starting and stopping on a loop.
 *
 * DELIBERATELY NOT DONE (simplification, 2026) — an earlier revision of
 * this file also fetch()'d the full file into an IndexedDB cache for
 * instant replay on a later visit. Measured against the real production
 * S3 objects: the welcome video is ~158MB and the campaign video is
 * ~172MB PER LANGUAGE, and the S3 bucket currently has no CORS
 * configuration (fetch() can't read the bytes anyway). Rather than
 * depend on an S3 configuration change, or risk Preferendum ever
 * downloading a SECOND full 150-180MB copy of the same file in the
 * background, that caching layer was removed entirely. Playback is
 * native progressive streaming only (unchanged from the original
 * design — S3 already supports Range requests, Render never proxies
 * the bytes), which needs no CORS and never re-fetches more than once
 * per context+language per page session (loadedContext/loadedLang
 * below).
 */
(function () {
  'use strict';

  // urlPattern points at the backend's storage-abstracted route
  // (/prefy/video/{context}/{lang} — see main.py's S3/GitHub/local-disk
  // precedence) rather than any specific host/CDN, so the actual storage
  // provider can change without touching this file. Adding a future
  // context (registration, voting, ...) is a one-line addition here once
  // real files for it exist — never ahead of time. poster is a STATIC
  // image already in the repo (assets/prefy/*.png) shown in the <video>
  // element before anything has loaded, and again whenever a source is
  // swapped — the user always sees Prefy, never a blank/black box.
  var CONTEXTS = {
    welcome:  { urlPattern: '/prefy/video/welcome/{lang}', poster: '/assets/prefy/prefy-welcome.png' },
    campaign: { urlPattern: '/prefy/video/campaign/{lang}', poster: '/assets/prefy/prefy-presenting.png' },
  };

  var ACTIVE_CONTEXT = 'welcome';
  var root, bubble, panel, video, playBtn, muteBtn, loadingOverlay, progressFill, progressLabel, connNotice;
  var isOpen = false;
  // What's actually loaded into the <video> element right now — distinct
  // from ACTIVE_CONTEXT (which screen wants Prefy visible). Only these
  // two changing is what should ever trigger a new fetch.
  var loadedContext = null, loadedLang = null;
  // Whether playback has actually started (the 'playing' event fired)
  // for the CURRENTLY loaded source. Used only to decide, on close(),
  // whether it's safe/worthwhile to abort the in-flight network request
  // (nothing watched yet -> abort, don't waste a 150-180MB download on a
  // hidden panel) versus merely pausing (already playing -> keep the
  // buffered data, resume exactly where left off on reopen).
  var playbackStarted = false;

  // ── Play-readiness gating (fixes "talks then stops") ────────────────
  // pendingPlayToken invalidates any in-flight wait the moment a newer
  // one starts (new source, retry, or the panel closing) — the only
  // mechanism needed to avoid stacking up stale timers/listeners; every
  // callback checks its own captured token first.
  var pendingPlayToken = 0;
  var playReadyTimeoutId = null;
  var PLAY_READY_TIMEOUT_MS = 20000;       // genuinely stalled connection fallback (initial wait)
  var MIN_INITIAL_BUFFER_SECONDS = 3;      // reasonable floor regardless of connection speed
  var MAX_INITIAL_BUFFER_SECONDS = 12;     // cap — a very slow connection still falls back to the
                                            // 20s timeout above rather than being asked to wait longer
  var MIN_REBUFFER_SECONDS = 2;            // seconds required to resume after a MID-playback stall

  // ── Adaptive initial-buffer target ───────────────────────────────────
  // Measures "seconds of video buffered per second of real time elapsed"
  // since buffering actively started — this IS the download-rate-
  // relative-to-playback-rate ratio, derived ENTIRELY from the <video>
  // element's own native buffered/currentTime signals, with no fetch(),
  // no byte counting, and therefore no CORS dependency whatsoever. A
  // ratio >= 1 means the connection downloads at or faster than
  // real-time playback consumes it — the reasonable floor
  // (MIN_INITIAL_BUFFER_SECONDS) is enough, since the buffer will keep
  // growing during playback. A ratio below 1 means the download is
  // slower than real-time — the target scales UP so there is enough
  // runway banked before playback could catch up to and pass the
  // download, capped at MAX_INITIAL_BUFFER_SECONDS so this never turns
  // into an extreme wait on its own (the 20s absolute timeout is the
  // final backstop regardless of what this function computes).
  var _bufRateStartWallMs = null;
  var _bufRateStartBufferedSec = 0;

  function startBufferRateMeasurement() {
    _bufRateStartWallMs = Date.now();
    _bufRateStartBufferedSec = bufferedAheadSeconds();
  }

  function estimatedDownloadToPlaybackRatio() {
    if (_bufRateStartWallMs === null) return null;
    var wallElapsedSec = (Date.now() - _bufRateStartWallMs) / 1000;
    if (wallElapsedSec < 0.5) return null; // too little data yet for a meaningful estimate
    var bufferedGained = bufferedAheadSeconds() - _bufRateStartBufferedSec;
    if (bufferedGained < 0) bufferedGained = 0;
    return bufferedGained / wallElapsedSec;
  }

  function dynamicInitialBufferTarget() {
    var ratio = estimatedDownloadToPlaybackRatio();
    if (ratio === null || ratio <= 0) return MIN_INITIAL_BUFFER_SECONDS; // not enough data yet — use the floor
    if (ratio >= 1) return MIN_INITIAL_BUFFER_SECONDS;
    return Math.min(MIN_INITIAL_BUFFER_SECONDS / ratio, MAX_INITIAL_BUFFER_SECONDS);
  }

  // ── Mid-playback stall tracking ──────────────────────────────────────
  // A connection that degrades after playback already started triggers
  // 'waiting'/'stalled'. Auto-pause + auto-resume once re-buffered is the
  // right response to an occasional blip, but doing that forever on a
  // connection that is simply too slow would look exactly like the
  // original "starts and stops repeatedly" complaint, just automated.
  // stallCount caps that: after MAX_STALL_RETRIES consecutive stalls
  // (never separated by a sustained stretch of smooth playback — see
  // scheduleStallCountReset) auto-resume stops and the player asks for
  // an explicit tap instead of looping.
  var stallCount = 0;
  var MAX_STALL_RETRIES = 3;
  var stallResetTimerId = null;
  var isRebuffering = false;

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

  function posterFor(context) {
    var ctx = CONTEXTS[context];
    return ctx ? ctx.poster : '';
  }

  // Seconds of CONTIGUOUS buffered video ahead of the current playback
  // position — the "segundos disponibles" signal the gate is built on,
  // not a bare boolean. Falls back to 0 on any platform quirk (some
  // WebViews expose an empty/irregular TimeRanges object) rather than
  // throwing, so a gating decision never crashes the player.
  function bufferedAheadSeconds() {
    try {
      if (!video || !video.buffered || !video.buffered.length) return 0;
      var t = video.currentTime || 0;
      for (var i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= t + 0.1 && t < video.buffered.end(i)) {
          return video.buffered.end(i) - t;
        }
      }
      return 0;
    } catch (e) { return 0; }
  }

  function cancelPendingPlayWait() {
    pendingPlayToken++; // invalidates any in-flight onReady/onError/timeout for a prior wait
    if (playReadyTimeoutId) { clearTimeout(playReadyTimeoutId); playReadyTimeoutId = null; }
    if (playBtn) playBtn.disabled = false;
    hideLoadingOverlay();
    hideSlowConnectionNotice();
    isRebuffering = false;
  }

  function showLoadingOverlay() { if (loadingOverlay) loadingOverlay.hidden = false; updateProgressUI(); }
  function hideLoadingOverlay() { if (loadingOverlay) loadingOverlay.hidden = true; }
  function showSlowConnectionNotice() { if (connNotice) connNotice.hidden = false; }
  function hideSlowConnectionNotice() { if (connNotice) connNotice.hidden = true; }

  function updateProgressUI() {
    if (!progressFill || !video) return;
    var pct = 0;
    try {
      if (video.duration && !isNaN(video.duration) && video.duration > 0 &&
          video.buffered && video.buffered.length) {
        var bufferedEnd = video.buffered.end(video.buffered.length - 1);
        pct = Math.max(0, Math.min(100, Math.round((bufferedEnd / video.duration) * 100)));
      }
    } catch (e) { pct = 0; }
    progressFill.style.width = pct + '%';
    if (progressLabel) progressLabel.textContent = pct + '%';
  }

  // Loads a source into the <video> element — pure native streaming, no
  // caching layer. Cancels any pending play-wait for the PREVIOUS
  // source, resets playback UI and stall tracking to idle, and assigns
  // the live network URL. preload stays "none" here (unchanged default)
  // — the browser does not actually start fetching until something
  // requires data, which is the point where waitUntilBufferedThenPlay
  // below sets preload="auto".
  function loadSource(context, lang) {
    if (!video) return;
    var url = videoUrlFor(context, lang);
    if (!url) return;
    cancelPendingPlayWait();
    video.pause();
    setPlayLabel(false);
    if (playBtn) playBtn.textContent = '▶ Play';
    stallCount = 0;
    if (stallResetTimerId) { clearTimeout(stallResetTimerId); stallResetTimerId = null; }
    playbackStarted = false;

    video.poster = posterFor(context);
    video.src = url; // preload="none" — this does not fetch the file yet
    video.load();     // resets element state to the new source, still no fetch

    loadedContext = context;
    loadedLang = lang;
  }

  // True only when the video element would need a different source than
  // what's already loaded — the single idempotency check every caller
  // below goes through, so "already showing this context+language" never
  // re-triggers a fetch of a (possibly 150-180MB) file.
  function needsReload(context, lang) {
    return context !== loadedContext || lang !== loadedLang;
  }

  function setPlayLabel(playing) {
    if (playBtn) playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
  }

  // Waits for a MINIMUM amount of actual buffered playback time — an
  // ADAPTIVE target (see dynamicInitialBufferTarget above), never a
  // single fixed number and never solely the browser's canplaythrough
  // heuristic — before calling video.play() for the FIRST time on this
  // source.
  //
  // Every readiness-related event (progress, canplaythrough, canplay)
  // funnels through the exact SAME check — sufficientlyBuffered() below
  // — rather than any one of them independently authorizing play(). This
  // is deliberate: a bare canplaythrough (or canplay) no longer has its
  // own unconditional "good enough, play now" branch, so there is
  // exactly one place in the whole file that decides whether enough
  // content is actually loaded, and no event can bypass it.
  //
  // A bounded timeout is the fallback for a genuinely stalled
  // connection: play anyway, with a visible notice, rather than leaving
  // the user stuck forever on a loading spinner.
  function waitUntilBufferedThenPlay() {
    var myToken = ++pendingPlayToken;
    startBufferRateMeasurement();

    function sufficientlyBuffered() {
      return video.readyState >= 4 /* HAVE_ENOUGH_DATA */ ||
             bufferedAheadSeconds() >= dynamicInitialBufferTarget();
    }

    if (sufficientlyBuffered()) {
      video.play().catch(function () {});
      return;
    }

    showLoadingOverlay();
    if (playBtn) { playBtn.disabled = true; playBtn.textContent = '⏳ Cargando…'; }
    video.preload = 'auto'; // only now actively ask the browser to buffer ahead

    function finish(outcome) {
      if (myToken !== pendingPlayToken) return; // superseded — a newer load/cancel already ran
      if (playReadyTimeoutId) { clearTimeout(playReadyTimeoutId); playReadyTimeoutId = null; }
      video.removeEventListener('progress', onCheck);
      video.removeEventListener('canplaythrough', onCheck);
      video.removeEventListener('canplay', onCheck);
      video.removeEventListener('error', onErr);
      if (playBtn) playBtn.disabled = false;
      hideLoadingOverlay();
      if (outcome === 'ready' || outcome === 'slow') {
        if (outcome === 'slow') showSlowConnectionNotice();
        video.play().catch(function () {});
      } else {
        setPlayLabel(false);
      }
    }
    // Re-checks the SAME single gate on every candidate signal — none of
    // them (including canplaythrough/canplay) ever skips straight to
    // finish('ready') on their own.
    function onCheck() { updateProgressUI(); if (sufficientlyBuffered()) finish('ready'); }
    function onErr() { finish('error'); if (playBtn) playBtn.textContent = '⚠ Retry'; }

    video.addEventListener('progress', onCheck);
    video.addEventListener('canplaythrough', onCheck);
    video.addEventListener('canplay', onCheck);
    video.addEventListener('error', onErr);
    playReadyTimeoutId = setTimeout(function () { finish('slow'); }, PLAY_READY_TIMEOUT_MS);
  }

  // A connection that degrades AFTER playback already started. Pauses
  // explicitly, shows the same loading overlay + slow-connection notice,
  // and waits for a smaller re-buffer threshold before resuming — unless
  // this has already happened MAX_STALL_RETRIES times in a row without a
  // sustained smooth stretch in between, in which case it stops
  // auto-retrying and leaves the player paused with a manual "retry"
  // state instead of visibly looping forever.
  function handleStall() {
    if (!video) return;
    // A real, user-initiated pause (not a stall) must never be treated
    // as a stall — 'waiting' can fire spuriously right after an
    // explicit pause() on some engines.
    if (video.paused && !isRebuffering) return;
    if (isRebuffering) return;
    isRebuffering = true;
    stallCount++;
    if (stallResetTimerId) { clearTimeout(stallResetTimerId); stallResetTimerId = null; }

    if (stallCount > MAX_STALL_RETRIES) {
      isRebuffering = false;
      video.pause();
      hideLoadingOverlay();
      showSlowConnectionNotice();
      if (playBtn) { playBtn.disabled = false; playBtn.textContent = '⚠ Reintentar'; }
      return;
    }

    showLoadingOverlay();
    showSlowConnectionNotice();
    var myToken = ++pendingPlayToken;
    function onResumeProgress() {
      if (myToken !== pendingPlayToken) return;
      updateProgressUI();
      if (bufferedAheadSeconds() >= MIN_REBUFFER_SECONDS || video.readyState >= 3) {
        video.removeEventListener('progress', onResumeProgress);
        video.removeEventListener('canplay', onResumeProgress);
        isRebuffering = false;
        hideLoadingOverlay();
        video.play().catch(function () {});
      }
    }
    video.addEventListener('progress', onResumeProgress);
    video.addEventListener('canplay', onResumeProgress);
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
    video.poster = posterFor(ACTIVE_CONTEXT);
    stage.appendChild(video);

    // Loading overlay — static Prefy poster already shows via the
    // <video poster> attribute underneath; this adds a progress bar +
    // percentage on top of it, visible only while actively buffering
    // toward a play attempt or re-buffering after a stall (not merely
    // while the panel is open and idle).
    loadingOverlay = document.createElement('div');
    loadingOverlay.className = 'prefy-video-loading';
    loadingOverlay.hidden = true;
    var spinner = document.createElement('div');
    spinner.className = 'prefy-video-spinner';
    var progressTrack = document.createElement('div');
    progressTrack.className = 'prefy-video-progress-track';
    progressFill = document.createElement('div');
    progressFill.className = 'prefy-video-progress-fill';
    progressTrack.appendChild(progressFill);
    progressLabel = document.createElement('span');
    progressLabel.className = 'prefy-video-progress-label';
    progressLabel.textContent = '0%';
    loadingOverlay.appendChild(spinner);
    loadingOverlay.appendChild(progressTrack);
    loadingOverlay.appendChild(progressLabel);
    stage.appendChild(loadingOverlay);

    connNotice = document.createElement('div');
    connNotice.className = 'prefy-video-conn-notice';
    connNotice.hidden = true;
    connNotice.textContent = 'Conexión lenta — la reproducción podría pausar brevemente.';
    stage.appendChild(connNotice);

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
    video.addEventListener('playing', function () {
      setPlayLabel(true);
      playbackStarted = true;
      hideSlowConnectionNotice();
      hideLoadingOverlay();
      // Only reset the stall counter after a SUSTAINED stretch of smooth
      // playback (5s with no further 'waiting') — an immediate reset on
      // every 'playing' would let a connection that stalls every couple
      // of seconds dodge the MAX_STALL_RETRIES cap forever, recreating
      // exactly the start/stop loop this is meant to prevent.
      if (stallResetTimerId) clearTimeout(stallResetTimerId);
      stallResetTimerId = setTimeout(function () { stallCount = 0; }, 5000);
    });
    video.addEventListener('pause', function () { if (!video.ended) setPlayLabel(false); });
    video.addEventListener('progress', updateProgressUI);
    // Mid-playback stall despite the initial buffer gate — a connection
    // that degrades AFTER playback already started. 'waiting': playback
    // paused itself because it ran out of buffered data. 'stalled': the
    // browser expected more data and none arrived. Both are handled the
    // same way.
    video.addEventListener('waiting', handleStall);
    video.addEventListener('stalled', handleStall);
    // A failed load (bad URL, network error, access denied, ...) must
    // never leave the player silently black forever — small, isolated
    // safeguard: reuse the same plain hardcoded-label convention already
    // used for Play/Mute/Replay above (this player has no localized
    // strings today, so this introduces no new i18n gap), and let the
    // same tap that shows "Retry" actually retry.
    video.addEventListener('error', function () {
      cancelPendingPlayWait();
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
    // Closing mid-download/mid-wait must not leave a background timer
    // that later calls play() on a hidden panel, nor a stuck "Cargando…"
    // state the next time it's opened.
    cancelPendingPlayWait();
    if (video) {
      video.pause();
      if (!playbackStarted) {
        // Nothing has actually been watched yet on this source (still
        // buffering toward the initial threshold, or the panel was
        // closed before Play was even tapped) — abort the in-flight
        // network request rather than let a 150-180MB file keep
        // downloading in the background behind a hidden panel.
        // Reopening starts a fresh request, which is the right
        // trade-off: there is no buffered progress worth preserving.
        try { video.removeAttribute('src'); video.load(); } catch (e) {}
        loadedContext = null;
        loadedLang = null;
      }
      // If playback HAD already started, loadedContext/loadedLang are
      // left as-is on purpose: reopening resumes the same (already
      // partly or fully buffered) source exactly where it was left,
      // paused — no unnecessary re-request.
    }
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
      waitUntilBufferedThenPlay();
      return;
    }
    if (video.paused || video.ended) {
      if (video.ended) video.currentTime = 0;
      waitUntilBufferedThenPlay();
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
