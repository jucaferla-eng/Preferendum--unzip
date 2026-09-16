"""test_prefy_s3_video.py — Prefy S3 integration (welcome + campaign).

Structural + route-level checks for the S3-backed video delivery added
to main.py's /prefy/video/{context}/{lang} route. Mirrors this project's
existing pattern for prefy_video_catalog-style tests: assert the literal
mapping tables are complete and correct, then exercise the actual route.

Run with: python3 test_prefy_s3_video.py
"""
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_prefy_s3_video.db')

import main
from fastapi.testclient import TestClient

CANONICAL_30 = [
    'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi',
    'nl', 'pl', 'tr', 'id', 'vi', 'th', 'fil', 'bn', 'ur', 'fa', 'he',
    'sv', 'da', 'fi', 'el', 'cs', 'ro', 'uk',
]


class TestS3KeyTables(unittest.TestCase):
    """Requirements 1-3: exact 30-language parity, no dup/missing codes,
    for BOTH contexts."""

    def _check_table(self, table):
        keys = set(table.keys())
        canon = set(CANONICAL_30)
        self.assertEqual(len(table), 30, f'expected exactly 30 entries, got {len(table)}')
        self.assertEqual(keys, canon, f'missing={canon - keys} extra={keys - canon}')
        values = list(table.values())
        self.assertEqual(len(values), len(set(values)), 'duplicate S3 object keys found')
        for lang, key in table.items():
            self.assertTrue(key.strip(), f'{lang} has an empty/whitespace-only key')
            self.assertTrue(key.endswith('.mp4'), f'{lang} key does not end in .mp4: {key!r}')

    def test_welcome_table_complete(self):
        self._check_table(main.PREFY_WELCOME_S3_KEY_BY_LANG)

    def test_campaign_table_complete(self):
        self._check_table(main.PREFY_CAMPAIGN_S3_KEY_BY_LANG)

    def test_no_key_was_generated_from_a_pattern(self):
        # The old GitHub/local-disk branches use a computed
        # "prefy-{context}-{lang}.mp4" pattern — the S3 tables must never
        # collide with or resemble that (proof they're literal, not
        # pattern-generated).
        for table in (main.PREFY_WELCOME_S3_KEY_BY_LANG, main.PREFY_CAMPAIGN_S3_KEY_BY_LANG):
            for lang, key in table.items():
                self.assertNotEqual(
                    key, main._prefy_video_filename('welcome', lang),
                    f'{lang} key looks pattern-generated, not literal: {key!r}')

    def test_spanish_special_mapping_and_exotic_characters_preserved(self):
        # es must map to the "sp"-suffixed S3 folder, and the exact
        # spacing/accents from the verified listing must survive.
        self.assertIn('_-sp/', main.PREFY_WELCOME_S3_KEY_BY_LANG['es'])
        self.assertIn('_0-sp/', main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['es'])
        self.assertIn('heygen_project 3/', main.PREFY_WELCOME_S3_KEY_BY_LANG['es'])
        self.assertIn('Campaña /heygen_project/', main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['es'])
        self.assertTrue(main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['es'].endswith('.mp4'))
        # The exact accented filename is NOT re-checked here by typing it
        # out again — that's exactly the trap that caused the real
        # production 403 (a visually-identical but byte-different
        # literal). See test_es_campaign_key_has_the_exact_mixed_unicode_normalization
        # for the actual, codepoint-integer-based protection.

    def test_es_campaign_key_has_the_exact_mixed_unicode_normalization(self):
        # Regression lock for the real production 403: the actual S3
        # object is NOT fully NFC. Confirmed against a real AWS codepoint
        # dump of the stored key: the shared "Campaña" folder (common to
        # all 30 campaign objects, proven reachable via 'fil') uses the
        # ordinary PRECOMPOSED ñ (U+00F1) — but the Spanish-only filename
        # ("Guía del área de campañas...") uses DECOMPOSED accents
        # (base letter + COMBINING ACUTE ACCENT U+0301 for í/á, +
        # COMBINING TILDE U+0303 for ñ). This asserts the exact codepoint
        # SEQUENCE (integers, not visual/typed characters), so a
        # formatter/editor/copy-paste that silently renormalizes the
        # string to plain NFC or NFD can never pass this test unnoticed
        # — checking string equality against another literal wouldn't
        # catch that, since both sides could be renormalized together.
        key = main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['es']
        non_ascii_codepoints = [ord(c) for c in key if ord(c) > 127]
        self.assertEqual(non_ascii_codepoints, [0xf1, 0x301, 0x301, 0x303],
            f'Spanish Campaign key normalization has drifted from the verified AWS evidence: {[hex(c) for c in non_ascii_codepoints]!r}')
        # And the precomposed ñ must land specifically in "Campaña" (the
        # shared prefix), not have leaked into the filename or been lost
        # from the prefix.
        self.assertIn('Campaña /heygen_project/', key)

    def test_bn_ur_resolved_to_distinct_keys(self):
        self.assertNotEqual(main.PREFY_WELCOME_S3_KEY_BY_LANG['bn'], main.PREFY_WELCOME_S3_KEY_BY_LANG['ur'])
        self.assertIn('_n-IN/', main.PREFY_WELCOME_S3_KEY_BY_LANG['bn'])
        self.assertIn('_r-IN/', main.PREFY_WELCOME_S3_KEY_BY_LANG['ur'])
        self.assertIn('_n-IN/', main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['bn'])
        self.assertIn('_r-IN/', main.PREFY_CAMPAIGN_S3_KEY_BY_LANG['ur'])


class TestPrefyVideoRoute(unittest.TestCase):
    """Requirements 4, 5, 12: valid/invalid route behavior, graceful
    failure with no AWS config."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_context_registry_has_both_approved_contexts(self):
        self.assertEqual(main._PREFY_VIDEO_CONTEXTS, frozenset({'welcome', 'campaign'}))

    def test_invalid_context_404(self):
        r = self.client.get('/prefy/video/registration/es', follow_redirects=False)
        self.assertEqual(r.status_code, 404)

    def test_invalid_language_404(self):
        r = self.client.get('/prefy/video/welcome/xx', follow_redirects=False)
        self.assertEqual(r.status_code, 404)

    def test_missing_aws_prefy_config_does_not_crash_the_route_or_app(self):
        # With no PREFY_AWS_* set (the default in this test process),
        # /prefy/video/campaign/{lang} has no local-disk or GitHub
        # fallback content either — it should 404 cleanly, never 500,
        # and every unrelated route must keep working.
        self.assertFalse(main.PREFY_AWS_ACCESS_KEY_ID)
        r = self.client.get('/prefy/video/campaign/fil', follow_redirects=False)
        self.assertIn(r.status_code, (404,), f'expected graceful 404, got {r.status_code}')
        health = self.client.get('/health')
        self.assertEqual(health.status_code, 200)

    def test_prefy_video_js_and_css_do_not_allow_long_unconditional_caching(self):
        # Regression lock for the real production bug this exact policy
        # caused: /prefy-video.js changed shape between two deploys (a
        # 'campaign' context was added) while its URL stayed the same;
        # a long "public, max-age=86400" Cache-Control let browsers that
        # had fetched the pre-deploy file keep running it for up to 24h
        # after the new version went live — the old show() silently
        # ignored its context argument and always fell back to Welcome,
        # so the Campaigns panel played the Welcome video. 'no-cache'
        # still lets the browser retain the asset, but forces it to
        # revalidate with the server before reusing it on each load, so
        # a real deploy takes effect immediately instead of waiting out
        # a stale cache window.
        for path in ('/prefy-video.js', '/prefy-video.css'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200)
            cache_control = r.headers.get('cache-control', '')
            self.assertNotIn('max-age=86400', cache_control, f'{path} still allows a 24h unconditional cache')
            self.assertNotRegex(cache_control, r'max-age=\d{3,}',
                                 f'{path} still allows a long (100s+ seconds) unconditional cache: {cache_control!r}')
            self.assertIn('no-cache', cache_control, f'{path} does not use the approved revalidation policy: {cache_control!r}')

    def test_s3_client_helper_returns_none_without_credentials(self):
        self.assertIsNone(main._prefy_s3_client())
        self.assertIsNone(main._prefy_s3_presigned_url('welcome', 'es'))

    def test_s3_precedence_with_fake_well_formed_credentials(self):
        # generate_presigned_url() is a pure local HMAC computation — it
        # does not contact AWS, so this proves the whole resolution path
        # (literal key lookup -> presigned URL -> 302) without needing
        # real credentials. Every one of the 60 (context, lang) pairs is
        # checked, not just a sample.
        old = (main.PREFY_AWS_ACCESS_KEY_ID, main.PREFY_AWS_SECRET_ACCESS_KEY,
               main.PREFY_MEDIA_S3_BUCKET, main._prefy_s3_client_cache)
        try:
            # Deliberately NOT shaped like a real AWS credential (no real
            # access-key prefix, no base64-like secret) — boto3's local
            # presigning math only needs *some* non-empty string in each
            # field, so a plainly synthetic placeholder proves the same
            # code path without storing anything credential-shaped here.
            main.PREFY_AWS_ACCESS_KEY_ID = 'test-prefy-s3-credential-placeholder-id'
            main.PREFY_AWS_SECRET_ACCESS_KEY = 'test-prefy-s3-credential-placeholder-secret'
            main.PREFY_MEDIA_S3_BUCKET = 'preferendum-prefy'
            main._prefy_s3_client_cache = None
            for context, table in (('welcome', main.PREFY_WELCOME_S3_KEY_BY_LANG),
                                    ('campaign', main.PREFY_CAMPAIGN_S3_KEY_BY_LANG)):
                for lang, key in table.items():
                    r = self.client.get(f'/prefy/video/{context}/{lang}', follow_redirects=False)
                    self.assertEqual(r.status_code, 302, f'{context}/{lang} did not redirect')
                    location = r.headers['location']
                    self.assertIn('preferendum-prefy.s3.amazonaws.com', location)
                    self.assertIn('Signature=', location)
        finally:
            (main.PREFY_AWS_ACCESS_KEY_ID, main.PREFY_AWS_SECRET_ACCESS_KEY,
             main.PREFY_MEDIA_S3_BUCKET, main._prefy_s3_client_cache) = old


if __name__ == '__main__':
    unittest.main(verbosity=2)
