"""test_prefy_backend_routes.py — Prefy contextual guide (Phase 1).

Confirms the three new static-file routes serve correctly, exactly like
the existing /lang.js and /translate.js routes they're modeled on, and
that nothing about them touches the database, requires auth, or executes
any business logic — they read a file off disk and return it, same as
their siblings.
"""
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix='prefy-route-test-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "t.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-prefy'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-prefy'

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


def test_prefy_js_route_serves_javascript():
    r = client.get('/prefy.js')
    assert r.status_code == 200
    assert 'javascript' in r.headers['content-type']
    assert 'Prefy' in r.text


def test_prefy_content_js_route_serves_javascript():
    r = client.get('/prefy-content.js')
    assert r.status_code == 200
    assert 'javascript' in r.headers['content-type']
    assert 'PrefyContent' in r.text


def test_prefy_css_route_serves_css():
    r = client.get('/prefy.css')
    assert r.status_code == 200
    assert 'css' in r.headers['content-type']
    assert '.prefy-root' in r.text


def test_prefy_routes_require_no_authentication():
    # Same as /lang.js and /translate.js — these are static assets, not
    # authenticated API responses.
    for path in ('/prefy.js', '/prefy-content.js', '/prefy.css'):
        r = client.get(path)
        assert r.status_code == 200


def test_prefy_routes_are_cacheable_like_their_siblings():
    for path in ('/prefy.js', '/prefy-content.js', '/prefy.css'):
        r = client.get(path)
        assert 'max-age' in r.headers.get('cache-control', '')


def test_all_three_portals_reference_the_shared_prefy_files():
    for path in ('/voter', '/marketer-portal', '/organizer-panel'):
        r = client.get(path)
        assert r.status_code == 200
        assert '/prefy.js' in r.text
        assert '/prefy-content.js' in r.text
        assert '/prefy.css' in r.text


APPROVED_ASSET_FILENAMES = [
    'prefy-welcome.png', 'prefy-explaining.png', 'prefy-presenting.png',
    'prefy-thinking.png', 'prefy-idea.png', 'prefy-attention.png',
    'prefy-missing-information.png', 'prefy-error.png',
    'prefy-possible-fraud.png', 'prefy-hacker-alert.png',
    'prefy-good-job.png', 'prefy-success.png', 'prefy-thanks.png',
    'prefy-help.png', 'prefy-goodbye.png',
]


def test_all_15_approved_assets_are_served():
    for filename in APPROVED_ASSET_FILENAMES:
        r = client.get(f'/assets/prefy/{filename}')
        assert r.status_code == 200, f'{filename}: {r.status_code}'
        assert r.headers['content-type'] == 'image/png'
        assert len(r.content) > 1000, f'{filename}: suspiciously small response'


def test_asset_route_rejects_a_filename_outside_the_whitelist():
    # Path-traversal / arbitrary-file-read guard: only the 15 approved
    # filenames are ever served, regardless of what's actually on disk.
    for attempt in ('../main.py', 'prefy-welcome.png/../../main.py', 'random-file.png', 'prefy-welcome.svg'):
        r = client.get(f'/assets/prefy/{attempt}')
        assert r.status_code == 404, f'{attempt} unexpectedly served: {r.status_code}'


def test_asset_route_requires_no_authentication():
    r = client.get('/assets/prefy/prefy-welcome.png')
    assert r.status_code == 200


def test_asset_route_is_cacheable():
    r = client.get('/assets/prefy/prefy-welcome.png')
    assert 'max-age' in r.headers.get('cache-control', '')
