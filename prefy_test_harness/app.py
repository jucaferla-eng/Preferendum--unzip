"""
prefy_test_harness/app.py — a MINIMAL, standalone service whose only job
is to exercise the real Prefy video player (prefy-video.js/css) against
the real S3 videos, for manual testing on a real browser/iPhone/Android,
completely isolated from the production Preferendum backend.

Deliberately NOT a copy of main.py and NOT a trimmed-down version of it.
It is a brand-new, ~100-line app with exactly four routes:

    GET /                           a bare HTML page that loads the
                                     player, identical in spirit to how
                                     the real root page embeds it
    GET /prefy-video.js             serves the REAL file from the repo
    GET /prefy-video.css            serves the REAL file from the repo
    GET /assets/prefy/{filename}    serves the REAL poster images
    GET /prefy/video/{context}/{lang}
                                     THE ONE piece of backend logic that
                                     matters for this test: resolves a
                                     presigned S3 GetObject URL from the
                                     same literal, verified key tables
                                     main.py uses, and 302-redirects to
                                     it. Read-only GetObject against the
                                     existing bucket — never writes,
                                     renames, or re-uploads anything.

No database. No boto3-adjacent services besides S3. No dependency on
main.py at import time (this file is fully self-contained) — if
main.py's key tables are ever edited, this file's copies must be
updated by hand; that trade-off is deliberate for a short-lived,
throwaway test harness, not a permanent second source of truth.

File paths are resolved relative to THIS file's own location, then
walked up one directory to the repo root — this makes the app work
correctly regardless of Render's configured working directory, without
duplicating prefy-video.js/css or the poster PNGs into this folder.

ACCESS CONTROL — a Render free-tier service gets a public, guessable-
pattern *.onrender.com URL with no built-in access restriction. Every
route below (including the video redirect) requires HTTP Basic Auth,
checked against HARNESS_BASIC_AUTH_USER/HARNESS_BASIC_AUTH_PASSWORD —
two NEW env vars, specific to this throwaway service, never shared with
or derived from production credentials. If either is left unset, the
app refuses to start serving (fails closed, not open) rather than
silently running unprotected.
"""
import hmac
import os
from pathlib import Path

import boto3
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

_security = HTTPBasic()
_BASIC_AUTH_USER = os.getenv('HARNESS_BASIC_AUTH_USER', '')
_BASIC_AUTH_PASSWORD = os.getenv('HARNESS_BASIC_AUTH_PASSWORD', '')


def require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    # hmac.compare_digest — constant-time comparison, avoids a timing
    # side-channel on the password check. Fails closed: if the two env
    # vars above were never set, no username/password can ever match
    # empty strings against a real client-supplied value (a non-empty
    # Basic Auth header never equals '').
    user_ok = hmac.compare_digest(credentials.username, _BASIC_AUTH_USER)
    pass_ok = hmac.compare_digest(credentials.password, _BASIC_AUTH_PASSWORD)
    if not (_BASIC_AUTH_USER and _BASIC_AUTH_PASSWORD and user_ok and pass_ok):
        raise HTTPException(401, 'Unauthorized', headers={'WWW-Authenticate': 'Basic'})


# Applied at the APP level (dependencies=[...]), not per-route — every
# current and future route requires auth automatically; there is no way
# to add a new route here and accidentally forget to protect it.
app = FastAPI(dependencies=[Depends(require_auth)])

# ── S3 config — deliberately isolated env var names, matching main.py's
# naming exactly so the SAME values can be reused, but configured
# separately on THIS service in Render (never inherited from, or shared
# with, the production service's environment). ──────────────────────────
PREFY_AWS_ACCESS_KEY_ID = os.getenv('PREFY_AWS_ACCESS_KEY_ID', '')
PREFY_AWS_SECRET_ACCESS_KEY = os.getenv('PREFY_AWS_SECRET_ACCESS_KEY', '')
PREFY_AWS_REGION = os.getenv('PREFY_AWS_REGION', 'us-east-1')
PREFY_MEDIA_S3_BUCKET = os.getenv('PREFY_MEDIA_S3_BUCKET', 'preferendum-prefy')
_PRESIGN_EXPIRES_SECONDS = 3600

# Literal, verified object keys — copied from main.py's own
# PREFY_WELCOME_S3_KEY_BY_LANG / PREFY_CAMPAIGN_S3_KEY_BY_LANG. Never
# computed from a pattern; never edited here without re-checking against
# the real `aws s3 ls --recursive` listing main.py's own comment
# describes, for the same byte-exact-Unicode-normalization reasons
# documented there.
_WELCOME_PREFIX = 'prefy/welcome/heygen_project 3/'
WELCOME_KEY_BY_LANG = {
    'fil': _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_-fil/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'es':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_-sp/Prefy_bienvenida_en_app_Preferendum_version_3.mp4',
    'cs':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-cs/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'da':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-da/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'el':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-el/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'fi':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-fi/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ro':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-ro/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'sv':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-sv/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'uk':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_0-uk/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ar':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_2-ar/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ja':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_2-ja/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ko':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_2-ko/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ru':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_2-ru/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'vi':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_3-vi/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'hi':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_9-hi/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'id':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_9-id/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'nl':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_9-nl/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'pl':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_9-pl/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'tr':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_9-tr/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'fa':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_a-IR/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'de':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_c-de/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'en':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_c-en/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'fr':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_c-fr/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'it':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_c-it/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'pt':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_c-pt/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'he':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_e-IL/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'zh':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_h-CN/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'th':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_h-TH/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'bn':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_n-IN/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
    'ur':  _WELCOME_PREFIX + 'Prefy_bienvenida_en_app_Preferendum_version_3_r-IN/Prefy_bienvenida_en_app_Preferendum_vers.mp4',
}

_CAMPAIGN_PREFIX = 'prefy/Campaña /heygen_project/'
CAMPAIGN_KEY_BY_LANG = {
    'fil': _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_-fil/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ar':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-ar/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'hi':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-hi/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'id':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-id/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ja':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-ja/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ko':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-ko/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'nl':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-nl/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'pl':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-pl/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ru':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-ru/Guia_del_area_de_campanas_de_Preferendum.mp4',
    # BYTE-EXACT — see main.py's PREFY_CAMPAIGN_S3_KEY_BY_LANG comment:
    # this key's accented letters are base+combining-accent, not
    # precomposed. Copy verbatim; do not retype by hand.
    'es':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-sp/Guía del área de campañas de Preferendum_1080p 4.mp4',
    'tr':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-tr/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'vi':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_0-vi/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'da':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-da/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'de':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-de/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'el':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-el/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'en':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-en/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'fi':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-fi/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'fr':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-fr/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'it':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-it/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'sv':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_6-sv/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'cs':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_9-cs/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ro':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_9-ro/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'uk':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_9-uk/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'fa':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_a-IR/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'he':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_e-IL/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'zh':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_h-CN/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'th':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_h-TH/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'bn':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_n-IN/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'ur':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_r-IN/Guia_del_area_de_campanas_de_Preferendum.mp4',
    'pt':  _CAMPAIGN_PREFIX + 'Guia_del_area_de_campanas_de_Preferendum_1080_t-BR/Guia_del_area_de_campanas_de_Preferendum.mp4',
}

_KEY_TABLES = {'welcome': WELCOME_KEY_BY_LANG, 'campaign': CAMPAIGN_KEY_BY_LANG}
_VALID_CONTEXTS = frozenset(_KEY_TABLES.keys())
_VALID_LANGS = frozenset({
    'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
    'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
    'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
})

_s3_client_cache = None


def _s3_client():
    global _s3_client_cache
    if not (PREFY_AWS_ACCESS_KEY_ID and PREFY_AWS_SECRET_ACCESS_KEY):
        return None
    if _s3_client_cache is None:
        _s3_client_cache = boto3.client(
            's3', region_name=PREFY_AWS_REGION,
            aws_access_key_id=PREFY_AWS_ACCESS_KEY_ID,
            aws_secret_access_key=PREFY_AWS_SECRET_ACCESS_KEY,
        )
    return _s3_client_cache


@app.get('/prefy-video.js')
def serve_js():
    content = (REPO_ROOT / 'prefy-video.js').read_text(encoding='utf-8')
    return Response(content=content, media_type='application/javascript')


@app.get('/prefy-video.css')
def serve_css():
    content = (REPO_ROOT / 'prefy-video.css').read_text(encoding='utf-8')
    return Response(content=content, media_type='text/css')


_ASSET_FILENAMES = frozenset({'prefy-welcome.png', 'prefy-presenting.png'})


@app.get('/assets/prefy/{filename}')
def serve_asset(filename: str):
    if filename not in _ASSET_FILENAMES:
        raise HTTPException(404, 'Not found')
    path = REPO_ROOT / 'assets' / 'prefy' / filename
    if not path.is_file():
        raise HTTPException(404, 'Not found')
    return Response(content=path.read_bytes(), media_type='image/png')


@app.get('/prefy/video/{context}/{lang}')
def serve_prefy_video(context: str, lang: str, range: Optional[str] = Header(None)):
    """The one real piece of backend logic under test: resolve a
    presigned, read-only S3 GetObject URL and 302-redirect to it —
    identical in behavior to main.py's own route. Never writes, renames,
    or re-uploads anything in the bucket."""
    if context not in _VALID_CONTEXTS or lang not in _VALID_LANGS:
        raise HTTPException(404, 'Not found')
    key = _KEY_TABLES[context].get(lang)
    if not key:
        raise HTTPException(404, 'No video for this language yet')
    client = _s3_client()
    if client is None:
        raise HTTPException(500, 'PREFY_AWS_ACCESS_KEY_ID / PREFY_AWS_SECRET_ACCESS_KEY not configured on this service')
    url = client.generate_presigned_url(
        'get_object',
        Params={'Bucket': PREFY_MEDIA_S3_BUCKET, 'Key': key},
        ExpiresIn=_PRESIGN_EXPIRES_SECONDS,
    )
    return RedirectResponse(url, status_code=302)


@app.get('/', response_class=HTMLResponse)
def root():
    return """<!doctype html>
<html lang="es" data-source-lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prefy — entorno de prueba</title>
<link rel="stylesheet" href="/prefy-video.css">
<style>
  body { background:#0a0d14; color:#f0f4ff; font-family:-apple-system,system-ui,sans-serif; padding:24px; }
  h1 { font-size:18px; }
  p { color:#9aa4bd; font-size:14px; max-width:480px; }
  button { background:#2d6eff; color:#fff; border:none; border-radius:8px; padding:10px 16px; font-size:14px; font-weight:600; cursor:pointer; }
</style>
</head>
<body>
  <h1>Prefy — entorno de prueba aislado</h1>
  <p>Este servicio sirve ÚNICAMENTE el reproductor de Prefy, contra los
     videos reales de S3, sin tocar la base de datos ni el backend de
     producción de Preferendum. Elige un contexto:</p>
  <button onclick="window.PrefyVideo.show('welcome'); window.PrefyVideo.open();">Welcome</button>
  <button onclick="window.PrefyVideo.show('campaign'); window.PrefyVideo.open();">Campaign</button>
  <script src="/prefy-video.js"></script>
</body>
</html>"""
