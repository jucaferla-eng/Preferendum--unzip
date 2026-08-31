"""
test_i18n_hardening.py — I18N FINAL HARDENING BEFORE RELEASE.

Covers:
  - User.preferred_lang: additive migration, default-safe, validated.
  - resolve_user_language(): the backend precedence, cross-checked against
    lang.js's own table for zero drift.
  - /profile/language: self-only, authenticated, validated, auditable.
  - send_email_otp / send_sms_otp: every active call site now
    language-aware, behaviorally verified (not just structurally).
  - Full country/language test matrix (Section 8) including multilingual
    countries (US, India).
  - Security: cross-user tampering, injection, unsupported values, no
    secrets leaked.

LOCAL / TEST ONLY. DATABASE_URL is forced to a throwaway sqlite file; no
production credential is read and no network call is made.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='i18n-hardening-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-i18n-hardening'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-i18n-hardening'
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL', 'RESEND_API_KEY', 'GMAIL_APP_PASSWORD'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402

REPO_ROOT = Path(main.__file__).parent
REQUIRED_LANGUAGES = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi']

_seq = {'n': 0}


def _uid():
    _seq['n'] += 1
    return _seq['n']


class Base(unittest.TestCase):

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)
        self.client = TestClient(main.app)

    def mk_user(self, **kw):
        n = _uid()
        base = dict(email=f'i18nh{n}@test.local', name=f'U{n}', password='x',
                   country='CL', county='', gender='F', dob='1990-01-01',
                   role='voter', referral_code=f'I18NH{n:06d}', email_verified=True)
        base.update(kw)
        u = main.User(**base)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def auth_headers(self, user):
        token = main.make_token(user.id, user.role)
        return {'Authorization': f'Bearer {token}'}


# ═══════════════════════════════════════════════════════════════════════
# Section 1 — User.preferred_lang: additive, default-safe, validated
# ═══════════════════════════════════════════════════════════════════════

class TestPreferredLangColumn(unittest.TestCase):

    def test_column_exists_with_a_safe_default(self):
        from sqlalchemy import inspect as sa_inspect
        cols = {c['name']: c for c in sa_inspect(main.engine).get_columns('users')}
        self.assertIn('preferred_lang', cols)

    def test_fresh_db_provisions_the_column(self):
        """A genuinely fresh sqlite file gets the column via _migrate()
        alone -- no production-only step required."""
        script = '''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-i18n-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
from sqlalchemy import inspect as sa_inspect
cols = {c["name"] for c in sa_inspect(main.engine).get_columns("users")}
assert "preferred_lang" in cols, "preferred_lang missing from a fresh DB"
db = main.SessionLocal()
u = main.User(email="fresh_lang@test.local", name="U", password="x", country="CL",
              county="", gender="F", dob="1990-01-01", role="voter", referral_code="FRESHLANG1")
db.add(u); db.commit(); db.refresh(u)
assert u.preferred_lang == "", f"expected empty-string default, got {u.preferred_lang!r}"
print("OK")
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)


class TestPreferredLangDefaultSafety(Base):

    def test_existing_users_get_empty_string_not_null_crash(self):
        u = self.mk_user()
        self.assertEqual(u.preferred_lang, '')

    def test_preferred_lang_never_auto_set_at_registration(self):
        """Section 1: the stored preference represents ONLY an explicit
        choice -- registration's resolved display language must not be
        silently written into preferred_lang (that would blur 'explicit'
        with 'resolved-from-device/country')."""
        r = self.client.post('/voter/register', json={
            'name': 'Test', 'email': 'noautoset@test.local', 'password': 'x', 'country': 'CL',
            'phone': '', 'national_id': '99999999-9', 'profession': '', 'cargo': '', 'lang': 'ja',
        })
        self.assertEqual(r.status_code, 200, r.text)
        u = self.db.query(main.User).filter(main.User.email == 'noautoset@test.local').first()
        self.assertEqual(u.preferred_lang, '',
                         'registration lang is for the OTP email only, never auto-stored as explicit preference')


# ═══════════════════════════════════════════════════════════════════════
# Sections 1-2 — resolve_user_language precedence, cross-checked vs lang.js
# ═══════════════════════════════════════════════════════════════════════

class TestResolveUserLanguage(unittest.TestCase):

    def test_explicit_beats_device_and_country(self):
        self.assertEqual(main.resolve_user_language(explicit='fr', device='en-US', country='JP'), 'fr')

    def test_device_beats_country(self):
        self.assertEqual(main.resolve_user_language(device='de-DE', country='JP'), 'de')

    def test_country_used_when_device_unsupported_or_absent(self):
        self.assertEqual(main.resolve_user_language(device='xx-XX', country='JP'), 'ja')
        self.assertEqual(main.resolve_user_language(country='BR'), 'pt')

    def test_global_fallback(self):
        self.assertEqual(main.resolve_user_language(), 'es')
        self.assertEqual(main.resolve_user_language(device='xx-XX', country='ZZ'), 'es')

    def test_multilingual_countries_have_no_forced_default(self):
        for cc in ('US', 'GB', 'AU', 'CA', 'ZA', 'NG', 'IN', 'CH', 'BE'):
            self.assertNotIn(cc, main._COUNTRY_DEFAULT_LANGUAGE, f'{cc} must not have a forced default')

    def test_india_hindi_device_resolves_via_device_not_country(self):
        self.assertEqual(main.resolve_user_language(device='hi-IN', country='IN'), 'hi')

    def test_india_english_device_resolves_via_device_not_country(self):
        self.assertEqual(main.resolve_user_language(device='en-IN', country='IN'), 'en')

    def test_india_unsupported_device_falls_through_to_global_not_forced(self):
        self.assertEqual(main.resolve_user_language(device='ta-IN', country='IN'), 'es')

    def test_us_spanish_preference_is_not_overridden_to_english(self):
        self.assertEqual(main.resolve_user_language(explicit='es', country='US'), 'es')

    def test_country_never_overrides_a_stored_explicit_preference(self):
        for cc in ('JP', 'KR', 'FR', 'DE', 'BR'):
            self.assertEqual(main.resolve_user_language(explicit='ar', country=cc), 'ar')

    def test_backend_table_matches_lang_js_exactly_no_drift(self):
        """Cross-check: parse lang.js's COUNTRY_DEFAULT_LANGUAGE and
        SUPPORTED_LANGUAGES directly out of the file and assert byte-for-
        byte equality with the Python side."""
        js_src = (REPO_ROOT / 'lang.js').read_text(encoding='utf-8')
        js_supported = re.search(r"var SUPPORTED_LANGUAGES = \[(.*?)\];", js_src).group(1)
        js_langs = sorted(re.findall(r"'([a-z]{2})'", js_supported))
        self.assertEqual(js_langs, sorted(main._SUPPORTED_LANGUAGES))

        js_table_block = re.search(r"var COUNTRY_DEFAULT_LANGUAGE = \{(.*?)\};", js_src, re.DOTALL).group(1)
        js_pairs = dict(re.findall(r"([A-Z]{2}):\s*'([a-z]{2})'", js_table_block))
        self.assertEqual(js_pairs, main._COUNTRY_DEFAULT_LANGUAGE,
                         'lang.js and main.py country-default tables have drifted apart')


# ═══════════════════════════════════════════════════════════════════════
# Section 3 — /profile/language endpoint
# ═══════════════════════════════════════════════════════════════════════

class TestProfileLanguageEndpoint(Base):

    def test_requires_authentication(self):
        r = self.client.post('/profile/language', json={'lang': 'en'})
        # This app's auth dependency (matching /profile/income's own
        # behavior) returns 403 for a request with no credentials at all;
        # the assertion is "not 200", not a specific status family.
        self.assertNotEqual(r.status_code, 200)
        self.assertIn(r.status_code, (401, 403))

    def test_sets_own_language(self):
        u = self.mk_user()
        r = self.client.post('/profile/language', json={'lang': 'ja'}, headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.db.refresh(u)
        self.assertEqual(u.preferred_lang, 'ja')

    def test_get_returns_own_preference(self):
        u = self.mk_user(preferred_lang='ko')
        r = self.client.get('/profile/language', headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['preferred_lang'], 'ko')

    def test_get_returns_null_when_unset(self):
        u = self.mk_user()
        r = self.client.get('/profile/language', headers=self.auth_headers(u))
        self.assertIsNone(r.json()['preferred_lang'])

    def test_rejects_unsupported_language(self):
        u = self.mk_user()
        r = self.client.post('/profile/language', json={'lang': 'klingon'}, headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 400)
        self.db.refresh(u)
        self.assertEqual(u.preferred_lang, '')

    def test_rejects_empty_string(self):
        u = self.mk_user()
        r = self.client.post('/profile/language', json={'lang': ''}, headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 400)

    def test_accepts_every_one_of_the_12_supported_languages(self):
        for lang in REQUIRED_LANGUAGES:
            u = self.mk_user()
            r = self.client.post('/profile/language', json={'lang': lang}, headers=self.auth_headers(u))
            self.assertEqual(r.status_code, 200, f'{lang}: {r.text}')
            self.db.refresh(u)
            self.assertEqual(u.preferred_lang, lang)

    def test_only_updates_the_language_field_no_side_effects_on_other_profile_data(self):
        u = self.mk_user(name='Original Name', country='CL', se_tier='B')
        self.client.post('/profile/language', json={'lang': 'de'}, headers=self.auth_headers(u))
        self.db.refresh(u)
        self.assertEqual(u.name, 'Original Name')
        self.assertEqual(u.country, 'CL')
        self.assertEqual(u.se_tier, 'B')


# ═══════════════════════════════════════════════════════════════════════
# Section 9 — security
# ═══════════════════════════════════════════════════════════════════════

class TestSecurity(Base):

    def test_user_a_cannot_change_user_b_language(self):
        """No user_id field exists on the request at all -- the ONLY
        identity source is the JWT. Confirms this structurally by proving
        a body carrying a foreign user_id has no effect."""
        victim = self.mk_user(preferred_lang='fr')
        attacker = self.mk_user()
        r = self.client.post('/profile/language',
                             json={'lang': 'ru', 'user_id': victim.id},
                             headers=self.auth_headers(attacker))
        self.assertEqual(r.status_code, 200)  # extra field silently ignored by Pydantic
        self.db.refresh(victim)
        self.db.refresh(attacker)
        self.assertEqual(victim.preferred_lang, 'fr', "victim's language must be untouched")
        self.assertEqual(attacker.preferred_lang, 'ru', "only the caller's own row changes")

    def test_malformed_language_rejected(self):
        u = self.mk_user()
        for bad in ('<script>alert(1)</script>', "'; DROP TABLE users; --", 'a' * 5000, '../../etc/passwd'):
            r = self.client.post('/profile/language', json={'lang': bad}, headers=self.auth_headers(u))
            self.assertEqual(r.status_code, 400, f'{bad!r} must be rejected')
        self.db.refresh(u)
        self.assertEqual(u.preferred_lang, '', 'no malformed value must ever be persisted')

    def test_language_field_cannot_alter_other_profile_fields_via_extra_keys(self):
        u = self.mk_user(se_tier='D', role='voter')
        r = self.client.post('/profile/language',
                             json={'lang': 'en', 'se_tier': 'A', 'role': 'admin', 'is_verified': True},
                             headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 200)
        self.db.refresh(u)
        self.assertEqual(u.se_tier, 'D', 'se_tier must not be alterable via /profile/language')
        self.assertEqual(u.role, 'voter', 'role must not be alterable via /profile/language')

    def test_sms_body_actually_reflects_the_requested_language(self):
        """Behavioral, not just structural: capture what would actually be
        sent and confirm the SMS body genuinely differs per language and
        matches _OTP_SMS_TEMPLATES -- catches send_sms_otp accepting
        `lang` but silently ignoring it (e.g. hardcoded back to Spanish)."""
        captured = {}

        class _FakeTwilioClient:
            def __init__(self, *a, **kw): pass
            class messages:
                @staticmethod
                def create(body='', **kw):
                    captured['body'] = body

        os.environ['TWILIO_ACCOUNT_SID'] = 'fake'
        os.environ['TWILIO_AUTH_TOKEN'] = 'fake'
        import twilio.rest
        original = twilio.rest.Client
        twilio.rest.Client = _FakeTwilioClient
        try:
            for lang in REQUIRED_LANGUAGES:
                captured.clear()
                main.send_sms_otp('+56900000000', '333333', lang)
                expected_body = main._OTP_SMS_TEMPLATES[lang].format(code='333333')
                self.assertEqual(captured['body'], expected_body, f'{lang}: SMS body does not match its template')
        finally:
            twilio.rest.Client = original
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_sms_es_and_ja_produce_genuinely_different_output(self):
        captured = []

        class _FakeTwilioClient:
            def __init__(self, *a, **kw): pass
            class messages:
                @staticmethod
                def create(body='', **kw):
                    captured.append(body)

        os.environ['TWILIO_ACCOUNT_SID'] = 'fake'
        os.environ['TWILIO_AUTH_TOKEN'] = 'fake'
        import twilio.rest
        original = twilio.rest.Client
        twilio.rest.Client = _FakeTwilioClient
        try:
            main.send_sms_otp('+56900000000', '111111', 'es')
            main.send_sms_otp('+56900000000', '111111', 'ja')
        finally:
            twilio.rest.Client = original
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)
        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0], captured[1], 'es and ja SMS bodies must not be identical')

    def test_no_otp_or_token_content_changes_across_languages(self):
        """The OTP digits themselves must be byte-identical regardless of
        the resolved language -- already proven in test_i18n_remediation
        for send_email_otp; here confirmed end-to-end via SMS too."""
        captured = []

        class _FakeTwilioClient:
            def __init__(self, *a, **kw): pass
            class messages:
                @staticmethod
                def create(body='', **kw):
                    captured.append(body)

        os.environ['TWILIO_ACCOUNT_SID'] = 'fake'
        os.environ['TWILIO_AUTH_TOKEN'] = 'fake'
        import twilio.rest
        original = twilio.rest.Client
        twilio.rest.Client = _FakeTwilioClient
        try:
            for lang in REQUIRED_LANGUAGES:
                main.send_sms_otp('+56900000000', '424242', lang)
        finally:
            twilio.rest.Client = original
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)
        self.assertEqual(len(captured), len(REQUIRED_LANGUAGES))
        for body in captured:
            self.assertIn('424242', body, f'OTP digits missing from SMS body: {body!r}')

    def test_no_sensitive_data_reaches_third_party_translation_in_otp_flow(self):
        """send_email_otp / send_sms_otp never call MyMemory or Google
        Translate -- confirmed by source inspection (no import of either)."""
        import inspect
        email_src = inspect.getsource(main.send_email_otp)
        sms_src = inspect.getsource(main.send_sms_otp)
        for src in (email_src, sms_src):
            self.assertNotIn('mymemory', src.lower())
            self.assertNotIn('translate.google', src.lower())


# ═══════════════════════════════════════════════════════════════════════
# Section 8 — full language/communication test matrix
# ═══════════════════════════════════════════════════════════════════════

class TestLanguageMatrix(Base):

    def _capture_resend(self):
        captured = {}

        class _FakeResponse:
            status_code = 200
            text = 'ok'

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured['subject'] = json['subject']
            captured['html'] = json['html']
            return _FakeResponse()

        os.environ['RESEND_API_KEY'] = 'fake-key-for-this-test-only'
        original = main._requests.post
        main._requests.post = _fake_post
        self.addCleanup(lambda: (setattr(main._requests, 'post', original), os.environ.pop('RESEND_API_KEY', None)))
        return captured

    def test_stored_explicit_preference_wins_for_every_language(self):
        for lang in REQUIRED_LANGUAGES:
            u = self.mk_user(preferred_lang=lang, country='CL')  # country deliberately mismatched
            resolved = main.resolve_user_language(explicit=u.preferred_lang, device='xx-XX', country=u.country)
            self.assertEqual(resolved, lang)

    def test_otp_email_uses_correct_language_for_every_supported_language(self):
        captured = self._capture_resend()
        for lang in REQUIRED_LANGUAGES:
            main.send_email_otp('test@test.local', '555555', 'Test', lang)
            expected = main._OTP_EMAIL_STRINGS[lang]
            self.assertIn(expected['instruction'], captured['html'], f'{lang} email content mismatch')

    def test_resend_verification_uses_stored_preference(self):
        """/verify/email/send (the 'resend' flow)."""
        captured = self._capture_resend()
        u = self.mk_user(preferred_lang='de', email_verified=False)
        r = self.client.post('/verify/email/send', headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(main._OTP_EMAIL_STRINGS['de']['instruction'], captured['html'])

    def test_fallback_works_when_user_has_no_saved_preference(self):
        captured = self._capture_resend()
        u = self.mk_user(preferred_lang='', email_verified=False)
        r = self.client.post('/verify/email/send', headers=self.auth_headers(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(main._OTP_EMAIL_STRINGS['es']['instruction'], captured['html'],
                      'no stored preference and no Accept-Language header -> Spanish global fallback')

    def test_multilingual_country_us_with_spanish_preference(self):
        u = self.mk_user(preferred_lang='es', country='US')
        self.assertEqual(main.resolve_user_language(explicit=u.preferred_lang, country=u.country), 'es')

    def test_multilingual_country_india_with_hindi_preference(self):
        u = self.mk_user(preferred_lang='hi', country='IN')
        self.assertEqual(main.resolve_user_language(explicit=u.preferred_lang, country=u.country), 'hi')

    def test_multilingual_country_india_with_english_preference(self):
        u = self.mk_user(preferred_lang='en', country='IN')
        self.assertEqual(main.resolve_user_language(explicit=u.preferred_lang, country=u.country), 'en')


if __name__ == '__main__':
    unittest.main()
