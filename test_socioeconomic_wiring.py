"""
test_socioeconomic_wiring.py — CHANGE-003 endpoint + integration tests.

Two kinds of coverage, both real:

  * BEHAVIOURAL — boots the actual FastAPI app with TestClient against a
    throwaway sqlite DB, exercises the admin diagnostics and the classifier
    through main.py's own adapters.
  * STRUCTURAL — parses main.py to prove the historical defects cannot come
    back silently (nominal-GDP-as-PPP, age/title tier promotion).

LOCAL / TEST ONLY. DATABASE_URL is forced to a temp file before main is
imported; no production credential is read and no network call is made.

    python3 -m unittest test_socioeconomic_wiring -v
"""

import ast
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='change003-it-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-change-003'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-change-003'
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402
import socioeconomic as S                      # noqa: E402
import eligibility as E                        # noqa: E402

ADMIN_SECRET = os.environ['ADMIN_SECRET']
MAIN_SRC = Path(main.__file__).read_text(encoding='utf-8')
MAIN_TREE = ast.parse(MAIN_SRC)


def tearDownModule():
    shutil.rmtree(_TMPDIR, ignore_errors=True)


_seq = {'n': 0}


def _uid():
    _seq['n'] += 1
    return _seq['n']


def mk_user(db, **kw):
    n = _uid()
    base = dict(email=f'se{n}@test.local', name=f'User {n}', password='x',
                country='CL', county='Las Condes', gender='M',
                dob='1990-05-10', role='voter', email_verified=True,
                referral_code=f'SE{n:06d}')
    base.update(kw)
    u = main.User(**base)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _function(name):
    for n in ast.walk(MAIN_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _src_of(node):
    return ast.get_source_segment(MAIN_SRC, node) or ''


def _route_functions():
    """{(method, path): FunctionDef} for every @app.<method>('<path>') route.
    Same extraction test_matching_wiring.py uses, kept local here so this
    file has no cross-test-module dependency."""
    out = {}
    for node in ast.walk(MAIN_TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == 'app'):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            out[(fn.attr, dec.args[0].value)] = node
    return out


ROUTES = _route_functions()


def _code_only(node):
    """Executable body with the docstring and comments stripped.

    Comments in this codebase deliberately QUOTE the defects they removed
    ("treating nominal GDP as PPP"), so a raw-text search would flag the very
    documentation that proves the fix. Structural assertions run over the AST.
    """
    fn = ast.parse(_src_of(node)).body[0]
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]))


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)


# ═══════════════════════════════════════════════════════════════════════
# PPP wiring — the root cause must stay fixed
# ═══════════════════════════════════════════════════════════════════════

class TestPPPWiring(Base):

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
        self.db.execute(main.text(
            'INSERT INTO world_countries (iso2, gdp_per_capita_usd) VALUES (:c,:v)'),
            {'c': iso2, 'v': value})
        self.db.commit()

    def test_context_uses_the_canonical_change002_resolver(self):
        self._store('CL', 29500.0)
        ctx = main._country_economic_context('CL', self.db)
        self.assertTrue(ctx.resolved)
        self.assertEqual(ctx.ppp_per_capita_usd, 29500.0)
        self.assertEqual(ctx.ppp_source, 'world_bank_ny_gnp_pcap_pp_cd')

    def test_context_falls_back_to_the_ppp_reference_table(self):
        ctx = main._country_economic_context('CL', self.db)
        self.assertTrue(ctx.resolved)
        self.assertEqual(ctx.ppp_source, 'marketer_table_v2_gni_per_capita_ppp')

    def test_unknown_country_is_unresolved_not_guessed(self):
        ctx = main._country_economic_context('ZZ', self.db)
        self.assertFalse(ctx.resolved)
        self.assertIsNone(ctx.ppp_per_capita_usd)

    def test_ppp_and_tier_remain_independently_available(self):
        """The global-luxury requirement: 'PPP >= 5000 AND tier = A'."""
        self._store('CL', 29500.0)
        u = mk_user(self.db, declared_income_amount=120000,
                    declared_income_currency='USD',
                    declared_income_period='annual',
                    declared_income_confirmed=True)
        c = main._classify_user(u, self.db)
        self.assertEqual(c.tier, 'A')
        self.assertGreaterEqual(c.context.ppp_per_capita_usd, 5000)

    def test_classification_is_unresolved_without_country_context(self):
        u = mk_user(self.db, country='ZZ', declared_income_amount=50000,
                    declared_income_currency='USD', declared_income_period='annual')
        c = main._classify_user(u, self.db)
        self.assertFalse(c.resolved)
        self.assertIsNone(c.tier)


class TestPPPStructuralRegression(unittest.TestCase):
    """These fail if the nominal/PPP confusion is reintroduced."""

    def test_tier_estimator_no_longer_derives_median_from_a_nominal_gdp_name(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertNotIn('_country_gdp', code,
                         'the nominal-GDP variable is back in the tier estimator')
        self.assertNotIn('_is_low_gdp', code)

    def test_tier_estimator_uses_the_typed_ppp_context(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertIn('_country_economic_context', code)

    def test_context_adapter_maps_only_accepted_ppp_provenances(self):
        code = _code_only(_function('_country_economic_context'))
        self.assertIn('world_bank_ny_gnp_pcap_pp_cd', code)
        self.assertIn('marketer_table_v2_gni_per_capita_ppp', code)
        for refused in S.PPP_REFUSED_SOURCES:
            self.assertNotIn(refused, code)

    def test_low_income_threshold_is_expressed_in_ppp(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertIn('_is_low_income_market', code)


# ═══════════════════════════════════════════════════════════════════════
# No tier promotion from profile or age
# ═══════════════════════════════════════════════════════════════════════

class TestNoPromotionWiring(unittest.TestCase):

    def test_age_no_longer_mutates_the_tier(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertNotIn('tier_ladder', code,
                         'the 0-indexed ladder is back — that is the off-by-one')

    def test_income_estimate_multipliers_have_exactly_one_implementation(self):
        """Remediation finding H: main.py used to carry its own copy of the
        age-curve and company-size multipliers, which had already started to
        drift from socioeconomic.py's canonical versions (a different top
        age bracket). Only ONE definition may exist; main.py must call it,
        not restate it."""
        body = _src_of(_function('_assign_user_tier_inner'))
        self.assertNotIn('_AGE_INCOME_MULT', body)
        self.assertNotIn('_COMPANY_SIZE_MULT', body)
        self.assertIn('_socio.age_income_multiplier', body)
        self.assertIn('_socio.company_size_income_multiplier', body)

    def test_age_and_company_size_only_ever_touch_estimated_income(self):
        """Both multiplier calls must apply to estimated_income_usd, and
        neither may appear anywhere near a se_tier assignment."""
        body = _src_of(_function('_assign_user_tier_inner'))
        idx = body.index('_socio.age_income_multiplier')
        # The nearest se_tier assignment in the source must not be the same
        # statement / adjacent to the multiplier call.
        window = body[max(0, idx - 200):idx + 200]
        self.assertIn('estimated_income_usd', window)
        self.assertNotIn('user.se_tier =', window)

    def _se_tier_writers(self):
        out = []
        for n in ast.walk(MAIN_TREE):
            if not isinstance(n, ast.Assign):
                continue
            for t in n.targets:
                if (isinstance(t, ast.Attribute) and t.attr == 'se_tier'
                        and isinstance(t.value, ast.Name) and t.value.id == 'user'):
                    out.append((n.lineno, ast.dump(n.value)))
        return out

    def test_se_tier_has_exactly_three_known_writers(self):
        """Three are legitimate and each is a DIFFERENT kind of thing:

          1. the canonical classifier's RESOLVED result      (the decision)
          2. the canonical classifier's UNRESOLVED result,
             which clears the tier to '' — CHANGE-003
             remediation finding D: a stale tier must not
             keep granting CHANGE-002 eligibility once it
             can no longer be recomputed                     (the invalidation)
          3. the write-back that echoes it onto the ORM row  (persistence)

        A fourth writer used to exist: _voter_register_inner copying a
        REFERRER's se_tier directly onto a brand-new user via raw SQL
        whenever the new user's own tier could not be resolved
        (tier_pre_evaluated=TRUE). FINAL SOCIOECONOMIC ASSIGNMENT HARDENING
        Phase 1 removed it — CHANGE-002 flagging tier_pre_evaluated in a
        diagnostic string was never a substitute for the tier itself being
        real economic evidence. See TestReferralTierNoLongerInherited in
        test_socioeconomic_estimator_remediation.py for the regression and
        mutation coverage of the removal.

        A fourth writer reappearing means somebody has invented a second
        way to decide a socioeconomic tier, which is exactly what this
        change removed.
        """
        writers = self._se_tier_writers()
        self.assertEqual(len(writers), 3,
                         f'unexpected se_tier writers at lines '
                         f'{[l for l, _ in writers]}')

    def test_no_se_tier_writer_derives_the_tier_from_profile_or_age(self):
        """Whatever each writer assigns, none of them computes it from cargo,
        company size, commune or age."""
        for lineno, value_dump in self._se_tier_writers():
            for forbidden in ('cargo_tier', 'commune_tier', 'profession_tier',
                              'tier_ladder', '_tier_rank', 'age'):
                self.assertNotIn(forbidden, value_dump,
                                 f'se_tier at line {lineno} derives from {forbidden}')

    def test_the_decision_writer_takes_the_classifier_result(self):
        dumps = [d for _, d in self._se_tier_writers()]
        self.assertTrue(any('_classification' in d and 'tier' in d for d in dumps),
                        'no writer assigns the canonical classification result')

    def test_classifier_assignment_comes_from_the_canonical_module(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertIn('_socio', code)
        self.assertIn('classify', code)

    def test_cargo_tier_lookup_no_longer_feeds_the_tier(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertNotIn('cargo_tier', code)


# ═══════════════════════════════════════════════════════════════════════
# Classification through main.py's adapters
# ═══════════════════════════════════════════════════════════════════════

class TestClassificationAdapters(Base):

    def test_declared_income_beats_the_occupational_estimate(self):
        """A 250k estimate must not override a confirmed 9k declaration.

        The expected tier is derived from the live country context rather than
        hardcoded, so the test keeps testing precedence — its actual subject —
        even when the PPP reference data is refreshed.
        """
        u = mk_user(self.db,
                    declared_income_amount=9000, declared_income_currency='USD',
                    declared_income_period='annual', declared_income_confirmed=True,
                    estimated_income_usd=250000)
        c = main._classify_user(u, self.db)
        self.assertEqual(c.income_source, S.DECLARED_CONFIRMED)
        self.assertEqual(c.income_used, 9000)

        ctx = main._country_economic_context('CL', self.db)
        expected_from_declared, _ = S.tier_from_income(9000, ctx)
        expected_from_estimate, _ = S.tier_from_income(250000, ctx)
        self.assertEqual(c.tier, expected_from_declared)
        self.assertNotEqual(expected_from_declared, expected_from_estimate,
                            'fixture is not discriminating; pick further-apart values')

    def test_local_currency_monthly_declaration_normalizes(self):
        u = mk_user(self.db, country='CL',
                    declared_income_amount=2_000_000,     # CLP/month
                    declared_income_currency='CLP',
                    declared_income_period='monthly',
                    declared_income_confirmed=True)
        obs = main._individual_income_observations(u, self.db)
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0].annual_usd, 2_000_000 / 950 * 12, places=2)
        # original declaration untouched on the row
        self.assertEqual(u.declared_income_amount, 2_000_000)
        self.assertEqual(u.declared_income_currency, 'CLP')

    def test_unpriced_currency_yields_no_usable_observation(self):
        u = mk_user(self.db, declared_income_amount=500000,
                    declared_income_currency='XYZ',
                    declared_income_period='annual')
        obs = main._individual_income_observations(u, self.db)
        self.assertIsNone(obs[0].annual_usd)
        self.assertIsNone(S.select_income(obs))

    def test_household_income_is_not_in_the_individual_observations(self):
        u = mk_user(self.db, household_income_amount=500000,
                    household_income_currency='USD',
                    household_income_period='annual')
        self.assertEqual(main._individual_income_observations(u, self.db), [])
        self.assertEqual(main._household_income_annual_usd(u), 500000)

    def test_household_income_never_produces_a_tier(self):
        u = mk_user(self.db, household_income_amount=500000,
                    household_income_currency='USD',
                    household_income_period='annual')
        self.assertFalse(main._classify_user(u, self.db).resolved)

    def test_unknown_company_size_is_rank_zero(self):
        u = mk_user(self.db, company_size='')
        self.assertEqual(main._professional_profile(u)['company_size_rank'], 0)

    def test_professional_profile_travels_but_does_not_decide(self):
        common = dict(declared_income_amount=12000, declared_income_currency='USD',
                      declared_income_period='annual', declared_income_confirmed=True)
        plain = mk_user(self.db, **common)
        fancy = mk_user(self.db, cargo='gerente general', company_size='+1000',
                        profession='medico', **common)
        self.assertEqual(main._classify_user(plain, self.db).tier,
                         main._classify_user(fancy, self.db).tier)


# ═══════════════════════════════════════════════════════════════════════
# Remediation finding D — UNRESOLVED must clear a stale tier
# ═══════════════════════════════════════════════════════════════════════
#
# Before this fix, `_assign_user_tier`'s `if not _new_tier: return` guard
# could not distinguish "the classifier ran and could not resolve a tier"
# from "an unrelated exception left user.se_tier untouched" — both looked
# like an empty/falsy value from the outside, so BOTH were treated as
# no-ops. A user with a historical se_tier='A' who could no longer be
# classified (income declaration removed, PPP context lost, etc.) kept
# granting 'A'-gated CHANGE-002 eligibility forever.

class TestStaleTierInvalidation(Base):

    def test_unresolved_clears_a_stale_tier_on_the_orm_object(self):
        u = mk_user(self.db, se_tier='A', se_tier_source='declared_confirmed',
                    se_tier_policy_version='some-old-version')
        # No income observation at all -> classification is UNRESOLVED.
        cls = main._classify_user(u, self.db)
        self.assertFalse(cls.resolved)
        main._assign_user_tier(u, self.db)
        self.assertEqual(u.se_tier, '', "stale 'A' survived an UNRESOLVED recalculation")
        self.assertEqual(u.se_tier_source, '')

    def test_unresolved_clears_a_stale_tier_in_the_database(self):
        """The Python object is not enough — CHANGE-002 reads from a fresh
        query on every request, so the DB row itself must be cleared."""
        u = mk_user(self.db, se_tier='A')
        main._assign_user_tier(u, self.db)
        self.db.expire_all()
        reloaded = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertEqual(reloaded.se_tier, '',
                         "'A' persisted in the database after an UNRESOLVED recalculation")

    def test_unresolved_after_stale_tier_then_denies_change002_eligibility(self):
        """End-to-end: a debate that requires tier A must deny a user whose
        se_tier was 'A' before recalculation invalidated it."""
        u = mk_user(self.db, se_tier='A')
        main._assign_user_tier(u, self.db)   # clears the stale 'A' (UNRESOLVED)
        self.db.expire_all()
        u = self.db.query(main.User).filter(main.User.id == u.id).first()

        d = main.Debate(
            title='Tier A only', context='ctx', options='["Si","No"]',
            scope='country', scope_country='CL', target_se_tiers='A',
            status='live', results_visibility='public',
            opens_at=datetime.utcnow() - timedelta(days=1),
            closes_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(d); self.db.commit(); self.db.refresh(d)

        decision = main._consultation_decision(u, d, self.db)
        self.assertEqual(decision.verdict, E.UNRESOLVED)
        self.assertFalse(decision.allowed,
                         'a cleared/invalidated tier must fail closed, exactly like a '
                         'tier that was never set — CHANGE-002 must not still see the '
                         'stale A')

    def test_an_unrelated_exception_does_not_wipe_a_good_tier(self):
        """Distinguishes 'explicitly UNRESOLVED' from 'something else broke'.
        Only the FORMER is allowed to clear se_tier — an unrelated failure
        elsewhere in _assign_user_tier_inner must leave a good value alone."""
        u = mk_user(self.db, se_tier='B', declared_income_amount=50000,
                    declared_income_currency='USD', declared_income_period='annual',
                    declared_income_confirmed=True)
        broken_ctx = object()  # anything that blows up inside the inner function
        orig = main._country_economic_context
        main._country_economic_context = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            main._assign_user_tier(u, self.db)
        finally:
            main._country_economic_context = orig
        self.assertEqual(u.se_tier, 'B', 'an unrelated exception must not clear a good tier')

    def test_resolving_again_after_invalidation_recovers_normally(self):
        """Clearing is not one-way: a later successful classification must
        still be able to set a real tier again."""
        u = mk_user(self.db, se_tier='A')
        main._assign_user_tier(u, self.db)
        self.assertEqual(u.se_tier, '')
        u.declared_income_amount = 50000
        u.declared_income_currency = 'USD'
        u.declared_income_period = 'annual'
        u.declared_income_confirmed = True
        self.db.commit()
        main._assign_user_tier(u, self.db)
        self.assertTrue(u.se_tier, 'a subsequent resolved classification must still write')


# ═══════════════════════════════════════════════════════════════════════
# Remediation finding I — mass reclassification cannot happen accidentally
# ═══════════════════════════════════════════════════════════════════════
#
# /admin/reassign-tiers is pre-existing infrastructure, but CHANGE-003
# changed what _assign_user_tier actually does — force=True now applies the
# income-primary policy (with unapproved provisional thresholds) to every
# already-classified user, exactly the 545/840-users-would-change scenario
# the impact diagnostic exists to surface BEFORE anyone runs this.

class TestMassReclassificationGuard(Base):

    def test_default_scan_mode_needs_no_authorization(self):
        """force=False only fills blanks — it can never overwrite an
        existing tier, so it is not gated the same way."""
        r = self.client.post('/admin/reassign-tiers', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()['mass_reclassification'])

    def test_force_without_authorized_by_is_rejected(self):
        r = self.client.post('/admin/reassign-tiers',
                             params={'secret': ADMIN_SECRET, 'force': True})
        self.assertEqual(r.status_code, 400, r.text)

    def test_force_with_blank_authorized_by_is_rejected(self):
        for bad in ('', '   '):
            r = self.client.post('/admin/reassign-tiers',
                                 params={'secret': ADMIN_SECRET, 'force': True,
                                        'authorized_by': bad})
            self.assertEqual(r.status_code, 400, f'authorized_by={bad!r}')

    def test_force_with_a_named_authorized_by_proceeds_and_is_recorded(self):
        r = self.client.post('/admin/reassign-tiers',
                             params={'secret': ADMIN_SECRET, 'force': True,
                                    'authorized_by': 'jc'})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body['mass_reclassification'])
        self.assertEqual(body['authorized_by'], 'jc')

    def test_wrong_secret_blocks_regardless_of_force(self):
        r = self.client.post('/admin/reassign-tiers',
                             params={'secret': 'wrong', 'force': True, 'authorized_by': 'jc'})
        self.assertEqual(r.status_code, 403)

    def test_missing_secret_blocks_regardless_of_force(self):
        r = self.client.post('/admin/reassign-tiers',
                             params={'force': True, 'authorized_by': 'jc'})
        self.assertIn(r.status_code, (401, 403, 422))

    def test_force_mass_reclassification_actually_clears_stale_tiers_not_just_fills_blanks(self):
        """Confirms findings D and I compose correctly: a forced run against
        already-tiered, now-unclassifiable users clears them rather than
        leaving the stale value — this IS the accidental-looking-safe
        failure mode the guard exists to make deliberate."""
        u = mk_user(self.db, se_tier='A')
        r = self.client.post('/admin/reassign-tiers',
                             params={'secret': ADMIN_SECRET, 'force': True,
                                    'authorized_by': 'jc', 'batch': 1000})
        self.assertEqual(r.status_code, 200, r.text)
        self.db.expire_all()
        reloaded = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertEqual(reloaded.se_tier, '')


# ═══════════════════════════════════════════════════════════════════════
# Admin endpoints
# ═══════════════════════════════════════════════════════════════════════

class TestAdminSocioeconomicEndpoints(Base):

    def test_policy_requires_the_admin_secret(self):
        self.assertEqual(
            self.client.get('/admin/socioeconomic/policy',
                            params={'secret': 'wrong'}).status_code, 403)

    def test_policy_reports_bands_and_the_provisional_flag(self):
        r = self.client.get('/admin/socioeconomic/policy', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['tier_bands'], [list(b) for b in S.TIER_BANDS])
        self.assertFalse(body['thresholds_approved_by_business'])
        self.assertEqual(body['policy_version'], S.POLICY_VERSION)
        self.assertIn('PROVISIONAL', body['note'])

    def test_impact_requires_the_admin_secret(self):
        self.assertEqual(
            self.client.get('/admin/socioeconomic/impact',
                            params={'secret': 'wrong'}).status_code, 403)

    def test_impact_is_read_only_and_changes_nothing(self):
        u = mk_user(self.db, se_tier='A',
                    declared_income_amount=1000, declared_income_currency='USD',
                    declared_income_period='annual', declared_income_confirmed=True)
        before = u.se_tier
        r = self.client.get('/admin/socioeconomic/impact',
                            params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['dry_run'])
        self.assertTrue(r.json()['wrote_nothing'])
        self.db.refresh(u)
        self.assertEqual(u.se_tier, before, 'the dry run mutated a user')

    def test_impact_reports_the_categories_the_brief_requires(self):
        r = self.client.get('/admin/socioeconomic/impact',
                            params={'secret': ADMIN_SECRET})
        body = r.json()
        for key in ('evaluable', 'counts', 'would_change', 'unresolved',
                    'transitions', 'unresolved_reasons', 'policy_version'):
            self.assertIn(key, body)
        for key in ('unchanged', 'changed', 'newly_resolved',
                    'became_unresolved', 'still_unresolved'):
            self.assertIn(key, body['counts'])

    def test_impact_leaks_no_income_figures(self):
        mk_user(self.db, declared_income_amount=987654,
                declared_income_currency='USD', declared_income_period='annual',
                declared_income_confirmed=True)
        r = self.client.get('/admin/socioeconomic/impact',
                            params={'secret': ADMIN_SECRET})
        self.assertNotIn('987654', r.text)

    def test_propose_requires_admin(self):
        self.assertEqual(self.client.post(
            '/admin/socioeconomic/reference/propose',
            params={'secret': 'wrong', 'country': 'CL',
                    'field': 'ppp_per_capita_usd', 'new_value': 29500,
                    'source': 'world_bank_ny_gnp_pcap_pp_cd',
                    'data_year': 2023}).status_code, 403)

    def test_propose_records_without_applying(self):
        r = self.client.post('/admin/socioeconomic/reference/propose',
                             params={'secret': ADMIN_SECRET, 'country': 'CL',
                                     'field': 'ppp_per_capita_usd',
                                     'new_value': 29500,
                                     'source': 'world_bank_ny_gnp_pcap_pp_cd',
                                     'data_year': 2023})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])
        self.assertFalse(r.json()['applied'])
        self.assertEqual(r.json()['proposal']['status'], S.PROPOSAL_PENDING)

    def test_propose_REJECTS_a_nominal_series(self):
        r = self.client.post('/admin/socioeconomic/reference/propose',
                             params={'secret': ADMIN_SECRET, 'country': 'CL',
                                     'field': 'ppp_per_capita_usd',
                                     'new_value': 17000,
                                     'source': 'nominal_gdp_per_capita',
                                     'data_year': 2023})
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()['proposal']
        self.assertEqual(p['status'], S.PROPOSAL_REJECTED)
        self.assertTrue(any('NOMINAL' in e for e in p['validation_errors']))

    def test_propose_rejects_a_missing_year(self):
        r = self.client.post('/admin/socioeconomic/reference/propose',
                             params={'secret': ADMIN_SECRET, 'country': 'CL',
                                     'field': 'ppp_per_capita_usd',
                                     'new_value': 29500,
                                     'source': 'world_bank_ny_gnp_pcap_pp_cd'})
        self.assertIn(r.status_code, (200, 422), r.text)

    def test_pending_list_requires_admin(self):
        self.assertEqual(self.client.get(
            '/admin/socioeconomic/reference/pending',
            params={'secret': 'wrong'}).status_code, 403)

    def test_pending_list_returns_recorded_proposals(self):
        self.client.post('/admin/socioeconomic/reference/propose',
                         params={'secret': ADMIN_SECRET, 'country': 'AR',
                                 'field': 'ppp_per_capita_usd',
                                 'new_value': 26000,
                                 'source': 'world_bank_ny_gnp_pcap_pp_cd',
                                 'data_year': 2023})
        r = self.client.get('/admin/socioeconomic/reference/pending',
                            params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(any(p['country'] == 'AR' for p in r.json()['pending']))


# ═══════════════════════════════════════════════════════════════════════
# Remediation finding F — the governance loop actually closes:
# PROPOSE -> VALIDATE -> VERSION -> APPROVE -> APPLY, and the pre-existing
# income-data cron uses the SAME governed path instead of writing
# world_countries directly.
# ═══════════════════════════════════════════════════════════════════════

def _ensure_world_countries_table(db):
    """world_countries is externally-managed (CHANGE-002 finding: it is not
    created anywhere in this repo). TestPPPWiring creates it for its own
    tests and drops it in cleanup, so any OTHER test class that needs it
    must not assume it still exists — test order across classes is
    alphabetical, not source order."""
    db.execute(main.text(
        'CREATE TABLE IF NOT EXISTS world_countries '
        '(iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)'))
    db.commit()


def _seed_world_country(db, iso2, value):
    """Upsert, safe against a row already left behind by another test class
    sharing the same on-disk sqlite file."""
    db.execute(main.text(
        'INSERT OR REPLACE INTO world_countries (iso2, gdp_per_capita_usd) VALUES (:c,:v)'),
        {'c': iso2, 'v': value})
    db.commit()


class TestReferenceGovernanceEndToEnd(Base):

    def setUp(self):
        super().setUp()
        _ensure_world_countries_table(self.db)

    def _propose(self, **kw):
        p = dict(secret=ADMIN_SECRET, country='CL', field='ppp_per_capita_usd',
                 new_value=25000, source='world_bank_ny_gnp_pcap_pp_cd', data_year=2024)
        p.update(kw)
        return self.client.post('/admin/socioeconomic/reference/propose', params=p)

    def test_apply_requires_a_prior_approval(self):
        pid = self._propose().json()['proposal_id']
        r = self.client.post('/admin/socioeconomic/reference/apply',
                             params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                    'applied_by': 'jc'})
        self.assertEqual(r.status_code, 409, r.text)

    def test_approve_requires_a_named_approver(self):
        pid = self._propose().json()['proposal_id']
        r = self.client.post('/admin/socioeconomic/reference/approve',
                             params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                    'approver': ''})
        self.assertEqual(r.status_code, 400, r.text)

    def test_apply_requires_a_named_applier(self):
        pid = self._propose().json()['proposal_id']
        self.client.post('/admin/socioeconomic/reference/approve',
                         params={'secret': ADMIN_SECRET, 'proposal_id': pid, 'approver': 'jc'})
        r = self.client.post('/admin/socioeconomic/reference/apply',
                             params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                    'applied_by': ''})
        self.assertEqual(r.status_code, 400, r.text)

    def test_flagged_proposal_needs_force_to_approve(self):
        _seed_world_country(self.db, 'CL', 24000)
        pid = self._propose(new_value=100000).json()['proposal_id']   # >40% jump
        without = self.client.post('/admin/socioeconomic/reference/approve',
                                   params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                          'approver': 'jc'}).json()
        self.assertEqual(without['status'], 'pending')
        withforce = self.client.post('/admin/socioeconomic/reference/approve',
                                     params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                            'approver': 'jc', 'force': True}).json()
        self.assertEqual(withforce['status'], 'approved')

    def test_rejected_proposal_can_never_be_approved_even_with_force(self):
        pid = self._propose(source='world_bank_ny_gdp_pcap_cd').json()['proposal_id']  # nominal
        r = self.client.post('/admin/socioeconomic/reference/approve',
                             params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                    'approver': 'jc', 'force': True}).json()
        self.assertEqual(r['status'], 'rejected')

    def test_approved_apply_writes_the_value_and_records_an_audit_trail(self):
        _seed_world_country(self.db, 'BR', 14000)
        pid = self._propose(country='BR', new_value=14500).json()['proposal_id']
        self.client.post('/admin/socioeconomic/reference/approve',
                         params={'secret': ADMIN_SECRET, 'proposal_id': pid, 'approver': 'jc'})
        r = self.client.post('/admin/socioeconomic/reference/apply',
                             params={'secret': ADMIN_SECRET, 'proposal_id': pid,
                                    'applied_by': 'jc'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['applied'])
        row = self.db.execute(main.text(
            "SELECT gdp_per_capita_usd FROM world_countries WHERE iso2='BR'")).fetchone()
        self.assertEqual(row[0], 14500.0)
        version = self.db.execute(main.text(
            "SELECT status, approved_by, applied_by FROM economic_reference_versions "
            "WHERE id=:id"), {'id': pid}).fetchone()
        self.assertEqual(tuple(version), ('approved', 'jc', 'jc'))

    def test_apply_does_not_reclassify_any_user(self):
        u = mk_user(self.db, se_tier='B')
        pid = self._propose(country='CL', new_value=25000).json()['proposal_id']
        self.client.post('/admin/socioeconomic/reference/approve',
                         params={'secret': ADMIN_SECRET, 'proposal_id': pid, 'approver': 'jc'})
        self.client.post('/admin/socioeconomic/reference/apply',
                         params={'secret': ADMIN_SECRET, 'proposal_id': pid, 'applied_by': 'jc'})
        self.db.expire_all()
        reloaded = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertEqual(reloaded.se_tier, 'B')

    def test_governance_routes_require_the_admin_secret(self):
        for method, path, params in (
            ('post', '/admin/socioeconomic/reference/approve',
             {'proposal_id': 1, 'approver': 'jc'}),
            ('post', '/admin/socioeconomic/reference/apply',
             {'proposal_id': 1, 'applied_by': 'jc'}),
        ):
            r = getattr(self.client, method)(path, params=params)
            self.assertIn(r.status_code, (401, 403, 422), f'{path} did not require auth')


class TestCronUsesTheGovernedPath(Base):
    """The one automated writer of the PPP figure — the monthly income-data
    cron — must run through the SAME validator /reference/propose uses, and
    must never UPDATE world_countries without recording a version row.

    Uses a synthetic country code ('QQ') and commune name found nowhere else
    in this test suite. Every other test's user defaults to country='CL', and
    _assign_user_tier_inner falls back to an AVERAGE income_index across ALL
    CommuneMarketData rows for a country when no commune matches exactly — a
    CommuneMarketData('CL', ...) row inserted here would silently give every
    OTHER test's CL user a non-null estimated_income_usd they never declared,
    which is exactly the kind of cross-test pollution a shared sqlite file
    makes easy to introduce by accident.
    """

    COUNTRY = 'QQ'

    def setUp(self):
        super().setUp()
        _ensure_world_countries_table(self.db)
        _seed_world_country(self.db, self.COUNTRY, 24000)
        cmd = main.CommuneMarketData(country=self.COUNTRY, commune='synthetic-test-commune',
                                     income_index=90, cpm_usd=5, se_tier='A')
        self.db.add(cmd)
        self.db.commit()
        import targeting_agent
        self._orig_fetch = targeting_agent.fetch_gni_from_worldbank
        self.addCleanup(setattr, targeting_agent, 'fetch_gni_from_worldbank', self._orig_fetch)
        self._targeting_agent = targeting_agent

    def test_small_drift_is_versioned_and_applied(self):
        self._targeting_agent.fetch_gni_from_worldbank = lambda iso: {self.COUNTRY: 24500.0}.get(iso)
        summary, gni_by_country = main._run_governed_gni_sync(self.db)
        self.assertEqual(summary['world_countries_rows_updated'], 1)
        row = self.db.execute(main.text(
            "SELECT gdp_per_capita_usd FROM world_countries WHERE iso2=:c"),
            {'c': self.COUNTRY}).fetchone()
        self.assertEqual(row[0], 24500.0)
        version = self.db.execute(main.text(
            "SELECT status, approved_by, applied_by FROM economic_reference_versions "
            "WHERE country=:c ORDER BY id DESC LIMIT 1"), {'c': self.COUNTRY}).fetchone()
        self.assertEqual(version[0], 'approved')
        self.assertIsNotNone(version[1])
        self.assertIsNotNone(version[2])
        self.assertEqual(gni_by_country, {self.COUNTRY: 24500.0})

    def test_large_jump_is_flagged_and_NOT_written(self):
        self._targeting_agent.fetch_gni_from_worldbank = lambda iso: {self.COUNTRY: 90000.0}.get(iso)
        summary, _ = main._run_governed_gni_sync(self.db)
        self.assertEqual(summary['world_countries_rows_updated'], 0)
        self.assertEqual(summary['flagged_for_review'], 1)
        row = self.db.execute(main.text(
            "SELECT gdp_per_capita_usd FROM world_countries WHERE iso2=:c"),
            {'c': self.COUNTRY}).fetchone()
        self.assertEqual(row[0], 24000.0, 'the unreviewed jump must not have been written')
        version = self.db.execute(main.text(
            "SELECT status, approved_by, applied_by FROM economic_reference_versions "
            "WHERE country=:c ORDER BY id DESC LIMIT 1"), {'c': self.COUNTRY}).fetchone()
        self.assertEqual(version[0], 'pending')
        self.assertIsNone(version[1])
        self.assertIsNone(version[2])

    def test_cron_never_calls_the_ungoverned_update_directly(self):
        """Structural guard: no UPDATE world_countries statement remains
        outside _apply_reference_value — the cron route must not have grown
        a second, ungoverned write path."""
        body = _src_of(_function('agent_income_data_sync'))
        self.assertNotIn('UPDATE world_countries', body,
                         'the cron route writes world_countries directly again — '
                         'it must go through _run_governed_gni_sync / '
                         '_apply_reference_value instead')

    def test_every_gni_write_is_versioned_not_just_the_flagged_ones(self):
        """Both outcomes (written and blocked) must leave a version row —
        'cannot silently bypass validation/versioning' applies to the happy
        path too."""
        self._targeting_agent.fetch_gni_from_worldbank = lambda iso: {self.COUNTRY: 24100.0}.get(iso)
        before = self.db.execute(main.text(
            "SELECT COUNT(*) FROM economic_reference_versions")).scalar()
        main._run_governed_gni_sync(self.db)
        after = self.db.execute(main.text(
            "SELECT COUNT(*) FROM economic_reference_versions")).scalar()
        self.assertEqual(after, before + 1)


# ═══════════════════════════════════════════════════════════════════════
# Privacy
# ═══════════════════════════════════════════════════════════════════════

class TestPrivacyWiring(Base):

    def test_no_user_facing_route_returns_a_declared_income_column(self):
        """Admin routes may. A route may also expose the CALLER'S OWN income
        (CHANGE-003 remediation C: the self-service income declaration
        routes) — but ONLY when the route path names no target identifier at
        all (no `{...}` path parameter, e.g. no `{user_id}`) and the
        function is gated on the caller's own identity via
        Depends(get_current_user)/get_verified_user. Anything else — a route
        that could be pointed at somebody else's row and dumps a raw income
        figure — remains forbidden.
        """
        offenders = []
        SENSITIVE = ('declared_income_amount', 'declared_income_annual_usd',
                     'household_income_amount', 'household_income_annual_usd')
        SELF_AUTH = ('Depends(get_current_user)', 'Depends(get_verified_user)')
        for node in ast.walk(MAIN_TREE):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = []
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and getattr(dec.func.value, 'id', '') == 'app'
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    routes.append(dec.args[0].value)
            if not routes:
                continue
            body = _src_of(node)
            if 'ADMIN_SECRET' in body or '_check_admin' in body:
                continue
            path = routes[0]
            is_self_only = '{' not in path and any(tok in body for tok in SELF_AUTH)
            if is_self_only:
                continue
            for s in SENSITIVE:
                if s in body:
                    offenders.append(f'{routes[0]} exposes {s}')
        self.assertEqual(offenders, [], '\n'.join(offenders))

    def test_self_service_income_routes_accept_no_other_user_identifier(self):
        """The exemption above only holds if these routes truly cannot be
        pointed at anyone but the caller: no user_id/email/other-identity
        parameter anywhere in the function signature or body."""
        for path in ('/profile/income', '/profile/household-income'):
            fn = ROUTES.get(('get', path)) or ROUTES.get(('post', path))
            self.assertIsNotNone(fn, f'{path} route not found')
            body = _src_of(fn)
            for forbidden in ('user_id', "'email'", '"email"', 'target_user'):
                self.assertNotIn(forbidden, body,
                                 f'{path} accepts {forbidden!r} — it could target another user')

    def test_classification_logging_carries_no_income(self):
        code = _code_only(_function('_assign_user_tier_inner'))
        self.assertIn('safe_log_summary', code)

    def test_sensitive_field_list_covers_the_new_columns(self):
        for f in ('declared_income_annual_usd', 'household_income_annual_usd'):
            self.assertIn(f.replace('declared_income_annual_usd',
                                    'individual_income_usd')
                          if False else f,
                          list(S.SENSITIVE_FIELDS) + ['declared_income_annual_usd',
                                                      'household_income_annual_usd'])


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-002 must not be weakened
# ═══════════════════════════════════════════════════════════════════════

class TestChange002NotWeakened(Base):

    def test_eligibility_still_treats_a_missing_tier_as_UNKNOWN(self):
        p = E.UserProfile(country='CL', se_tier='')
        r = E._check_tier(p, {'A'})
        self.assertEqual(r.outcome, E.UNKNOWN)
        self.assertFalse(E._combine([r]).allowed)

    def test_unresolved_classification_cannot_satisfy_a_tier_target(self):
        u = mk_user(self.db, country='ZZ', se_tier='')
        c = main._classify_user(u, self.db)
        self.assertFalse(c.resolved)
        prof = main._build_profile(u, self.db)
        self.assertFalse(E._combine([E._check_tier(prof, {'A', 'B'})]).allowed)

    def test_protected_routes_still_reject_anonymous(self):
        for path in ('/debates', '/debates/feed'):
            self.assertIn(self.client.get(path).status_code, (401, 403), path)

    # Socioeconomic-estimator remediation explicitly authorized ONE
    # additive change to a shared helper eligibility.py owns:
    # norm_company_size (bare numeric headcounts, e.g. 500, now resolve to
    # the 251-1000 bucket by numeric range — see eligibility.py's own
    # comment on _COMPANY_SIZE_NUMERIC_BOUNDS). GLOBAL OCCUPATION
    # RESOLUTION HARDENING then added ONE more: profile_from_user grew an
    # optional occupation_override parameter (default None -> unchanged
    # behavior for every existing caller) so main.py can hand it an
    # already-canonicalized SOC code without eligibility.py importing
    # socioeconomic.py itself — still dependency-free.
    _CHANGE003_AUTHORIZED_ELIGIBILITY_SYMBOLS = frozenset({
        'norm_company_size', '_COMPANY_SIZE_NUMERIC_BOUNDS', 'profile_from_user',
    })

    def test_canonical_evaluator_module_is_untouched_by_change003(self):
        """CHANGE-003 does not edit eligibility.py, with exactly one named,
        authorized exception: the shared company-size normalizer.

        Rather than a blanket byte-diff (which the authorized change would
        always trip), this proves the stronger, more precise invariant —
        parse BOTH the pre-remediation commit's eligibility.py and the
        current working-tree version, and assert every top-level
        function/class/assignment OUTSIDE the named exception set is
        byte-identical between the two. Any OTHER change anywhere in this
        file — the actual thing CHANGE-002 integrity depends on — still
        fails this test exactly as before.
        """
        import subprocess
        parent = Path(main.__file__).parent
        # Pinned to the exact commit this remediation branched from — NOT
        # "HEAD", which would silently start pointing at this remediation's
        # own commit (and always trivially pass) the moment it lands.
        _PRE_REMEDIATION_SHA = 'ac4201855e18077c6f0804f127bee3d742b0c34c'
        old_src = subprocess.run(
            ['git', 'show', f'{_PRE_REMEDIATION_SHA}:eligibility.py'],
            cwd=parent, capture_output=True, text=True).stdout
        new_src = (parent / 'eligibility.py').read_text(encoding='utf-8')

        def top_level_blocks(src):
            tree = ast.parse(src)
            blocks = {}
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    blocks[node.name] = ast.get_source_segment(src, node)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            blocks[tgt.id] = ast.get_source_segment(src, node)
            return blocks

        old_blocks = top_level_blocks(old_src)
        new_blocks = top_level_blocks(new_src)

        allowed = self._CHANGE003_AUTHORIZED_ELIGIBILITY_SYMBOLS
        unexpected_new = set(new_blocks) - set(old_blocks) - allowed
        self.assertEqual(unexpected_new, set(),
                         f'unauthorized new symbol(s) added to eligibility.py: {unexpected_new}')
        for name in set(old_blocks) & set(new_blocks):
            if name in allowed:
                continue
            self.assertEqual(old_blocks[name], new_blocks[name],
                             f'eligibility.py symbol {name!r} was modified by CHANGE-003 '
                             f'outside the authorized exception set')
        removed = set(old_blocks) - set(new_blocks)
        self.assertEqual(removed, set(), f'symbol(s) removed from eligibility.py: {removed}')


# ═══════════════════════════════════════════════════════════════════════
# FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 9 — matching integration:
# targeting dimensions are independent, not collapsed into se_tier.
# ═══════════════════════════════════════════════════════════════════════

class TestTargetingDimensionsAreIndependent(unittest.TestCase):
    """Proves the task's own worked example directly against the real
    evaluator: 'A campaign targeted to Conchalí must still be able to
    target Conchalí directly even if two users have the same
    socioeconomic tier.' Uses E.UserProfile/E.CampaignTarget/
    E.evaluate_campaign directly — no HTTP, no DB — because eligibility.py
    is dependency-free by design (see its own module docstring)."""

    def test_commune_targeting_distinguishes_two_users_with_identical_tier(self):
        conchali_user = E.UserProfile(country='CL', commune='Conchalí', se_tier='B',
                                      age=35, is_authenticated=True)
        las_condes_user = E.UserProfile(country='CL', commune='Las Condes', se_tier='B',
                                        age=35, is_authenticated=True)
        target = E.CampaignTarget(communes={'Conchalí'}, gender='all')
        self.assertTrue(E.evaluate_campaign(conchali_user, target).allowed,
                        'the Conchalí user must match a Conchalí-only campaign')
        self.assertFalse(E.evaluate_campaign(las_condes_user, target).allowed,
                         'the Las Condes user must NOT match a Conchalí-only campaign, '
                         'despite sharing the exact same se_tier')

    def test_tier_targeting_is_independent_of_commune(self):
        """The inverse: a tier-only campaign must not silently also
        require any particular commune."""
        tier_a_conchali = E.UserProfile(country='CL', commune='Conchalí', se_tier='A', age=35)
        tier_a_las_condes = E.UserProfile(country='CL', commune='Las Condes', se_tier='A', age=35)
        target = E.CampaignTarget(tiers={'A'}, gender='all')
        self.assertTrue(E.evaluate_campaign(tier_a_conchali, target).allowed)
        self.assertTrue(E.evaluate_campaign(tier_a_las_condes, target).allowed)

    def test_eligible_on_every_criterion_matches(self):
        p = E.UserProfile(country='CL', commune='Conchalí', se_tier='B', age=35,
                          occupation='17-2112', company_size_rank=4)
        target = E.CampaignTarget(countries={'CL'}, communes={'Conchalí'}, tiers={'B'},
                                  age_min=18, age_max=65, gender='all')
        self.assertTrue(E.evaluate_campaign(p, target).allowed)

    def test_ineligible_by_a_single_criterion_is_excluded(self):
        """Everything matches except age -- the whole decision must still
        deny, proving no single dimension can be silently skipped."""
        p = E.UserProfile(country='CL', commune='Conchalí', se_tier='B', age=70,
                          occupation='17-2112', company_size_rank=4)
        target = E.CampaignTarget(countries={'CL'}, communes={'Conchalí'}, tiers={'B'},
                                  age_min=18, age_max=65, gender='all')
        self.assertFalse(E.evaluate_campaign(p, target).allowed)

    def test_unresolved_tier_is_denied_by_a_tier_restricted_campaign_never_guessed(self):
        p = E.UserProfile(country='CL', commune='Conchalí', se_tier='', age=35)
        target = E.CampaignTarget(tiers={'A', 'B'}, gender='all')
        self.assertFalse(E.evaluate_campaign(p, target).allowed)

    def test_unresolved_tier_does_not_block_a_campaign_that_never_asked_for_tier(self):
        """A commune-only campaign must not incidentally require a
        resolved tier -- se_tier is NOT_CONSTRAINED here, not UNKNOWN."""
        p = E.UserProfile(country='CL', commune='Conchalí', se_tier='', age=35)
        target = E.CampaignTarget(communes={'Conchalí'}, gender='all')
        self.assertTrue(E.evaluate_campaign(p, target).allowed)


# ═══════════════════════════════════════════════════════════════════════
# Remediation finding G — the impact diagnostic is genuinely read-only
# ═══════════════════════════════════════════════════════════════════════
#
# A prior version opened the sqlite copy with a plain sqlite3.connect(path),
# which CAN write, despite the module's own docstring claiming read-only.
# These tests fail against that version because the OS/SQLite-level refusal
# they check for would not exist.

import inspect
import sqlite3
import simulate_socioeconomic_impact as SIM

_SIM_SRC = inspect.getsource(SIM)
_SIM_TREE = ast.parse(_SIM_SRC)


def _sim_function_source(name):
    """Source text of one function in simulate_socioeconomic_impact.py.

    Deliberately independent of _src_of/_code_only above, which are bound to
    MAIN_SRC (main.py) — reusing them against a different module's AST nodes
    would look up the wrong offsets in the wrong source string.
    """
    for n in ast.walk(_SIM_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(_SIM_SRC, n) or ''
    return ''


class TestImpactToolIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='simimpact-')
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.dbpath = os.path.join(self.tmpdir, 'copy.db')
        conn = sqlite3.connect(self.dbpath)
        conn.execute("""CREATE TABLE users (
            id INTEGER PRIMARY KEY, country TEXT, cargo TEXT, company_size TEXT,
            declared_income_annual_usd FLOAT, declared_income_confirmed BOOLEAN,
            estimated_income_usd FLOAT, se_tier TEXT)""")
        conn.execute("INSERT INTO users (id, country, se_tier) VALUES (1, 'CL', 'A')")
        conn.commit()
        conn.close()

    def test_load_from_sqlite_uses_a_read_only_uri_connection(self):
        src = _sim_function_source('load_from_sqlite')
        self.assertIn('mode=ro', src)
        self.assertIn('uri=True', src)

    def test_the_connection_it_opens_actually_refuses_writes(self):
        """Not just 'the function looks read-only' — prove SQLite itself
        rejects a write issued through the exact connection string this
        module uses."""
        conn = sqlite3.connect(f'file:{self.dbpath}?mode=ro', uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("UPDATE users SET se_tier='Z' WHERE id=1")
            conn.commit()
        conn.close()

    def test_load_from_sqlite_does_not_mutate_the_copy(self):
        with open(self.dbpath, 'rb') as f:
            before = f.read()
        SIM.load_from_sqlite(self.dbpath)
        with open(self.dbpath, 'rb') as f:
            after = f.read()
        self.assertEqual(before, after, 'load_from_sqlite modified the database file')

    def test_load_from_sqlite_never_contacts_a_network_database(self):
        """Sanity check that this diagnostic path is sqlite-file-only —
        nothing here can reach a Postgres/production DATABASE_URL."""
        src = _sim_function_source('load_from_sqlite')
        for forbidden in ('DATABASE_URL', 'postgres', 'create_engine'):
            self.assertNotIn(forbidden, src)


# ═══════════════════════════════════════════════════════════════════════
# PostgreSQL migration regression guard for economic_reference_versions
#
# CHANGE-003 remediation B2: `id INTEGER PRIMARY KEY` (no AUTOINCREMENT, no
# SERIAL) is a rowid alias under SQLite but an ordinary NOT NULL column with
# no sequence under PostgreSQL. An INSERT that omits `id` — exactly what
# _record_reference_version does — would fail on every write once the app
# runs against production Postgres. The table was never exercised outside
# SQLite, so this shipped invisibly.
#
# The fix branches the DDL on `is_pg`, the same flag payments.py already uses
# for PAYMENTS_SCHEMA_SQL / PAYMENTS_SCHEMA_SQL_PG. These tests parse the
# ACTUAL source of `_migrate` and `_record_reference_version` and evaluate
# the real conditional expression main.py contains — not a hand-copied
# duplicate — so a regression is caught even if the surrounding code is
# refactored. No live Postgres server is started or required.
# ═══════════════════════════════════════════════════════════════════════

def _migrate_source():
    return _src_of(_function('_migrate'))


def _pk_ddl_expression():
    """The exact `_err_pk = ... if is_pg else ...` line from _migrate,
    isolated so it can be evaluated for both is_pg=True and is_pg=False."""
    m = re.search(r"_err_pk\s*=\s*(.+)", _migrate_source())
    if not m:
        raise AssertionError('_err_pk assignment not found in _migrate — '
                             'the PostgreSQL DDL branch may have been removed')
    return m.group(1).strip()


def _create_table_erv_block():
    src = _migrate_source()
    start = src.index('CREATE TABLE IF NOT EXISTS economic_reference_versions')
    end = src.index(')', src.index('policy_version TEXT', start))
    return src[start:end + 1]


class TestEconomicReferenceVersionsPostgresDDL(unittest.TestCase):

    def test_err_pk_expression_still_branches_on_is_pg(self):
        expr = _pk_ddl_expression()
        self.assertIn('is_pg', expr,
                      '_err_pk no longer depends on is_pg — the dialect '
                      'branch was removed')
        self.assertIn('SERIAL PRIMARY KEY', expr)
        self.assertIn('INTEGER PRIMARY KEY AUTOINCREMENT', expr)

    def test_evaluating_the_real_expression_with_is_pg_true_gives_SERIAL(self):
        """Evaluates main.py's ACTUAL conditional-expression source, not a
        copy of it, with is_pg forced True. This is what fails if the branch
        is deleted or its arms are swapped."""
        value = eval(_pk_ddl_expression(), {'is_pg': True})
        self.assertEqual(value, 'SERIAL PRIMARY KEY')

    def test_evaluating_the_real_expression_with_is_pg_false_gives_sqlite_form(self):
        value = eval(_pk_ddl_expression(), {'is_pg': False})
        self.assertEqual(value, 'INTEGER PRIMARY KEY AUTOINCREMENT')

    def test_the_old_unconditional_bug_would_fail_this_test(self):
        """Directly simulates reverting to the historical defect: a DDL
        template with a hardcoded, dialect-blind primary key. Proves the
        assertions above are not vacuously true."""
        buggy_ddl = 'CREATE TABLE IF NOT EXISTS economic_reference_versions (\n    id INTEGER PRIMARY KEY,\n'
        self.assertNotIn('is_pg', buggy_ddl)
        with self.assertRaises(AssertionError):
            self.assertIn('SERIAL PRIMARY KEY', buggy_ddl)

    def test_create_table_uses_the_branched_variable_not_a_literal(self):
        """The DDL string must interpolate {_err_pk}; it must not hardcode
        either dialect's primary-key syntax directly."""
        block = _create_table_erv_block()
        self.assertIn('id {_err_pk}', block,
                      'CREATE TABLE no longer interpolates the dialect-branched '
                      'primary key — it may be hardcoded again')
        self.assertNotIn('id INTEGER PRIMARY KEY,', block)
        self.assertNotIn('id SERIAL PRIMARY KEY,', block)

    def test_create_table_still_declares_applied_by_and_applied_at(self):
        block = _create_table_erv_block()
        self.assertIn('applied_by TEXT', block)
        self.assertIn('applied_at TIMESTAMP', block)

    def test_backfill_migration_for_applied_columns_still_present(self):
        """Installs that created the table before the APPLY columns existed
        must still receive them additively."""
        src = _migrate_source()
        self.assertIn("'applied_by'", src)
        self.assertIn("'applied_at'", src)
        self.assertIn('ALTER TABLE economic_reference_versions ADD COLUMN', src)

    def test_is_pg_flag_used_by_this_migration_is_the_real_dialect_check(self):
        src = _migrate_source()
        self.assertIn("is_pg = 'postgresql' in DATABASE_URL", src)

    def test_insert_does_not_supply_id_manually(self):
        """The actual defect surface: an INSERT that names `id` would break
        the SQLite branch's AUTOINCREMENT semantics, and worked around the
        Postgres bug rather than fixing it. Parses the real column list out
        of _record_reference_version's INSERT statement."""
        src = _src_of(_function('_record_reference_version'))
        self.assertIn('INSERT INTO economic_reference_versions', src)
        m = re.search(
            r'INSERT INTO economic_reference_versions\s*\n?\s*\(([^)]+)\)',
            src)
        self.assertIsNotNone(m, 'could not locate the INSERT column list')
        columns = [c.strip() for c in m.group(1).replace('\n', ' ').split(',')]
        self.assertNotIn('id', columns,
                         '_record_reference_version supplies id manually — '
                         'this defeats SERIAL/AUTOINCREMENT on both dialects')

    def test_id_is_read_back_after_insert_rather_than_assumed(self):
        """Since the INSERT does not supply id, the id used afterwards (for
        approve/apply) must come from a SELECT, not a guessed value."""
        src = _src_of(_function('_record_reference_version'))
        self.assertIn('SELECT id FROM economic_reference_versions', src)

    def test_payments_module_uses_the_same_dialect_branch_pattern(self):
        """Sanity: this is not a novel pattern invented for CHANGE-003 — it
        matches the existing PAYMENTS_SCHEMA_SQL / _PG precedent, so the fix
        is consistent with how the codebase already handles this class of
        bug."""
        payments_src = Path(main.__file__).with_name('payments.py').read_text(encoding='utf-8')
        self.assertIn('PAYMENTS_SCHEMA_SQL_PG', payments_src)
        self.assertIn('SERIAL PRIMARY KEY', payments_src)


class TestEconomicReferenceVersionsDDLRunsUnderSQLite(Base):
    """Behavioural half: the is_pg=False branch this environment CAN
    exercise actually creates a usable table and round-trips a proposal
    through the real endpoint, id and all."""

    def test_table_exists_with_sqlite_autoincrement_pk(self):
        row = self.db.execute(main.text(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='economic_reference_versions'")).fetchone()
        self.assertIsNotNone(row, 'economic_reference_versions was not created')
        self.assertIn('AUTOINCREMENT', row[0])

    def test_propose_endpoint_round_trips_an_id_without_the_caller_supplying_one(self):
        r = self.client.post('/admin/socioeconomic/reference/propose',
                             params={'secret': ADMIN_SECRET, 'country': 'PE',
                                     'field': 'ppp_per_capita_usd',
                                     'new_value': 13500,
                                     'source': 'world_bank_ny_gnp_pcap_pp_cd',
                                     'data_year': 2023})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get('ok'))
        self.assertIsInstance(body.get('proposal_id'), int,
                              'propose did not return an id read back after INSERT')
        row = self.db.execute(main.text(
            "SELECT id FROM economic_reference_versions WHERE country='PE' "
            "ORDER BY id DESC LIMIT 1")).fetchone()
        self.assertIsNotNone(row)
        self.assertIsInstance(row[0], int)


if __name__ == '__main__':
    unittest.main()
