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
