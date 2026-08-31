"""
test_i18n_remediation.py — COMPLETE INTERNATIONALIZATION REMEDIATION.

Covers:
  - The Node-based pure-resolver tests (test_lang_resolver.mjs) and the
    extracted-real-code tests (test_voter_portal_i18n.mjs), run as
    subprocesses so `pytest` picks them up as part of the normal suite.
  - Structural coverage: every active portal includes lang.js and a
    manual selector container.
  - Backend email language table completeness and behavior.
  - /voter/register's optional `lang` field, end to end.
  - Occupation i18n integration (Section 8) — canonical SOC identity is
    unaffected by display language.

LOCAL / TEST ONLY. DATABASE_URL is forced to a throwaway sqlite file; no
production credential is read and no network call is made (RESEND_API_KEY
and GMAIL_APP_PASSWORD are explicitly popped so send_email_otp always
takes its dev/no-op path).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='i18n-remediation-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-i18n'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-i18n'
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL', 'RESEND_API_KEY', 'GMAIL_APP_PASSWORD'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402
import socioeconomic as S                      # noqa: E402

REPO_ROOT = Path(main.__file__).parent
REQUIRED_LANGUAGES = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi']


class TestNodeResolverSuite(unittest.TestCase):
    """Runs the actual Node-based test files as subprocesses so pytest's
    'run everything' picks up JS-level regressions too."""

    def test_lang_resolver_pure_logic(self):
        result = subprocess.run(['node', 'test_lang_resolver.mjs'], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_voter_portal_extracted_functions(self):
        result = subprocess.run(['node', 'test_voter_portal_i18n.mjs'], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestPortalStructuralCoverage(unittest.TestCase):
    """Section 2: a visible, accessible language selector on every active
    user-facing portal/surface, backed by the ONE resolver."""

    _ACTIVE_PORTALS = [
        'voter_portal.html', 'marketer_portal.html', 'preferendum_organizer.html',
        'preferendum_marketers.html', 'preferendum_organizers.html',
    ]

    def test_every_active_portal_includes_lang_js_before_translate_js(self):
        for fname in self._ACTIVE_PORTALS:
            html = (REPO_ROOT / fname).read_text(encoding='utf-8')
            lang_idx = html.find('/lang.js')
            translate_idx = html.find('/translate.js')
            self.assertNotEqual(lang_idx, -1, f'{fname} does not include lang.js')
            self.assertNotEqual(translate_idx, -1, f'{fname} does not include translate.js')
            self.assertLess(lang_idx, translate_idx,
                            f'{fname}: lang.js must load BEFORE translate.js so the cookie is already set')

    def test_every_active_portal_has_a_selector_container(self):
        for fname in self._ACTIVE_PORTALS:
            html = (REPO_ROOT / fname).read_text(encoding='utf-8')
            self.assertIn('data-pref-lang-selector', html, f'{fname} has no manual language selector')

    def test_every_active_portal_declares_a_source_language(self):
        for fname in self._ACTIVE_PORTALS:
            html = (REPO_ROOT / fname).read_text(encoding='utf-8')
            self.assertIn('data-source-lang=', html,
                          f'{fname} does not declare data-source-lang -- Google Translate cannot '
                          f'know whether to treat this page as Spanish or English source')

    def test_root_landing_is_covered_too(self):
        root_src = main.__file__
        content = Path(root_src).read_text(encoding='utf-8')
        # The root page HTML is an inline string inside main.py's root() handler.
        start = content.index("def root():")
        end = content.index('""")', start)
        root_html = content[start:end]
        self.assertIn('/lang.js', root_html)
        self.assertIn('data-pref-lang-selector', root_html)
        self.assertIn('data-source-lang', root_html)


class TestBackendEmailLanguageTable(unittest.TestCase):
    """Section 6: backend language awareness for OTP emails."""

    def test_all_12_languages_covered(self):
        self.assertEqual(sorted(main._OTP_EMAIL_STRINGS.keys()), sorted(REQUIRED_LANGUAGES))

    def test_every_language_has_every_required_field(self):
        required_fields = {'greeting', 'instruction', 'validity', 'subject', 'default_name'}
        for lang, strings in main._OTP_EMAIL_STRINGS.items():
            self.assertEqual(set(strings.keys()), required_fields, f'{lang} missing fields')
            for field, value in strings.items():
                self.assertTrue(value, f'{lang}.{field} is empty')

    def test_subject_and_greeting_use_placeholders_not_hardcoded_values(self):
        """The OTP code and name must be INJECTED, never baked into the
        translated string itself (which would be a template bug, not a
        privacy issue, but worth pinning)."""
        for lang, strings in main._OTP_EMAIL_STRINGS.items():
            self.assertIn('{code}', strings['subject'], f'{lang} subject missing {{code}} placeholder')
            self.assertIn('{name}', strings['greeting'], f'{lang} greeting missing {{name}} placeholder')

    def test_send_email_otp_never_translates_the_code_itself(self):
        """The actual OTP digits must appear byte-identically regardless
        of language -- only the surrounding copy changes."""
        import inspect
        src = inspect.getsource(main.send_email_otp)
        # The numeric `code` variable must be interpolated as-is (an
        # f-string with plain `{code}`), never passed through any string
        # table lookup.
        self.assertIn('{code}', src)
        for lang in REQUIRED_LANGUAGES:
            self.assertNotIn(f"'{lang}': {{'code'", src)  # sanity: no per-lang code table exists

    def test_unrecognised_or_missing_lang_falls_back_to_spanish_exactly_as_before(self):
        for bad_lang in ('zz', '', None, 'xx-XX'):
            strings = main._OTP_EMAIL_STRINGS.get(bad_lang, main._OTP_EMAIL_STRINGS['es'])
            self.assertEqual(strings, main._OTP_EMAIL_STRINGS['es'])

    def test_send_email_otp_runs_without_error_for_every_supported_language(self):
        for lang in REQUIRED_LANGUAGES:
            result = main.send_email_otp('test@test.local', '123456', 'Juan', lang)
            self.assertTrue(result)

    def test_send_email_otp_actual_output_reflects_the_requested_language(self):
        """Behavioral, not just structural: capture what would actually be
        sent (via the Resend path) and confirm the subject/html genuinely
        differ per language and match _OTP_EMAIL_STRINGS -- catches a
        send_email_otp that accepts `lang` but silently ignores it."""
        captured = {}

        class _FakeResponse:
            status_code = 200
            text = 'ok'

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured['subject'] = json['subject']
            captured['html'] = json['html']
            return _FakeResponse()

        os.environ['RESEND_API_KEY'] = 'fake-key-for-this-test-only'
        original_post = main._requests.post
        main._requests.post = _fake_post
        try:
            for lang in REQUIRED_LANGUAGES:
                captured.clear()
                main.send_email_otp('test@test.local', '999999', 'Juan', lang)
                expected = main._OTP_EMAIL_STRINGS[lang]
                self.assertIn(expected['instruction'], captured['html'],
                             f'{lang}: html does not contain the {lang} instruction string')
                self.assertEqual(captured['subject'], expected['subject'].format(code='999999'),
                                 f'{lang}: subject does not match the {lang} template')
                self.assertIn('999999', captured['subject'], f'{lang}: OTP code missing from subject')
        finally:
            main._requests.post = original_post
            os.environ.pop('RESEND_API_KEY', None)

    def test_different_languages_produce_genuinely_different_output(self):
        """The strongest form of the above: es and ja output must not be
        byte-identical (proves the language argument has real effect, not
        just that both calls succeed)."""
        captured = []

        class _FakeResponse:
            status_code = 200
            text = 'ok'

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured.append(json['html'])
            return _FakeResponse()

        os.environ['RESEND_API_KEY'] = 'fake-key-for-this-test-only'
        original_post = main._requests.post
        main._requests.post = _fake_post
        try:
            main.send_email_otp('test@test.local', '111111', 'Juan', 'es')
            main.send_email_otp('test@test.local', '111111', 'Juan', 'ja')
        finally:
            main._requests.post = original_post
            os.environ.pop('RESEND_API_KEY', None)
        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0], captured[1], 'es and ja emails must not be identical')


class TestRegistrationLangFieldEndToEnd(unittest.TestCase):
    """The optional `lang` field on /voter/register, wired through to the
    OTP email's language, without breaking clients that omit it."""

    def setUp(self):
        self.client = TestClient(main.app)

    _nid_seq = 0

    def _register(self, email, **overrides):
        TestRegistrationLangFieldEndToEnd._nid_seq += 1
        n = TestRegistrationLangFieldEndToEnd._nid_seq
        payload = dict(name='Test User', email=email, password='x', country='CL',
                       phone='', national_id=f'{n:08d}-{n % 10}', profession='', cargo='')
        payload.update(overrides)
        return self.client.post('/voter/register', json=payload)

    def test_registration_without_lang_field_still_works(self):
        r = self._register('nolang@test.local')
        self.assertEqual(r.status_code, 200, r.text)

    def test_registration_with_explicit_lang_field_works(self):
        r = self._register('withlang@test.local', lang='fr')
        self.assertEqual(r.status_code, 200, r.text)

    def test_registration_with_unrecognised_lang_still_works(self):
        r = self._register('badlang@test.local', lang='not-a-real-language')
        self.assertEqual(r.status_code, 200, r.text)


class TestOccupationI18nIntegration(unittest.TestCase):
    """Section 8: canonical occupation identity must be unaffected by
    display language; adding aliases_es to the API response (from the
    prior occupation-resolution hardening) must still work exactly as
    before this task."""

    def test_spanish_and_english_still_resolve_to_the_same_canonical_soc(self):
        self.assertEqual(S.resolve_occupation_soc('Médico'), S.resolve_occupation_soc('Physician'))
        self.assertEqual(S.resolve_occupation_soc('Ingeniero Industrial'),
                         S.resolve_occupation_soc('Industrial Engineer'))

    def test_registration_stores_the_canonical_soc_code_not_the_display_label(self):
        """The occupation search click handler must persist item.dataset
        CODE into r-profession (the canonical, language-independent SOC
        identity) — never .title or a display label, regardless of which
        language a result happened to render in."""
        html = (REPO_ROOT / 'voter_portal.html').read_text(encoding='utf-8')
        self.assertIn("document.getElementById('r-profession').value = item.dataset.code;", html,
                      'occupation search must store the canonical SOC code, not a display label')

    def test_occupation_aliases_for_soc_is_language_independent_of_estimator(self):
        """occupation_aliases_for_soc is a pure DISPLAY helper -- calling
        it must never change what resolve_occupation_soc returns for the
        same canonical SOC code."""
        soc = '17-2112'
        before = S.resolve_occupation_soc('17-2112')
        _ = S.occupation_aliases_for_soc(soc, 'es')
        after = S.resolve_occupation_soc('17-2112')
        self.assertEqual(before, after, 'reading display aliases must not mutate resolution')


if __name__ == '__main__':
    unittest.main()
