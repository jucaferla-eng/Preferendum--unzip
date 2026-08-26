"""
test_integration_http.py — CHANGE-002 Phase 2 REAL HTTP integration tests.

These are not unit tests against the evaluator: they boot the actual FastAPI
application from main.py and drive it over HTTP with fastapi.testclient, so
every dependency, decorator and route guard is exercised exactly as in
production.

LOCAL / TEST ONLY:
  * DATABASE_URL is forced to a throwaway sqlite file in a temp directory
    BEFORE main is imported, so the app can never reach a production
    database. The temp directory is removed on teardown.
  * JWT_SECRET / ADMIN_SECRET are test-only values generated here.
  * No production credential is read and no network call is made.

Covers scenarios A-S from the CHANGE-002 Phase 2 brief.

    python3 -m unittest test_integration_http -v
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

# ── Sandbox the app BEFORE importing it ────────────────────────────────
_TMPDIR = tempfile.mkdtemp(prefix='change002-it-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-change-002'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-change-002'
# Neutralize anything that might try to leave the machine.
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient          # noqa: E402
import main                                        # noqa: E402
import eligibility as E                            # noqa: E402

ADMIN_SECRET = os.environ['ADMIN_SECRET']


def tearDownModule():
    shutil.rmtree(_TMPDIR, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

_seq = {'n': 0}


def _uid():
    _seq['n'] += 1
    return _seq['n']


def mk_user(db, *, country='CL', county='Las Condes', gender='M',
            dob='1990-05-10', se_tier='B', role='voter', email=None,
            national_id='', email_verified=True, **kw):
    n = _uid()
    u = main.User(
        email=email or f'user{n}@test.local',
        name=f'User {n}',
        password='x',
        country=country, county=county, gender=gender, dob=dob,
        se_tier=se_tier, role=role, national_id=national_id,
        email_verified=email_verified,
        referral_code=f'REF{n:06d}',
        **kw
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def mk_debate(db, *, scope_country='CL', scope_commune='', status='live',
              is_closed_list=False, results_visibility='public',
              creator_id=0, **kw):
    n = _uid()
    kw.setdefault('title', f'Consulta {n}')
    kw.setdefault('context', 'ctx')
    kw.setdefault('options', '["Si","No"]')
    d = main.Debate(
        scope='country',
        scope_country=scope_country,
        scope_commune=scope_commune,
        status=status,
        is_closed_list=is_closed_list,
        results_visibility=results_visibility,
        creator_id=creator_id,
        opens_at=datetime.utcnow() - timedelta(days=1),
        closes_at=datetime.utcnow() + timedelta(days=30),
        **kw
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def mk_campaign(db, *, advertiser_email='adv@test.local', is_active=True, **kw):
    n = _uid()
    base = dict(
        advertiser_email=advertiser_email,
        advertiser_name=f'Brand {n}',
        title=f'Campaign {n}',
        budget_clp=1_000_000,
        ad_type='banner',
        target_country='', target_communes='', target_se_tiers='A,B,C,D',
        target_income_min=0.0, target_income_max=9999.0,
        target_gender='all', target_age_min=13, target_age_max=99,
        target_age_ranges='', target_categories='', excluded_categories='',
        min_per_capita_usd=0.0,
        is_active=is_active,
        start_date=datetime.utcnow() - timedelta(days=1),
        end_date=datetime.utcnow() + timedelta(days=30),
    )
    base.update(kw)
    c = main.AdCampaign(**base)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def mk_marketer(db, *, status='approved', email=None):
    u = mk_user(db, role='marketer', email=email, email_verified=True)
    p = main.MarketerProfile(
        user_id=u.id, org_type='company', is_supervisor=True,
        status=status, company_name='Acme',
    )
    db.add(p)
    db.commit()
    return u


def auth(user):
    return {'Authorization': f'Bearer {main.make_token(user.id, user.role)}'}


def campaign_payload(**kw):
    base = dict(
        advertiser_email='adv@test.local',
        advertiser_name='Acme',
        campaign_title='Nueva campaña',
        budget_clp=500_000,
        target_country='CL',
        start_date=datetime.utcnow().isoformat(),
        end_date=(datetime.utcnow() + timedelta(days=30)).isoformat(),
    )
    base.update(kw)
    return base


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)


# ═══════════════════════════════════════════════════════════════════════
# A-F. Consultation discovery, direct access and voting
# ═══════════════════════════════════════════════════════════════════════

class TestConsultationAccess(Base):

    def test_A_unauthenticated_listing_is_denied(self):
        r = self.client.get('/debates')
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_B_eligible_authenticated_consultation_is_visible(self):
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        u = mk_user(self.db, country='CL', county='Las Condes')
        r = self.client.get('/debates', headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        ids = [x['id'] for x in r.json()['debates']]
        self.assertIn(d.id, ids)

    def test_C_ineligible_consultation_is_absent_from_listing(self):
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        u = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.get('/debates', headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        ids = [x['id'] for x in r.json()['debates']]
        self.assertNotIn(d.id, ids)

    def test_D_direct_get_by_ineligible_user_is_non_disclosing(self):
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes',
                      title='SECRETO Las Condes')
        u = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.get(f'/debates/{d.id}', headers=auth(u))
        self.assertEqual(r.status_code, 404, r.text)
        # Non-disclosure: identical to a consultation that does not exist,
        # and the title must not leak in the error body.
        missing = self.client.get('/debates/99999999', headers=auth(u))
        self.assertEqual(r.status_code, missing.status_code)
        self.assertEqual(r.json().get('detail'), missing.json().get('detail'))
        self.assertNotIn('SECRETO', r.text)

    def test_D2_direct_get_unauthenticated_is_denied(self):
        d = mk_debate(self.db)
        r = self.client.get(f'/debates/{d.id}')
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_E_direct_vote_by_ineligible_user_is_rejected(self):
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        u = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0}, headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_F_eligible_user_reaches_normal_vote_validation(self):
        """An eligible user must NOT be stopped by targeting. They may still
        be stopped by ordinary vote validation (dedupe, device, etc.) — what
        matters is that the 403 targeting gate is passed."""
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        u = mk_user(self.db, country='CL', county='Las Condes')
        r = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0}, headers=auth(u))
        self.assertNotEqual(r.status_code, 403,
                            f'eligible user was blocked by targeting: {r.text}')
        self.assertIn(r.status_code, (200, 400, 422), r.text)


# ═══════════════════════════════════════════════════════════════════════
# G-H. Adversarial geography — Las Condes vs Conchalí
# ═══════════════════════════════════════════════════════════════════════

class TestLasCondesConchali(Base):
    """The mandatory adversarial pair. A Conchalí user must be rejected on
    EVERY path of a Las Condes consultation, not merely hidden from the feed."""

    def setUp(self):
        super().setUp()
        self.debate = mk_debate(self.db, scope_country='CL',
                                scope_commune='Las Condes')
        self.outsider = mk_user(self.db, country='CL', county='Conchali')
        self.insider = mk_user(self.db, country='CL', county='Las Condes')

    def test_G1_listing_hides_it(self):
        r = self.client.get('/debates', headers=auth(self.outsider))
        self.assertNotIn(self.debate.id, [x['id'] for x in r.json()['debates']])

    def test_G2_feed_hides_it(self):
        r = self.client.get('/debates/feed', headers=auth(self.outsider))
        # Assert the status outright: a soft `if r.status_code == 200` would
        # let this test silently stop testing anything the day the feed breaks.
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(self.debate.id, [x['id'] for x in r.json()['debates']])

    def test_G3_direct_access_404s(self):
        r = self.client.get(f'/debates/{self.debate.id}', headers=auth(self.outsider))
        self.assertEqual(r.status_code, 404, r.text)

    def test_G4_vote_is_rejected(self):
        r = self.client.post(f'/debates/{self.debate.id}/vote',
                             json={'option_index': 0}, headers=auth(self.outsider))
        self.assertEqual(r.status_code, 403, r.text)

    def test_G5_comments_are_rejected(self):
        r = self.client.get(f'/debates/{self.debate.id}/comments',
                            headers=auth(self.outsider))
        self.assertIn(r.status_code, (403, 404), r.text)

    def test_G6_accent_and_case_variants_are_still_rejected(self):
        """'Conchalí' must not sneak past by spelling."""
        for spelling in ('Conchalí', 'CONCHALI', ' conchali '):
            u = mk_user(self.db, country='CL', county=spelling)
            r = self.client.get(f'/debates/{self.debate.id}', headers=auth(u))
            self.assertEqual(r.status_code, 404, f'{spelling!r}: {r.text}')

    def test_H1_matching_user_sees_it(self):
        r = self.client.get('/debates', headers=auth(self.insider))
        self.assertIn(self.debate.id, [x['id'] for x in r.json()['debates']])

    def test_H2_matching_user_direct_access_allowed(self):
        r = self.client.get(f'/debates/{self.debate.id}', headers=auth(self.insider))
        self.assertEqual(r.status_code, 200, r.text)

    def test_H3_matching_user_spelling_variants_allowed(self):
        """The insider must be admitted regardless of how they wrote it."""
        for spelling in ('Las Condes', 'las condes', 'LAS  CONDES'):
            u = mk_user(self.db, country='CL', county=spelling)
            r = self.client.get(f'/debates/{self.debate.id}', headers=auth(u))
            self.assertEqual(r.status_code, 200, f'{spelling!r}: {r.text}')

    def test_H4_matching_user_reaches_vote_validation(self):
        r = self.client.post(f'/debates/{self.debate.id}/vote',
                             json={'option_index': 0}, headers=auth(self.insider))
        self.assertNotEqual(r.status_code, 403, r.text)


# ═══════════════════════════════════════════════════════════════════════
# I-J. Closed list — THE LIST IS THE AUDIENCE
# ═══════════════════════════════════════════════════════════════════════

def upload_closed_list(client, db, organizer, debate, rut_lines):
    """Drive the REAL upload endpoint with a REAL CSV body.

    CHANGE-002 remediation: the previous version of these tests inserted
    ClosedListEntry rows directly, pre-normalized with
    `hash_str('111111111', ...)`. That fixture happened to match what the
    lookup computed, so the suite was green while the actual product was
    broken end to end — the upload endpoint hashed the RAW line, so a real
    organizer's '12.345.678-9' never matched anybody. Fixture rows must never
    stand in for the write path they are supposed to prove.
    """
    body = ('\n'.join(rut_lines) + '\n').encode()
    return client.post(
        '/organizer/closed-list',
        data={'debate_id': str(debate.id)},
        files={'file': ('padron.csv', body, 'text/csv')},
        headers=auth(organizer),
    )


class TestClosedList(Base):
    """Closed list driven entirely through the real upload endpoint."""

    def setUp(self):
        super().setUp()
        self.organizer = mk_user(self.db, role='organizer')
        self.debate = mk_debate(self.db, scope_country='CL', scope_commune='',
                                creator_id=self.organizer.id)
        # Formatted RUTs, exactly as an organizer's spreadsheet exports them.
        self.member = mk_user(self.db, national_id='11.111.111-1')
        self.nonmember = mk_user(self.db, national_id='22.222.222-2')
        r = upload_closed_list(self.client, self.db, self.organizer,
                               self.debate, ['11.111.111-1'])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['total_added'], 1, r.text)
        self.db.refresh(self.debate)
        # Uploading a roll IS the act that closes the consultation.
        self.assertTrue(self.debate.is_closed_list)

    def test_I1_member_may_see_it(self):
        r = self.client.get(f'/debates/{self.debate.id}', headers=auth(self.member))
        self.assertEqual(r.status_code, 200, r.text)

    def test_I2_member_reaches_vote_validation(self):
        r = self.client.post(f'/debates/{self.debate.id}/vote',
                             json={'option_index': 0}, headers=auth(self.member))
        self.assertNotEqual(r.status_code, 403, r.text)

    def test_J1_non_member_is_denied_direct_access(self):
        r = self.client.get(f'/debates/{self.debate.id}', headers=auth(self.nonmember))
        self.assertEqual(r.status_code, 404, r.text)

    def test_J2_non_member_vote_is_rejected(self):
        r = self.client.post(f'/debates/{self.debate.id}/vote',
                             json={'option_index': 0}, headers=auth(self.nonmember))
        self.assertEqual(r.status_code, 403, r.text)

    def test_J3_non_member_does_not_see_it_in_listing(self):
        r = self.client.get('/debates', headers=auth(self.nonmember))
        self.assertNotIn(self.debate.id, [x['id'] for x in r.json()['debates']])

    def test_J4_user_without_national_id_is_unresolved_not_admitted(self):
        """Rule: UNKNOWN never becomes eligibility."""
        ghost = mk_user(self.db, national_id='')
        r = self.client.get(f'/debates/{self.debate.id}', headers=auth(ghost))
        self.assertEqual(r.status_code, 404, r.text)
        v = self.client.post(f'/debates/{self.debate.id}/vote',
                             json={'option_index': 0}, headers=auth(ghost))
        self.assertEqual(v.status_code, 403, v.text)

    def test_J5_closed_list_membership_is_the_audience(self):
        """JC rule 6: for a closed list the LIST defines the audience, so a
        member from a commune the consultation would otherwise exclude is
        still admitted — uploaded through the real endpoint."""
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes',
                      creator_id=org.id)
        u = mk_user(self.db, county='Conchali', national_id='33.333.333-3')
        r0 = upload_closed_list(self.client, self.db, org, d, ['33.333.333-3'])
        self.assertEqual(r0.status_code, 200, r0.text)

        r = self.client.get(f'/debates/{d.id}', headers=auth(u))
        self.assertEqual(r.status_code, 200,
                         f'closed-list member excluded by demographic targeting: {r.text}')
        v = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0}, headers=auth(u))
        self.assertNotEqual(v.status_code, 403, v.text)

    def test_J6_closed_list_does_not_admit_a_non_member_from_the_right_commune(self):
        """The other half of rule 6: the list must not EXPAND either. Someone
        who satisfies every demographic dimension but is not on the roll
        stays out."""
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes',
                      creator_id=org.id)
        insider = mk_user(self.db, county='Las Condes', national_id='44.444.444-4')
        r0 = upload_closed_list(self.client, self.db, org, d, ['55.555.555-5'])
        self.assertEqual(r0.status_code, 200, r0.text)

        self.assertEqual(
            self.client.get(f'/debates/{d.id}', headers=auth(insider)).status_code, 404)
        self.assertEqual(
            self.client.post(f'/debates/{d.id}/vote', json={'option_index': 0},
                             headers=auth(insider)).status_code, 403)


class TestClosedListNormalization(Base):
    """CRIT-1 regression: ONE normalization across write and read.

    Each of these fails against the pre-remediation code, where
    `upload_closed_list` hashed the raw CSV line and `_is_closed_list_member`
    hashed a stripped/uppercased form.
    """

    def _roll(self, uploaded, profile_nid):
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id)
        voter = mk_user(self.db, national_id=profile_nid)
        r = upload_closed_list(self.client, self.db, org, d, [uploaded])
        self.assertEqual(r.status_code, 200, r.text)
        return d, voter

    def test_formatted_rut_uploaded_matches_formatted_profile(self):
        d, voter = self._roll('12.345.678-9', '12.345.678-9')
        r = self.client.get(f'/debates/{d.id}', headers=auth(voter))
        self.assertEqual(r.status_code, 200,
                         f'formatted RUT did not match itself: {r.text}')

    def test_punctuation_and_case_variants_all_match(self):
        """Every ordinary rendering of one document is the same person."""
        for uploaded, profile in (
            ('12.345.678-9', '123456789'),
            ('123456789',    '12.345.678-9'),
            ('12345678-9',   '12.345.678-9'),
            (' 12.345.678-9 ', '12345678-9'),
            ('9.876.543-K',  '9876543k'),
            ('9876543-k',    '9.876.543-K'),
        ):
            with self.subTest(uploaded=uploaded, profile=profile):
                d, voter = self._roll(uploaded, profile)
                r = self.client.get(f'/debates/{d.id}', headers=auth(voter))
                self.assertEqual(r.status_code, 200,
                                 f'{uploaded!r} should match {profile!r}: {r.text}')

    def test_normalization_does_not_merge_different_documents(self):
        """Only presentation is stripped; distinct documents stay distinct.

        Note the deliberate boundary: normalization collapses by the
        alphanumeric sequence, so '1.234.567-89' and '12.345.678-9' DO
        collapse together — same characters, different punctuation, and the
        former is not a well-formed RUT anyway. What must never collapse is
        two genuinely different sequences.
        """
        d, _ = self._roll('12.345.678-9', '12.345.678-9')
        for different in ('12.345.678-0',   # different check digit
                          '12.345.679-9',   # different body
                          '1.345.678-9',    # a digit short
                          '112.345.678-9'): # a digit extra
            with self.subTest(nid=different):
                impostor = mk_user(self.db, national_id=different)
                self.assertEqual(
                    self.client.get(f'/debates/{d.id}',
                                    headers=auth(impostor)).status_code, 404,
                    f'{different!r} must not match the listed document')

    def test_upload_writes_the_canonical_hash(self):
        """The stored hash is the canonical one, and no plaintext is kept."""
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id)
        upload_closed_list(self.client, self.db, org, d, ['12.345.678-9'])
        entry = self.db.query(main.ClosedListEntry).filter(
            main.ClosedListEntry.debate_id == d.id).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.national_id_hash, main._closed_list_hash('12.345.678-9'))
        self.assertEqual(entry.national_id_hash, main._closed_list_hash('123456789'))
        # Privacy: the document itself is never stored.
        self.assertNotIn('12345678', entry.national_id_hash)
        self.assertNotIn('12.345.678-9', entry.national_id_hash)

    def test_legacy_raw_hashed_entries_still_grant_membership(self):
        """Rows written by the OLD code path hold the hash of the raw line.
        SHA-256 cannot be reversed, so membership is recovered by re-deriving
        renderings of the SAME user's own document."""
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id)
        d.is_closed_list = True
        legacy = mk_user(self.db, national_id='7.777.777-7')
        # Exactly what the pre-remediation upload wrote:
        self.db.add(main.ClosedListEntry(
            debate_id=d.id,
            national_id_hash=main.hash_str('7.777.777-7', prefix='closedlist:')))
        self.db.commit()
        r = self.client.get(f'/debates/{d.id}', headers=auth(legacy))
        self.assertEqual(r.status_code, 200,
                         f'legacy closed-list entry lost its member: {r.text}')

    def test_legacy_compatibility_does_not_admit_a_stranger(self):
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id)
        d.is_closed_list = True
        self.db.add(main.ClosedListEntry(
            debate_id=d.id,
            national_id_hash=main.hash_str('7.777.777-7', prefix='closedlist:')))
        self.db.commit()
        stranger = mk_user(self.db, national_id='8.888.888-8')
        self.assertEqual(
            self.client.get(f'/debates/{d.id}', headers=auth(stranger)).status_code, 404)

    def test_unusable_lines_are_skipped_not_hashed(self):
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id)
        r = upload_closed_list(self.client, self.db, org, d,
                               ['12.345.678-9', '---', '   ', '...'])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['total_added'], 1, r.text)
        # Blank lines were already ignored before reaching the usability
        # check; '---' and '...' are punctuation-only and normalize to ''.
        self.assertEqual(r.json()['skipped_unusable'], 2, r.text)
        self.assertEqual(
            self.db.query(main.ClosedListEntry)
                .filter(main.ClosedListEntry.debate_id == d.id).count(), 1)


# ═══════════════════════════════════════════════════════════════════════
# K. Invitations do not authorize
# ═══════════════════════════════════════════════════════════════════════

class TestInvitationCannotAuthorize(Base):

    def test_K1_ordinary_invite_cannot_authorize_ineligible_user(self):
        """Holding an invite token changes nothing at the destination."""
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        outsider = mk_user(self.db, country='CL', county='Conchali')
        token = 'a' * 32
        # Direct access carrying the invitation in every plausible position.
        for url in (f'/debates/{d.id}?invite={token}',
                    f'/debates/{d.id}?invite={token}&debate={d.id}'):
            r = self.client.get(url, headers=auth(outsider))
            self.assertEqual(r.status_code, 404, f'{url}: {r.text}')
        r = self.client.post(f'/debates/{d.id}/vote?invite={token}',
                             json={'option_index': 0}, headers=auth(outsider))
        self.assertEqual(r.status_code, 403, r.text)

    def test_K2_invite_filtering_helper_uses_canonical_decision(self):
        """The send path must classify invitees with the canonical evaluator,
        including closed-list semantics — not a parallel rule."""
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        outsider = mk_user(self.db, country='CL', county='Conchali')
        insider = mk_user(self.db, country='CL', county='Las Condes')
        self.assertFalse(main._consultation_decision(outsider, d, self.db).allowed)
        self.assertEqual(main._consultation_decision(outsider, d, self.db).verdict,
                         E.INELIGIBLE)
        self.assertTrue(main._consultation_decision(insider, d, self.db).allowed)

    def test_K3_unresolved_invitee_is_not_converted_into_eligible(self):
        closed = mk_debate(self.db, is_closed_list=True, scope_country='CL')
        ghost = mk_user(self.db, national_id='')
        dec = main._consultation_decision(ghost, closed, self.db)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.UNRESOLVED)


# ═══════════════════════════════════════════════════════════════════════
# L-O. Campaign authorization
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignAuthorization(Base):

    def test_L1_anonymous_advertiser_campaign_creation_is_rejected(self):
        r = self.client.post('/advertiser/campaigns', json=campaign_payload())
        self.assertIn(r.status_code, (401, 403), r.text)
        self.assertEqual(
            self.db.query(main.AdCampaign)
                .filter(main.AdCampaign.title == 'Nueva campaña').count(), 0)

    def test_L2_anonymous_marketer_campaign_creation_is_rejected(self):
        r = self.client.post('/marketer/campaigns', json=campaign_payload())
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_L3_anonymous_creation_does_not_manufacture_a_marketer_identity(self):
        """The old code auto-created an APPROVED MarketerProfile for the
        anonymous caller. Nothing may be minted by a rejected request."""
        email = 'ghost-marketer@test.local'
        before_u = self.db.query(main.User).filter(main.User.email == email).count()
        before_p = self.db.query(main.MarketerProfile).count()
        r = self.client.post('/marketer/campaigns',
                             json=campaign_payload(advertiser_email=email))
        self.assertIn(r.status_code, (401, 403), r.text)
        self.db.expire_all()
        self.assertEqual(
            self.db.query(main.User).filter(main.User.email == email).count(),
            before_u, 'anonymous request created a User')
        self.assertEqual(self.db.query(main.MarketerProfile).count(), before_p,
                         'anonymous request created a MarketerProfile')

    def test_L4_plain_voter_cannot_create_a_campaign(self):
        u = mk_user(self.db, role='voter')
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(advertiser_email=u.email),
                             headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_L5_pending_marketer_cannot_create_a_campaign(self):
        u = mk_marketer(self.db, status='pending')
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(advertiser_email=u.email),
                             headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_L6_suspended_marketer_cannot_create_a_campaign(self):
        u = mk_marketer(self.db, status='suspended')
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(advertiser_email=u.email),
                             headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_M1_approved_marketer_may_create_a_campaign(self):
        u = mk_marketer(self.db, status='approved')
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(advertiser_email=u.email),
                             headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('campaign_id', r.json())

    def test_M2_campaign_is_bound_to_the_signing_identity(self):
        """An approved marketer may not create a campaign under someone
        else's advertiser email — that email IS the ownership key."""
        u = mk_marketer(self.db, status='approved')
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(advertiser_email='victim@test.local'),
                             headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_N1_unauthorized_user_cannot_modify_another_advertiser_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        attacker = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email)
        r = self.client.patch(f'/advertiser/campaigns/{c.id}',
                              json=campaign_payload(advertiser_email=owner.email,
                                                    campaign_title='HIJACKED'),
                              headers=auth(attacker))
        self.assertEqual(r.status_code, 403, r.text)
        self.db.refresh(c)
        self.assertNotEqual(c.title, 'HIJACKED')

    def test_N2_owner_may_modify_their_own_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email)
        r = self.client.patch(f'/advertiser/campaigns/{c.id}',
                              json=campaign_payload(advertiser_email=owner.email,
                                                    campaign_title='Actualizada'),
                              headers=auth(owner))
        self.assertEqual(r.status_code, 200, r.text)
        self.db.refresh(c)
        self.assertEqual(c.title, 'Actualizada')

    def test_N3_plain_voter_cannot_modify_any_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        voter = mk_user(self.db, role='voter')
        c = mk_campaign(self.db, advertiser_email=owner.email)
        r = self.client.patch(f'/advertiser/campaigns/{c.id}',
                              json=campaign_payload(advertiser_email=owner.email),
                              headers=auth(voter))
        self.assertEqual(r.status_code, 403, r.text)

    def test_O1_anonymous_pause_is_rejected(self):
        c = mk_campaign(self.db, is_active=True)
        r = self.client.put(f'/advertiser/campaigns/{c.id}/pause')
        self.assertIn(r.status_code, (401, 403), r.text)
        self.db.refresh(c)
        self.assertTrue(c.is_active, 'anonymous caller toggled is_active')

    def test_O2_anonymous_reactivation_is_rejected(self):
        """The route TOGGLES, so on a paused campaign it is a reactivation."""
        c = mk_campaign(self.db, is_active=False)
        r = self.client.put(f'/advertiser/campaigns/{c.id}/pause')
        self.assertIn(r.status_code, (401, 403), r.text)
        self.db.refresh(c)
        self.assertFalse(c.is_active, 'anonymous caller REACTIVATED a campaign')

    def test_O3_other_advertiser_cannot_pause_your_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        attacker = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email, is_active=True)
        r = self.client.put(f'/advertiser/campaigns/{c.id}/pause',
                            headers=auth(attacker))
        self.assertEqual(r.status_code, 403, r.text)
        self.db.refresh(c)
        self.assertTrue(c.is_active)

    def test_O4_owner_may_pause_their_own_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email, is_active=True)
        r = self.client.put(f'/advertiser/campaigns/{c.id}/pause',
                            headers=auth(owner))
        self.assertEqual(r.status_code, 200, r.text)
        self.db.refresh(c)
        self.assertFalse(c.is_active)

    def test_O5_budget_cannot_be_drained_from_another_advertiser_campaign(self):
        """/payments/return-from-campaign credits the CALLER's account."""
        owner = mk_marketer(self.db, status='approved')
        attacker = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email)
        r = self.client.post(f'/payments/return-from-campaign/{c.id}',
                             headers=auth(attacker))
        self.assertEqual(r.status_code, 403, r.text)

    def test_O6_budget_cannot_be_allocated_to_another_advertiser_campaign(self):
        owner = mk_marketer(self.db, status='approved')
        attacker = mk_marketer(self.db, status='approved')
        c = mk_campaign(self.db, advertiser_email=owner.email)
        r = self.client.post('/payments/allocate-to-campaign',
                             json={'campaign_id': c.id, 'credits': 10.0},
                             headers=auth(attacker))
        self.assertEqual(r.status_code, 403, r.text)


# ═══════════════════════════════════════════════════════════════════════
# P-Q. Campaign targeting and billing
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignServingAndBilling(Base):

    def test_P1_target_debate_ids_cannot_bypass_campaign_targeting(self):
        """Association is placement, never authorization."""
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db, target_communes='Las Condes',
                        target_debate_ids=str(d.id))
        outsider = mk_user(self.db, country='CL', county='Conchali')
        dec = main._campaign_decision(outsider, c, d, self.db)
        self.assertFalse(dec.allowed, f'target_debate_ids granted access: {dec}')

    def test_P2_target_debate_ids_does_not_bypass_at_the_billing_route(self):
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db, target_communes='Las Condes',
                        target_debate_ids=str(d.id))
        outsider = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.post('/ads/view',
                             json={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(outsider))
        self.assertEqual(r.status_code, 403, r.text)

    def test_Q1_ineligible_impression_is_not_billed(self):
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db, target_communes='Las Condes')
        outsider = mk_user(self.db, country='CL', county='Conchali')
        before = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count()
        r = self.client.post('/ads/view',
                             json={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(outsider))
        self.assertEqual(r.status_code, 403, r.text)
        self.db.expire_all()
        after = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count()
        self.assertEqual(before, after, 'an ineligible impression was billed')

    def test_Q2_anonymous_impression_is_not_billed(self):
        c = mk_campaign(self.db)
        r = self.client.post('/ads/view', json={'campaign_id': c.id})
        self.assertIn(r.status_code, (401, 403), r.text)
        self.assertEqual(self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count(), 0)

    def test_Q3_impression_inside_an_unviewable_consultation_is_not_billed(self):
        """Even if the campaign matches the user, the consultation must not."""
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        c = mk_campaign(self.db)  # untargeted campaign, matches everyone
        outsider = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.post('/ads/view',
                             json={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(outsider))
        self.assertIn(r.status_code, (403, 404), r.text)
        self.assertEqual(self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count(), 0)

    def test_Q4_client_supplied_demographics_are_ignored(self):
        """The body used to set the billed demographics. It must not."""
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db)
        u = mk_user(self.db, country='CL', county='Las Condes', gender='M')
        r = self.client.post('/ads/view',
                             json={'campaign_id': c.id, 'debate_id': d.id,
                                   'gender': 'F', 'county': 'Vitacura',
                                   'country': 'AR', 'age_group': '99+'},
                             headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        log = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).first()
        self.assertIsNotNone(log)
        # Server profile wins over every field the client supplied.
        self.assertEqual(log.gender, 'M')
        self.assertEqual(log.county, 'Las Condes')
        self.assertEqual(log.country, 'CL')

    def test_Q6_second_billing_path_rejects_anonymous(self):
        """/ads/impression also deducts credits. Closing /ads/view alone
        would have left the same abuse one route away."""
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db)
        r = self.client.post('/ads/impression',
                             params={'campaign_id': c.id, 'debate_id': d.id})
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_Q7_second_billing_path_rejects_ineligible_user(self):
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db, target_communes='Las Condes')
        outsider = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.post('/ads/impression',
                             params={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(outsider))
        self.assertEqual(r.status_code, 403, r.text)

    def test_Q8_second_billing_path_respects_consultation_access(self):
        d = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes')
        c = mk_campaign(self.db)
        outsider = mk_user(self.db, country='CL', county='Conchali')
        r = self.client.post('/ads/impression',
                             params={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(outsider))
        self.assertIn(r.status_code, (403, 404), r.text)

    def test_Q5_eligible_impression_is_billed(self):
        d = mk_debate(self.db, scope_country='CL')
        c = mk_campaign(self.db)
        u = mk_user(self.db, country='CL', county='Las Condes')
        r = self.client.post('/ads/view',
                             json={'campaign_id': c.id, 'debate_id': d.id},
                             headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count(), 1)


# ═══════════════════════════════════════════════════════════════════════
# R-S. Results visibility
# ═══════════════════════════════════════════════════════════════════════

class TestResultsVisibility(Base):

    def test_R1_restricted_results_deny_unauthorized_user(self):
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id)
        other = mk_user(self.db)
        r = self.client.get(f'/debates/{d.id}/results', headers=auth(other))
        self.assertIn(r.status_code, (403, 404), r.text)

    def test_R2_restricted_results_deny_anonymous(self):
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id)
        r = self.client.get(f'/debates/{d.id}/results')
        self.assertIn(r.status_code, (401, 403, 404), r.text)

    def test_R3_restricted_results_allow_the_creator(self):
        """Closed consultation, so the separate 'you must vote first' gate
        (which applies only while a consultation is live) does not mask the
        visibility decision under test."""
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id, status='closed')
        r = self.client.get(f'/debates/{d.id}/results', headers=auth(creator))
        self.assertEqual(r.status_code, 200, r.text)

    def test_R4_restricted_results_allow_admin(self):
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id, status='closed')
        admin = mk_user(self.db, role='admin')
        r = self.client.get(f'/debates/{d.id}/results', headers=auth(admin))
        self.assertEqual(r.status_code, 200, r.text)

    def test_R6_vote_first_gate_is_separate_from_visibility(self):
        """On a LIVE restricted consultation the creator passes the
        visibility gate and is then stopped only by the ordinary
        'vote first' rule — a 403, never the non-disclosing 404."""
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id, status='live')
        r = self.client.get(f'/debates/{d.id}/results', headers=auth(creator))
        self.assertEqual(r.status_code, 403, r.text)
        outsider = mk_user(self.db)
        r2 = self.client.get(f'/debates/{d.id}/results', headers=auth(outsider))
        self.assertEqual(r2.status_code, 404, r2.text)

    def test_R5_restricted_public_results_page_denies_outsider(self):
        creator = mk_user(self.db)
        d = mk_debate(self.db, results_visibility='restricted',
                      creator_id=creator.id)
        other = mk_user(self.db)
        r = self.client.get(f'/r/{d.id}', headers=auth(other))
        self.assertIn(r.status_code, (403, 404), r.text)

    # NOTE — JC's final rule changed what "public results" means. Publishing
    # results no longer publishes the CONSULTATION. These two tests used to
    # assert that any results_visibility='public' consultation was readable by
    # anyone; a country-scoped consultation IS targeted, so that expectation
    # is exactly the back door the remediation closed. They now assert the
    # rule as decided: unrestricted stays fully public, targeted does not.

    def test_S1_unrestricted_public_results_are_fully_readable(self):
        d = mk_debate(self.db, results_visibility='public', status='closed',
                      scope_country='GLOBAL', title='ABIERTA A TODOS')
        r = self.client.get(f'/debates/{d.id}/results')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['debate']['title'], 'ABIERTA A TODOS')
        self.assertFalse(r.json().get('content_restricted'))

    def test_S1b_targeted_public_results_expose_aggregates_only(self):
        d = mk_debate(self.db, results_visibility='public', status='closed',
                      scope_country='CL', title='SOLO CHILE')
        r = self.client.get(f'/debates/{d.id}/results')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get('content_restricted'))
        self.assertNotIn('SOLO CHILE', r.text)
        self.assertIn('total_votes', r.json()['debate'])

    def test_S2_unrestricted_results_page_remains_reachable(self):
        d = mk_debate(self.db, results_visibility='public',
                      scope_country='GLOBAL', title='ABIERTA A TODOS')
        r = self.client.get(f'/r/{d.id}')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('ABIERTA A TODOS', r.text)

    def test_S2b_targeted_results_page_is_not_anonymously_reachable(self):
        d = mk_debate(self.db, results_visibility='public',
                      scope_country='CL', title='SOLO CHILE')
        r = self.client.get(f'/r/{d.id}')
        self.assertEqual(r.status_code, 404, r.text[:120])
        self.assertNotIn('SOLO CHILE', r.text)
        # …and an eligible Chilean still sees it.
        u = mk_user(self.db, country='CL')
        ok = self.client.get(f'/r/{d.id}', headers=auth(u))
        self.assertEqual(ok.status_code, 200, ok.text[:120])
        self.assertIn('SOLO CHILE', ok.text)


# ═══════════════════════════════════════════════════════════════════════
# Admin read-only audits (must not write)
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# HIGH-1 — public results must not be a back door into a restricted
# consultation.
#
# JC final rule: if a consultation is restricted by targeting or closed-list
# membership, an ineligible/unauthorized caller must NOT obtain its protected
# content merely because results_visibility == 'public'.
#
# Every test here fails against the pre-remediation code, where
# /debates/{id}/results and /r/{id} returned the full format_debate(...)
# payload — title, context, options, scope_country, scope_commune,
# target_gender, target_age_* — to anyone at all.
# ═══════════════════════════════════════════════════════════════════════

PROTECTED_CONTENT_KEYS = ('title', 'context', 'options', 'option_images',
                          'scope_country', 'scope_commune', 'target_gender',
                          'target_age_min', 'target_age_max', 'inst_name',
                          'results')


class TestResultsNotABackDoor(Base):

    def setUp(self):
        super().setUp()
        self.creator = mk_user(self.db, role='organizer')
        self.targeted = mk_debate(
            self.db, scope_country='CL', scope_commune='Las Condes',
            results_visibility='public', status='closed',
            creator_id=self.creator.id,
            title='PADRON SECRETO Las Condes', context='CONTEXTO RESERVADO')
        self.outsider = mk_user(self.db, country='CL', county='Conchali')
        self.insider = mk_user(self.db, country='CL', county='Las Condes')

    def _assert_no_protected_content(self, resp, where):
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json().get('debate', {})
        for k in PROTECTED_CONTENT_KEYS:
            self.assertNotIn(k, payload, f'{where}: leaked {k!r}')
        self.assertNotIn('SECRETO', resp.text, f'{where}: leaked the title')
        self.assertNotIn('RESERVADO', resp.text, f'{where}: leaked the context')
        self.assertNotIn('Las Condes', resp.text, f'{where}: leaked the targeting')
        self.assertTrue(resp.json().get('content_restricted'), where)

    # ── /debates/{id}/results ──────────────────────────────────────────
    def test_anonymous_gets_no_protected_content_from_results(self):
        r = self.client.get(f'/debates/{self.targeted.id}/results')
        self._assert_no_protected_content(r, 'anonymous /results')

    def test_ineligible_authenticated_gets_no_protected_content(self):
        r = self.client.get(f'/debates/{self.targeted.id}/results',
                            headers=auth(self.outsider))
        self._assert_no_protected_content(r, 'Conchali /results')

    def test_no_inversion_anonymous_vs_authenticated_ineligible(self):
        """An anonymous caller must never learn MORE than an authenticated
        ineligible one — the exact inversion this remediation had to avoid."""
        anon = self.client.get(f'/debates/{self.targeted.id}/results')
        inelig = self.client.get(f'/debates/{self.targeted.id}/results',
                                 headers=auth(self.outsider))
        self.assertEqual(anon.status_code, inelig.status_code)
        self.assertEqual(set(anon.json().get('debate', {})),
                         set(inelig.json().get('debate', {})))

    def test_no_inversion_on_a_LIVE_targeted_consultation(self):
        """The live path is where the inversion nearly happened: the
        'you must vote first' gate only fires when a user is present."""
        live = mk_debate(self.db, scope_country='CL', scope_commune='Las Condes',
                         results_visibility='public', status='live',
                         creator_id=self.creator.id, title='LIVE SECRETO')
        anon = self.client.get(f'/debates/{live.id}/results')
        inelig = self.client.get(f'/debates/{live.id}/results',
                                 headers=auth(self.outsider))
        self.assertEqual(anon.status_code, inelig.status_code,
                         f'anon={anon.status_code} inelig={inelig.status_code}')
        self.assertNotIn('SECRETO', anon.text)
        self.assertNotIn('SECRETO', inelig.text)

    def test_eligible_caller_still_gets_the_full_consultation(self):
        r = self.client.get(f'/debates/{self.targeted.id}/results',
                            headers=auth(self.insider))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['debate']['title'], 'PADRON SECRETO Las Condes')
        self.assertIn('options', r.json()['debate'])
        self.assertFalse(r.json().get('content_restricted'))

    def test_creator_still_gets_the_full_consultation(self):
        r = self.client.get(f'/debates/{self.targeted.id}/results',
                            headers=auth(self.creator))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['debate']['title'], 'PADRON SECRETO Las Condes')

    # ── /r/{id} share page ─────────────────────────────────────────────
    def test_share_page_denies_anonymous_for_targeted_consultation(self):
        r = self.client.get(f'/r/{self.targeted.id}')
        self.assertEqual(r.status_code, 404, r.text[:200])
        self.assertNotIn('SECRETO', r.text)
        self.assertNotIn('RESERVADO', r.text)

    def test_share_page_denies_ineligible_user(self):
        r = self.client.get(f'/r/{self.targeted.id}', headers=auth(self.outsider))
        self.assertEqual(r.status_code, 404, r.text[:200])
        self.assertNotIn('SECRETO', r.text)

    def test_share_page_allows_eligible_user(self):
        r = self.client.get(f'/r/{self.targeted.id}', headers=auth(self.insider))
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertIn('SECRETO', r.text)

    # ── closed list ────────────────────────────────────────────────────
    def test_closed_list_non_member_gets_no_content_from_results(self):
        org = mk_user(self.db, role='organizer')
        d = mk_debate(self.db, scope_country='CL', creator_id=org.id,
                      results_visibility='public', status='closed',
                      title='PADRON CERRADO SECRETO')
        member = mk_user(self.db, national_id='66.666.666-6')
        nonmember = mk_user(self.db, national_id='77.777.777-1')
        self.assertEqual(
            upload_closed_list(self.client, self.db, org, d,
                               ['66.666.666-6']).status_code, 200)

        r = self.client.get(f'/debates/{d.id}/results', headers=auth(nonmember))
        self._assert_no_protected_content(r, 'closed-list non-member /results')
        self.assertEqual(self.client.get(f'/r/{d.id}',
                                         headers=auth(nonmember)).status_code, 404)
        self.assertEqual(self.client.get(f'/r/{d.id}').status_code, 404)
        # …and the member is unaffected.
        m = self.client.get(f'/debates/{d.id}/results', headers=auth(member))
        self.assertEqual(m.status_code, 200, m.text)
        self.assertEqual(m.json()['debate']['title'], 'PADRON CERRADO SECRETO')

    # ── genuinely public consultation keeps working ────────────────────
    def test_unrestricted_consultation_remains_fully_public(self):
        """No targeting at all => nothing to protect; historic share-link
        behaviour is preserved exactly."""
        d = mk_debate(self.db, scope_country='GLOBAL', scope_commune='',
                      target_gender='all', target_age_min=13, target_age_max=99,
                      target_se_tiers='A,B,C,D', results_visibility='public',
                      status='closed', title='CONSULTA ABIERTA')
        r = self.client.get(f'/debates/{d.id}/results')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['debate']['title'], 'CONSULTA ABIERTA')
        self.assertIn('options', r.json()['debate'])
        self.assertFalse(r.json().get('content_restricted'))
        page = self.client.get(f'/r/{d.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('CONSULTA ABIERTA', page.text)

    # ── restricted results_visibility is unchanged ─────────────────────
    def test_restricted_visibility_still_404s_for_outsiders(self):
        d = mk_debate(self.db, results_visibility='restricted', status='closed',
                      creator_id=self.creator.id, title='SOLO CREADOR')
        self.assertEqual(self.client.get(f'/debates/{d.id}/results').status_code, 404)
        self.assertEqual(self.client.get(f'/debates/{d.id}/results',
                                         headers=auth(self.outsider)).status_code, 404)
        ok = self.client.get(f'/debates/{d.id}/results', headers=auth(self.creator))
        self.assertEqual(ok.status_code, 200, ok.text)

    # ── pilot dashboard ────────────────────────────────────────────────
    def test_pilot_dashboard_denies_anonymous_and_ineligible(self):
        self.assertEqual(
            self.client.get(f'/pilot/{self.targeted.id}/live').status_code, 404)
        self.assertEqual(
            self.client.get(f'/pilot/{self.targeted.id}/live',
                            headers=auth(self.outsider)).status_code, 404)

    def test_pilot_dashboard_allows_the_creator(self):
        r = self.client.get(f'/pilot/{self.targeted.id}/live',
                            headers=auth(self.creator))
        self.assertEqual(r.status_code, 200, r.text[:200])

    # ── no alternate route defeats this ────────────────────────────────
    def test_no_results_route_leaks_the_targeted_consultation(self):
        """Sweep every results-ish route as an anonymous caller."""
        for path in (f'/debates/{self.targeted.id}/results',
                     f'/r/{self.targeted.id}',
                     f'/pilot/{self.targeted.id}/live',
                     f'/debates/{self.targeted.id}',
                     f'/debates/{self.targeted.id}/opinions',
                     f'/debates/{self.targeted.id}/comments'):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertNotIn('SECRETO', r.text, f'{path} leaked the title')
                self.assertNotIn('RESERVADO', r.text, f'{path} leaked the context')


# ═══════════════════════════════════════════════════════════════════════
# MED-1 — internal duplicate detection
# ═══════════════════════════════════════════════════════════════════════

class TestInternalDedupEndpoint(Base):

    def test_dedup_endpoint_rejects_anonymous(self):
        r = self.client.get('/internal/debates/dedup')
        self.assertEqual(r.status_code, 403, r.text)

    def test_dedup_endpoint_rejects_a_normal_user_token(self):
        u = mk_user(self.db)
        r = self.client.get('/internal/debates/dedup', headers=auth(u))
        self.assertEqual(r.status_code, 403, r.text)

    def test_dedup_endpoint_rejects_a_wrong_secret(self):
        r = self.client.get('/internal/debates/dedup',
                            headers={'X-Agent-Secret': 'nope'})
        self.assertEqual(r.status_code, 403, r.text)

    def test_agent_secret_returns_titles_for_dedup(self):
        d = mk_debate(self.db, title='Consulta sobre transporte publico')
        r = self.client.get('/internal/debates/dedup',
                            headers={'X-Agent-Secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        titles = {x['title'] for x in r.json()['debates']}
        self.assertIn('Consulta sobre transporte publico', titles)

    def test_dedup_sees_consultations_regardless_of_targeting(self):
        """Dedup must find a Las Condes consultation even though no
        particular user is eligible for it — that is the whole point."""
        d = mk_debate(self.db, scope_commune='Las Condes',
                      title='Consulta exclusiva de Las Condes')
        r = self.client.get('/internal/debates/dedup',
                            headers={'X-Agent-Secret': ADMIN_SECRET})
        self.assertIn(d.id, [x['id'] for x in r.json()['debates']])

    def test_dedup_payload_carries_no_consultation_body(self):
        """Narrow projection: enough to compare titles, nothing more."""
        mk_debate(self.db, title='Otra consulta')
        r = self.client.get('/internal/debates/dedup',
                            headers={'X-Agent-Secret': ADMIN_SECRET})
        row = r.json()['debates'][0]
        self.assertEqual(set(row), {'id', 'title', 'status', 'scope_country',
                                    'created_at', 'closes_at'})
        for forbidden in ('context', 'options', 'results', 'total_votes'):
            self.assertNotIn(forbidden, row)

    def test_public_debates_route_is_still_closed(self):
        """Restoring dedup must not have reopened /debates."""
        self.assertIn(self.client.get('/debates').status_code, (401, 403))
        self.assertEqual(
            self.client.get('/debates',
                            headers={'X-Agent-Secret': ADMIN_SECRET}).status_code, 403)


# ═══════════════════════════════════════════════════════════════════════
# PPP resolver — the PRIMARY database source, which the rest of the suite
# never exercises because `world_countries` does not exist in the test DB.
#
# JC: THE MARKET THERMOMETER IS PPP/PPA PER CAPITA. NOMINAL GDP PER CAPITA
# MUST NOT BE SUBSTITUTED.
#
# The figures below are fixtures chosen to be unambiguous about WHICH source
# won; they are not presented as authoritative economic data and nothing is
# written to production.
# ═══════════════════════════════════════════════════════════════════════

class TestPPPResolver(Base):

    def setUp(self):
        super().setUp()
        self.db.execute(main.text(
            'CREATE TABLE IF NOT EXISTS world_countries '
            '(iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)'))
        self.db.execute(main.text('DELETE FROM world_countries'))
        self.db.commit()
        self.addCleanup(self._drop)

    def _drop(self):
        try:
            self.db.execute(main.text('DROP TABLE IF EXISTS world_countries'))
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _store(self, iso2, value):
        self.db.execute(
            main.text('INSERT INTO world_countries (iso2, gdp_per_capita_usd) '
                      'VALUES (:c, :v)'), {'c': iso2, 'v': value})
        self.db.commit()

    def test_primary_db_source_is_used_and_labelled_ppp(self):
        self._store('CL', 31234.0)
        value, source = main._country_per_capita_ppp_usd('CL', self.db)
        self.assertEqual(value, 31234.0)
        self.assertEqual(source, main._elig.PPP_SOURCE_DB)
        self.assertIn('NY.GNP.PCAP.PP.CD', source)

    def test_primary_source_wins_over_the_reference_table(self):
        ref = main._ppp_reference_table().get('CL')
        self.assertIsNotNone(ref, 'CL missing from the PPP reference table')
        self._store('CL', float(ref) + 7777.0)
        value, source = main._country_per_capita_ppp_usd('CL', self.db)
        self.assertEqual(value, float(ref) + 7777.0)
        self.assertEqual(source, main._elig.PPP_SOURCE_DB)

    def test_reference_fallback_is_ppp_not_nominal(self):
        """No stored row -> the in-repo PPP table, never a nominal figure."""
        value, source = main._country_per_capita_ppp_usd('CL', self.db)
        self.assertEqual(source, main._elig.PPP_SOURCE_REFERENCE)
        self.assertEqual(value, float(main._ppp_reference_table()['CL']))
        # Chile's nominal GDP per capita is ~15-17k; PPP is ~25-30k. A value
        # down at nominal level would mean the wrong series was substituted.
        self.assertGreater(value, 20000)

    def test_missing_everywhere_is_unknown_and_denies(self):
        value, source = main._country_per_capita_ppp_usd('ZZ', self.db)
        self.assertIsNone(value)
        self.assertEqual(source, '')
        reason = main._elig._check_market_per_capita(value, 5000)
        self.assertEqual(reason.outcome, main._elig.UNKNOWN)
        self.assertFalse(main._elig._combine([reason]).allowed)

    def test_null_stored_value_falls_back_and_never_becomes_zero(self):
        """A NULL row must not resolve to 0.0 — that would silently FAIL
        every market threshold instead of falling back to PPP."""
        self._store('CL', None)
        value, source = main._country_per_capita_ppp_usd('CL', self.db)
        self.assertEqual(source, main._elig.PPP_SOURCE_REFERENCE)
        self.assertIsNotNone(value)
        self.assertNotEqual(value, 0.0)

    def test_end_to_end_market_threshold_uses_the_stored_ppp_value(self):
        """Full HTTP path: the stored PPP figure decides eligibility."""
        self._store('CL', 31234.0)
        rich = mk_debate(self.db, scope_country='CL', min_per_capita_usd=30000.0)
        poor = mk_debate(self.db, scope_country='CL', min_per_capita_usd=40000.0)
        u = mk_user(self.db, country='CL')
        self.assertEqual(
            self.client.get(f'/debates/{rich.id}', headers=auth(u)).status_code, 200)
        self.assertEqual(
            self.client.get(f'/debates/{poor.id}', headers=auth(u)).status_code, 404)

    def test_unknown_country_denies_a_market_thresholded_consultation(self):
        d = mk_debate(self.db, scope_country='GLOBAL', min_per_capita_usd=5000.0)
        u = mk_user(self.db, country='ZZ')
        r = self.client.get(f'/debates/{d.id}', headers=auth(u))
        self.assertEqual(r.status_code, 404, r.text)
        dec = main._consultation_decision(u, d, self.db)
        self.assertEqual(dec.verdict, E.UNRESOLVED)
        self.assertIn('market_per_capita', dec.blocking_dimensions())

    def test_resolver_never_reads_a_nominal_column(self):
        """Structural guard over EXECUTABLE code only.

        The docstring deliberately contains the word 'nominal' (it explains
        why nominal must never be substituted), so the prose is stripped
        before asserting — otherwise the test would flag the very comment
        that documents the rule.
        """
        import ast as _ast
        import inspect
        tree = _ast.parse(inspect.getsource(main._country_per_capita_ppp_usd))
        fn = tree.body[0]
        if (fn.body and isinstance(fn.body[0], _ast.Expr)
                and isinstance(fn.body[0].value, _ast.Constant)):
            fn.body = fn.body[1:]                     # drop the docstring
        code = _ast.dump(_ast.Module(body=fn.body, type_ignores=[]))
        self.assertIn('gdp_per_capita_usd', code)
        for nominal in ('NY.GDP.PCAP.CD', 'gdp_nominal', 'nominal_gdp',
                        'estimated_income_usd', 'income_index'):
            self.assertNotIn(nominal, code,
                             f'resolver touches {nominal!r} in executable code')


class TestAdminAudits(Base):

    def test_ppp_audit_requires_the_admin_secret(self):
        r = self.client.get('/admin/ppp-audit', params={'secret': 'wrong'})
        self.assertEqual(r.status_code, 403, r.text)

    def test_ppp_audit_returns_a_report(self):
        r = self.client.get('/admin/ppp-audit', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('counts', r.json())

    def test_legacy_income_audit_requires_the_admin_secret(self):
        r = self.client.get('/admin/legacy-income-audit', params={'secret': 'wrong'})
        self.assertEqual(r.status_code, 403, r.text)

    def test_legacy_income_audit_is_read_only(self):
        c = mk_campaign(self.db, target_income_min=500.0, target_income_max=2000.0)
        before = (c.target_income_min, c.target_income_max)
        r = self.client.get('/admin/legacy-income-audit',
                            params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.db.refresh(c)
        self.assertEqual((c.target_income_min, c.target_income_max), before,
                         'the audit modified data')
        ids = [row['id'] for row in r.json().get('requires_review', [])]
        self.assertIn(c.id, ids)


if __name__ == '__main__':
    unittest.main()
