"""
test_socioeconomic_estimator_remediation.py — CHANGE-003 socioeconomic
estimator remediation (post input-sensitivity-audit fixes).

Covers, against the REAL canonical estimator (main._assign_user_tier /
socioeconomic.classify), never a parallel/mock formula:

  FIX 1  — idempotency: repeated recalculation must never compound.
  FIX 2  — company-size canonicalization (numeric headcount vs '500+' alias).
  FIX 3  — occupation title resolution (free-text -> canonical SOC code).
  FIX 4  — occupation_unified schema exists on a fresh database.
  FIX 5  — cargo has zero numeric effect on the estimate (documented, not invented).
  FIX 7  — declared-income precedence, household-income isolation, determinism.
  FIX 9  — input-sensitivity regression, repeated 10x per profile.
  FIX 10 — structural search: no age/occupation/company-size/commune -> tier shortcut.

LOCAL / TEST ONLY. DATABASE_URL is forced to a throwaway sqlite file; no
production credential is read and no network call is made.
"""

import ast
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='socio-remediation-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-socio-remediation'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-socio-remediation'
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402
import socioeconomic as S                      # noqa: E402
import eligibility as E                        # noqa: E402
import usa_data_agent as USA                   # noqa: E402

MAIN_SRC = Path(main.__file__).read_text(encoding='utf-8')
MAIN_TREE = ast.parse(MAIN_SRC)

_seq = {'n': 0}


def _uid():
    _seq['n'] += 1
    return _seq['n']


_REFERENCE_DATA_SEEDED = {'done': False}


def _seed_reference_data_once(db):
    """Seeds shared, REAL-schema reference data exactly once for the whole
    module run: a country PPP row, the REAL 818-row BLS SOC import into
    occupation_unified (FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 3 —
    usa_data_agent.import_bls_occupations_to_db, the same function the
    /admin/import-bls-occupations endpoint calls; not a parallel hand-typed
    fixture) plus a CL ISCO income row (so occupation resolution has
    something real to return for non-US users), and two distinct Chilean
    communes. All of this is test fixture data in an isolated throwaway
    sqlite file — never production, never a parallel formula. A short-lived
    session, committed and not held open, to avoid the SQLite single-writer
    lock contention a persistent setUpClass session across many test
    classes would cause."""
    if _REFERENCE_DATA_SEEDED['done']:
        return
    db.execute(main.text(
        "CREATE TABLE IF NOT EXISTS world_countries (iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)"))
    db.execute(main.text(
        "INSERT OR REPLACE INTO world_countries (iso2, gdp_per_capita_usd) VALUES ('CL', 26000.0)"))
    _bls_result = USA.import_bls_occupations_to_db(db)
    assert _bls_result['ok'] and _bls_result['total'] == 818, _bls_result
    db.execute(main.text("""
        INSERT INTO occupation_unified
          (country_iso, occupation_type, isco_group, profession_score, median_annual_usd)
        VALUES ('CL', 'ISCO', 2, 78.0, 42000)
    """))
    # occupation_salary (occupation_salary_agent.py's real schema) — this is
    # the table the GUARDED write site reads (main.py: "if _occ_row[1] and
    # not user.estimated_income_usd:"), the exact site the original
    # compounding bug lived in. profession='medico' resolves via
    # PROFESSION_TO_ISCO -> isco_group=2 -> this row.
    db.execute(main.text("""
        CREATE TABLE IF NOT EXISTS occupation_salary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, country_iso TEXT NOT NULL, isco_group INTEGER NOT NULL,
            isco_label TEXT DEFAULT '', median_monthly_local REAL, median_monthly_usd REAL,
            currency TEXT DEFAULT '', profession_score REAL DEFAULT 0, year INTEGER, source TEXT DEFAULT '',
            updated_at TIMESTAMP, UNIQUE (country_iso, isco_group))
    """))
    db.execute(main.text("""
        INSERT OR REPLACE INTO occupation_salary (country_iso, isco_group, median_monthly_usd, profession_score, year, source)
        VALUES ('CL', 2, 2600.0, 65.0, 2025, 'remediation-test-seed')
    """))
    for commune, tier, idx, m2 in [('Conchalí', 'C', 45.0, 45.0), ('Las Condes', 'A', 95.0, 95.0)]:
        db.add(main.CommuneMarketData(country='CL', commune=commune, se_tier=tier,
                                      income_index=idx, price_m2_avg=m2, cpm_usd=6.0))
    db.commit()
    _REFERENCE_DATA_SEEDED['done'] = True


class Base(unittest.TestCase):

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)
        _seed_reference_data_once(self.db)

    def mk_user(self, age=40, profession='17-2112', company_size='+1000', county='Conchalí', **kw):
        n = _uid()
        today = date.today()
        dob = date(today.year - age, today.month, today.day).isoformat()
        base = dict(email=f'sremuser{n}@test.local', name=f'U{n}', password='x',
                   country='CL', county=county, gender='F', dob=dob,
                   profession=profession, company_size=company_size, role='voter',
                   referral_code=f'SREM{n:06d}')
        base.update(kw)
        u = main.User(**base)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def recompute(self, u):
        main._assign_user_tier(u, self.db)
        self.db.refresh(u)
        return u.estimated_income_usd, u.se_tier, u.se_tier_source


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1 — referral-tier-inheritance BLOCKER removed
# ═══════════════════════════════════════════════════════════════════════

class TestReferralTierNoLongerInherited(Base):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def mk_referrer(self, tier):
        n = _uid()
        u = main.User(email=f'referrer{n}@test.local', name=f'Ref{n}', password='x',
                      country='CL', county='Las Condes', gender='F', dob='1985-01-01',
                      role='voter', se_tier=tier, income_index=90.0,
                      referral_code=f'REF{n:06d}')
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def register_via_referrer(self, referrer, **overrides):
        n = _uid()
        payload = dict(name='New User', email=f'referred{n}@test.local', password='x',
                       country='CL', phone='', profession='', cargo='',
                       national_id=f'{n}1111111-{n % 10}', ref_code=referrer.referral_code)
        payload.update(overrides)
        r = self.client.post('/voter/register', json=payload)
        self.assertEqual(r.status_code, 200, r.text)
        u = self.db.query(main.User).filter(main.User.email == payload['email']).first()
        self.db.refresh(u)
        return u

    def test_referrer_tier_a_does_not_make_new_user_a(self):
        ref = self.mk_referrer('A')
        u = self.register_via_referrer(ref)
        self.assertNotEqual(u.se_tier, 'A')
        self.assertEqual(u.se_tier, '')

    def test_referrer_tier_b_does_not_make_new_user_b(self):
        ref = self.mk_referrer('B')
        u = self.register_via_referrer(ref)
        self.assertNotEqual(u.se_tier, 'B')
        self.assertEqual(u.se_tier, '')

    def test_referrer_tier_c_does_not_make_new_user_c(self):
        ref = self.mk_referrer('C')
        u = self.register_via_referrer(ref)
        self.assertNotEqual(u.se_tier, 'C')
        self.assertEqual(u.se_tier, '')

    def test_referrer_tier_d_does_not_make_new_user_d(self):
        ref = self.mk_referrer('D')
        u = self.register_via_referrer(ref)
        self.assertNotEqual(u.se_tier, 'D')
        self.assertEqual(u.se_tier, '')

    def test_tier_pre_evaluated_flag_is_never_set_true_anymore(self):
        ref = self.mk_referrer('A')
        u = self.register_via_referrer(ref)
        self.assertFalse(u.tier_pre_evaluated)

    def test_referral_relationship_itself_is_preserved(self):
        """The FEATURE (who invited whom) is legitimate and untouched —
        only the tier fabrication is removed."""
        ref = self.mk_referrer('A')
        u = self.register_via_referrer(ref)
        self.assertEqual(u.referred_by_user_id, ref.id)

    def test_users_own_legitimate_evidence_still_classifies_normally(self):
        """A referred user WITH their own real occupation/commune evidence
        must still classify normally from THAT evidence — this fix only
        removes the fabricated fallback, not real classification."""
        ref = self.mk_referrer('D')   # low-tier referrer, to prove it's ignored either way
        u = self.register_via_referrer(ref, profession='17-2112', company_size='+1000',
                                       commune='Conchalí', dob='1986-01-01')
        self.assertNotEqual(u.se_tier, '')
        self.assertIsNotNone(u.estimated_income_usd)

    def test_unresolved_referred_user_is_treated_as_unknown_by_change002(self):
        """CHANGE-002 must treat this exactly like any other UNRESOLVED
        user — deny a tier-restricted target, never guess from the
        referral."""
        ref = self.mk_referrer('A')
        u = self.register_via_referrer(ref)
        self.assertEqual(u.se_tier, '')
        prof = main._build_profile(u, self.db)
        decision = E._combine([E._check_tier(prof, {'A', 'B'})])
        self.assertFalse(decision.allowed, 'an UNRESOLVED (non-inherited) tier must not satisfy a tier target')

    def test_inherited_tier_diagnostic_field_carries_no_weight_in_matching(self):
        """Even if tier_pre_evaluated were somehow True on old/legacy data,
        eligibility.py must not use it to grant anything — it is read only
        for a diagnostic string (audit finding Q)."""
        u = self.mk_user(age=40, profession='17-2112', company_size='+1000')
        u.tier_pre_evaluated = True
        u.se_tier = ''   # still unresolved despite the flag
        self.db.commit()
        prof = main._build_profile(u, self.db)
        decision = E._combine([E._check_tier(prof, {'A', 'B'})])
        self.assertFalse(decision.allowed)


# ═══════════════════════════════════════════════════════════════════════
# FIX 1 — idempotency (the BLOCKER)
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotency(Base):

    def test_repeated_calls_1_2_3_10_50_produce_identical_results(self):
        u = self.mk_user(age=40, profession='17-2112', company_size='+1000')
        results = [self.recompute(u) for _ in range(50)]
        checkpoints = {1: results[0], 2: results[1], 3: results[2], 10: results[9], 50: results[49]}
        for n, r in checkpoints.items():
            self.assertEqual(r, results[0], f'call #{n} diverged from call #1: {r} != {results[0]}')
        self.assertEqual(len(set(results)), 1, 'not every one of the 50 calls produced an identical result')

    def test_idempotency_holds_via_the_guarded_legacy_slug_write_site(self):
        """This is the ACTUAL site the original bug lived in: main.py's
        occupation_salary/PROFESSION_TO_ISCO fallback writes
        estimated_income_usd only `if _occ_row[1] and not
        user.estimated_income_usd` — a guard that, without the Fix 1
        reset, lets a stale already-multiplied value block the fresh
        write on any call after the first. A SOC-code profession like
        '17-2112' does NOT exercise this guard (its own write sites are
        unconditional). 'medico' doesn't either in THIS suite specifically
        — it's also a key in the EARLIER, unguarded _OCC_TO_ISCO lookup,
        which (now that this suite's own Fix 3/4 fixtures seed a matching
        occupation_unified CL/ISCO=2 row) resolves and short-circuits
        before the guarded fallback is ever reached. 'veterinario' is a
        PROFESSION_TO_ISCO-only key (confirmed absent from _OCC_TO_ISCO)
        and correctly isolates the guarded path — reproduces the original
        bug exactly (38064 -> 46438 -> 56654 -> ...) when the Fix 1 reset
        is removed; this test failing to catch that with 'medico' instead
        is exactly how this comment came to be this precise."""
        u = self.mk_user(age=40, profession='veterinario', company_size='+1000')
        results = [self.recompute(u) for _ in range(10)]
        self.assertEqual(len(set(results)), 1,
                         f'the guarded legacy-slug write site compounded across calls: {results}')
        # Sanity: this must actually be resolving through the occupation
        # signal, not silently falling back to something else.
        self.assertEqual(results[0][2], 'estimated_occupation')

    def test_idempotency_holds_for_a_non_trivial_company_size_multiplier(self):
        """The bug specifically only manifested when the multiplier != 1.00
        — cover a bucket where it genuinely isn't 1.00 (own separate case
        from the 51-250/1.00 no-op bucket, which would mask the bug)."""
        for size in ('1-10', '11-50', '251-1000', '+1000'):
            u = self.mk_user(age=50, profession='17-2112', company_size=size)
            results = [self.recompute(u) for _ in range(5)]
            self.assertEqual(len(set(results)), 1,
                             f'company_size={size!r} (non-1.00 multiplier) compounded across calls')

    def test_idempotency_holds_across_multiple_ages(self):
        for age in (19, 25, 30, 40, 50, 60):
            u = self.mk_user(age=age, profession='17-2112', company_size='251-1000')
            results = [self.recompute(u) for _ in range(5)]
            self.assertEqual(len(set(results)), 1, f'age={age} compounded across calls')

    def test_recalculation_never_overwrites_a_declared_income_with_an_estimate(self):
        u = self.mk_user(age=40, profession='17-2112', company_size='+1000')
        self.recompute(u)
        u.declared_income_amount = 800_000
        u.declared_income_currency = 'CLP'
        u.declared_income_period = 'monthly'
        u.declared_income_confirmed = False
        self.db.commit()
        results = [self.recompute(u) for _ in range(10)]
        sources = {r[2] for r in results}
        self.assertEqual(sources, {'declared'}, 'a recalculation drifted the source away from declared')
        tiers = {r[1] for r in results}
        self.assertEqual(len(tiers), 1, 'repeated recalculation changed the declared-income tier')


# ═══════════════════════════════════════════════════════════════════════
# FIX 2 — company-size canonicalization
# ═══════════════════════════════════════════════════════════════════════

class TestCompanySizeCanonicalization(unittest.TestCase):

    def test_canonical_buckets_are_identity(self):
        for bucket, rank in [('1-10', 1), ('11-50', 2), ('51-250', 3), ('251-1000', 4), ('+1000', 5)]:
            self.assertEqual(E.norm_company_size(bucket), rank)

    def test_numeric_500_resolves_to_251_1000_not_1000_plus(self):
        self.assertEqual(E.norm_company_size(500), 4)
        self.assertEqual(E.norm_company_size('500'), 4)
        self.assertEqual(E.norm_company_size(251), 4)
        self.assertEqual(E.norm_company_size(1000), 4)

    def test_numeric_boundaries(self):
        self.assertEqual(E.norm_company_size(10), 1)
        self.assertEqual(E.norm_company_size(11), 2)
        self.assertEqual(E.norm_company_size(50), 2)
        self.assertEqual(E.norm_company_size(51), 3)
        self.assertEqual(E.norm_company_size(250), 3)
        self.assertEqual(E.norm_company_size(1001), 5)

    def test_legacy_alias_500_plus_preserved_exactly_as_before(self):
        """Historical compatibility (audit finding K): '500+' is a
        pre-existing legacy ALIAS for the top bucket (matches
        marketer_portal.html's own UI copy and _HNW_COMPANY_BIG), not a
        literal count — must stay rank 5, unchanged."""
        self.assertEqual(E.norm_company_size('500+'), 5)

    def test_other_legacy_aliases_unchanged(self):
        for legacy, rank in [('51-200', 3), ('100-499', 3), ('201-500', 4)]:
            self.assertEqual(E.norm_company_size(legacy), rank)

    def test_free_text_aliases_unchanged(self):
        for word, rank in [('large', 4), ('grande', 4), ('enterprise', 5), ('micro', 1), ('small', 2)]:
            self.assertEqual(E.norm_company_size(word), rank)

    def test_invalid_numeric_input_is_unknown_not_fabricated(self):
        self.assertEqual(E.norm_company_size(0), 0)
        self.assertEqual(E.norm_company_size(-5), 0)

    def test_blank_and_none_are_unknown(self):
        self.assertEqual(E.norm_company_size(''), 0)
        self.assertEqual(E.norm_company_size(None), 0)

    def test_unrecognised_string_is_unknown_no_fuzzy_matching(self):
        self.assertEqual(E.norm_company_size('a really big company honestly'), 0)


class TestCompanySizeCanonicalizationEndToEnd(Base):

    def test_251_1000_and_500_plus_alias_produce_different_estimates(self):
        """Direct proof the two representations are NOT silently conflated
        (audit finding K's core ambiguity, now resolved and measurable)."""
        u_range = self.mk_user(age=40, profession='17-2112', company_size='251-1000')
        u_alias = self.mk_user(age=40, profession='17-2112', company_size='500+')
        est_range, _, _ = self.recompute(u_range)
        est_alias, _, _ = self.recompute(u_alias)
        self.assertNotEqual(est_range, est_alias)
        self.assertLess(est_range, est_alias, "251-1000 (rank 4, mult 1.13) must be less than the "
                                              "'500+' legacy alias (rank 5, mult 1.22)")

    def test_numeric_500_matches_251_1000_not_the_alias(self):
        u_numeric = self.mk_user(age=40, profession='17-2112', company_size='500')
        u_range = self.mk_user(age=40, profession='17-2112', company_size='251-1000')
        est_numeric, _, _ = self.recompute(u_numeric)
        est_range, _, _ = self.recompute(u_range)
        self.assertEqual(est_numeric, est_range)


class TestCompanySizeUIConsistency(unittest.TestCase):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 6 — verified by
    reading the literal HTML form values: voter_portal.html's registration
    <select> already emits the fully canonical 5-bucket vocabulary
    directly ('1-10'/'11-50'/'51-250'/'251-1000'/'+1000' -- no '500+'
    anywhere), and marketer_portal.html's targeting chips emit the bucket
    names ('small'/'medium'/'large') that _COMPANY_BUCKET_RANKS already
    expects. The literal string '500+' is NOT emitted by any current UI --
    it only exists as a historical/legacy stored value (and in UI COPY
    text like "Grande 500+", which is a label, not the submitted value).
    This test pins that finding: if a future UI change starts submitting
    a value this vocabulary doesn't recognise, this fails loudly instead
    of silently degrading to rank 0 (unknown)."""

    _VOTER_REGISTRATION_SELECT_VALUES = ['1-10', '11-50', '51-250', '251-1000', '+1000']
    _MARKETER_TARGETING_CHIP_VALUES = ['small', 'medium', 'large']

    def test_voter_registration_select_values_are_all_canonical_and_distinct(self):
        ranks = [E.norm_company_size(v) for v in self._VOTER_REGISTRATION_SELECT_VALUES]
        self.assertEqual(ranks, [1, 2, 3, 4, 5])

    def test_marketer_targeting_chip_values_all_resolve_to_nonempty_rank_sets(self):
        for chip in self._MARKETER_TARGETING_CHIP_VALUES:
            ranks = E.company_size_target_ranks(chip)
            self.assertTrue(ranks, f'{chip!r} chip resolved to an empty rank set')

    def test_marketer_large_chip_covers_both_251_1000_and_the_top_bucket(self):
        """'large' is documented in the UI as "Grande 500+" -- covering
        BOTH the 251-1000 and +1000 canonical ranks keeps that promise for
        a voter in either bucket, without asserting '500+' means exactly
        one of them."""
        self.assertEqual(E.company_size_target_ranks('large'), {4, 5})

    def test_html_forms_still_contain_exactly_the_values_this_test_pins(self):
        """If someone edits the <select>/chip markup without updating this
        test, this catches the drift explicitly instead of the two files
        silently disagreeing."""
        voter_html = Path(main.__file__).parent.joinpath('voter_portal.html').read_text(encoding='utf-8')
        for v in self._VOTER_REGISTRATION_SELECT_VALUES:
            self.assertIn(f'value="{v}"', voter_html, f'voter_portal.html no longer offers {v!r}')
        marketer_html = Path(main.__file__).parent.joinpath('marketer_portal.html').read_text(encoding='utf-8')
        for v in self._MARKETER_TARGETING_CHIP_VALUES:
            self.assertIn(f'data-value="{v}"', marketer_html, f'marketer_portal.html no longer offers {v!r}')


# ═══════════════════════════════════════════════════════════════════════
# FIX 3 — occupation title resolution
# ═══════════════════════════════════════════════════════════════════════

class TestOccupationTitleResolution(unittest.TestCase):

    def test_spanish_supported_title(self):
        self.assertEqual(S.resolve_occupation_soc('Ingeniero Industrial'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('ingeniero industrial'), '17-2112')

    def test_english_supported_title(self):
        self.assertEqual(S.resolve_occupation_soc('Industrial Engineer'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('Industrial Engineers'), '17-2112')

    def test_canonical_code(self):
        self.assertEqual(S.resolve_occupation_soc('17-2112'), '17-2112')

    def test_capitalization_and_whitespace_insensitive(self):
        for v in ('INGENIERO INDUSTRIAL', '  Ingeniero   Industrial  ',
                  'ingeniero  industrial', 'Ingeniero\tIndustrial'):
            self.assertEqual(S.resolve_occupation_soc(v), '17-2112', f'failed for {v!r}')

    def test_snake_case_legacy_slug_is_out_of_scope_for_this_resolver(self):
        """Preferendum's own internal snake_case slugs (e.g. 'ing_civil',
        'ing_comercial') already have their own resolution path (main.py's
        _US_PROFESSION_SOC/_OCC_TO_ISCO / eligibility.norm_occupation) at
        the coarser major-group level and were never natural-language
        titles a user typed — this resolver correctly leaves them
        unresolved, not guessed. (GLOBAL OCCUPATION RESOLUTION HARDENING —
        unlike 'medico', which WAS a legacy slug under the old design and
        is now also a genuine, deliberately-added Spanish alias; see
        TestCanonicalOccupationRegistry.)"""
        self.assertEqual(S.resolve_occupation_soc('ing_civil'), '')
        self.assertEqual(S.resolve_occupation_soc('ing_comercial'), '')

    def test_unknown_occupation_returns_empty_not_fabricated(self):
        self.assertEqual(S.resolve_occupation_soc('Astronauta Marciano'), '')
        self.assertEqual(S.resolve_occupation_soc('Dragon Trainer'), '')

    def test_blank_and_none(self):
        self.assertEqual(S.resolve_occupation_soc(''), '')
        self.assertEqual(S.resolve_occupation_soc(None), '')

    def test_no_fuzzy_matching_a_near_miss_does_not_resolve(self):
        """'Ingeniero Comercial' is a REAL, different, already-supported
        legacy slug (ing_comercial) -- must NOT accidentally resolve to
        Industrial Engineer just because it shares a word."""
        self.assertEqual(S.resolve_occupation_soc('Ingeniero Comercial'), '')
        self.assertEqual(S.resolve_occupation_soc('Ingeniero'), '')


class TestOccupationTitleResolutionEndToEnd(Base):

    def test_all_recognized_representations_produce_the_same_income(self):
        titles = ['17-2112', 'Ingeniero Industrial', 'ingeniero industrial',
                 'Industrial Engineer', 'Industrial Engineers', '  INDUSTRIAL   ENGINEERS  ']
        results = []
        for title in titles:
            u = self.mk_user(age=40, profession=title, company_size='+1000')
            est, tier, src = self.recompute(u)
            results.append((title, est, tier))
        estimates = {r[1] for r in results}
        tiers = {r[2] for r in results}
        self.assertEqual(len(estimates), 1, f'representations diverged: {results}')
        self.assertEqual(len(tiers), 1, f'tiers diverged: {results}')
        self.assertIsNotNone(results[0][1])

    def test_unknown_occupation_falls_back_honestly_and_differs_from_resolved(self):
        u_known = self.mk_user(age=40, profession='Ingeniero Industrial', company_size='+1000')
        u_unknown = self.mk_user(age=40, profession='Astronauta Marciano', company_size='+1000')
        est_known, _, src_known = self.recompute(u_known)
        est_unknown, _, src_unknown = self.recompute(u_unknown)
        self.assertNotEqual(est_known, est_unknown,
                            'an unresolved occupation must not coincide with a resolved one\'s real data')


# ═══════════════════════════════════════════════════════════════════════
# FIX 4 — occupation_unified schema on a fresh database
# ═══════════════════════════════════════════════════════════════════════

class TestFreshDatabaseOccupationSchema(unittest.TestCase):
    """A SEPARATE, genuinely fresh sqlite file/import — not the shared
    module-level DB the other classes use — to prove the schema exists
    from _migrate() alone, with zero manual seeding."""

    def test_occupation_unified_exists_with_the_columns_the_code_reads(self):
        import subprocess, sys
        script = '''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-occ-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
from sqlalchemy import inspect as sa_inspect
cols = {c["name"] for c in sa_inspect(main.engine).get_columns("occupation_unified")}
required = {"occupation_code", "country_iso", "occupation_type", "isco_group",
            "isco_label", "title", "profession_score", "median_annual_usd"}
missing = required - cols
assert not missing, f"missing columns: {missing}"
count = main.SessionLocal().execute(main.text("SELECT COUNT(*) FROM occupation_unified")).scalar()
print(f"OK columns={sorted(cols)} rows={count}")
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(main.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)

    def test_estimator_does_not_crash_against_a_fresh_empty_occupation_unified(self):
        import subprocess, sys
        script = '''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-occ2-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
db = main.SessionLocal()
u = main.User(email="fresh@test.local", name="U", password="x", country="CL", county="",
              gender="F", dob="1986-01-01", profession="17-2112", company_size="+1000",
              role="voter", referral_code="FRESH001")
db.add(u); db.commit(); db.refresh(u)
main._assign_user_tier(u, db)   # must not raise
print("OK no crash")
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(main.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3 — occupation_unified data completeness: real BLS SOC import
# ═══════════════════════════════════════════════════════════════════════

class TestBLSOccupationImport(unittest.TestCase):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 3 — a SEPARATE,
    genuinely fresh sqlite file/import per test (subprocess, matching
    TestFreshDatabaseOccupationSchema's convention), proving
    usa_data_agent.import_bls_occupations_to_db (the same function
    /admin/import-bls-occupations calls) provisions occupation_unified
    from the tracked bls_occupation_scores_2025.csv with no production
    dependency, deterministically, idempotently, and that Industrial
    Engineer / SOC 17-2112 resolves end-to-end afterward for both a US
    user (direct SOC lookup) and a non-US user (SOC -> isco_group ->
    country fallback path)."""

    def _run(self, script):
        import subprocess, sys
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(main.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_fresh_db_import_inserts_all_818_rows_no_fabrication(self):
        out = self._run('''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-bls-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
import usa_data_agent as USA
import csv
db = main.SessionLocal()
result = USA.import_bls_occupations_to_db(db)
assert result["ok"] and result["inserted"] == 818 and result["total"] == 818, result
count = db.execute(main.text(
    "SELECT COUNT(*) FROM occupation_unified WHERE country_iso=\\'US\\' AND occupation_type=\\'SOC\\'"
)).scalar()
assert count == 818, count
# Cross-check every row against the tracked CSV directly -- no fabrication.
with open("bls_occupation_scores_2025.csv", encoding="utf-8") as f:
    csv_rows = {r["soc_code"]: r for r in csv.DictReader(f)}
assert len(csv_rows) == 818
db_rows = db.execute(main.text(
    "SELECT occupation_code, title, profession_score, median_annual_usd "
    "FROM occupation_unified WHERE country_iso=\\'US\\' AND occupation_type=\\'SOC\\'"
)).fetchall()
assert len(db_rows) == 818
for code, title, score, median in db_rows:
    csv_row = csv_rows[code]
    assert title == csv_row["title"], (code, title, csv_row["title"])
    assert abs(float(score) - float(csv_row["profession_score"])) < 1e-6, code
    assert abs(float(median) - float(csv_row["national_median_salary_usd"])) < 1e-6, code
print("OK all 818 rows match CSV exactly")
''')
        self.assertIn('OK', out)

    def test_rerunning_import_is_idempotent_no_duplicates(self):
        out = self._run('''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-bls2-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
import usa_data_agent as USA
db = main.SessionLocal()
r1 = USA.import_bls_occupations_to_db(db)
r2 = USA.import_bls_occupations_to_db(db)
r3 = USA.import_bls_occupations_to_db(db)
assert r1["inserted"] == 818 and r1["updated"] == 0, r1
assert r2["inserted"] == 0 and r2["updated"] == 818, r2
assert r3["inserted"] == 0 and r3["updated"] == 818, r3
count = db.execute(main.text(
    "SELECT COUNT(*) FROM occupation_unified WHERE country_iso=\\'US\\' AND occupation_type=\\'SOC\\'"
)).scalar()
assert count == 818, f"duplicate rows after 3 runs: {count}"
print("OK idempotent across 3 runs, no duplicates")
''')
        self.assertIn('OK', out)

    def test_industrial_engineer_end_to_end_from_fresh_db_us_user(self):
        out = self._run('''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-bls3-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
import usa_data_agent as USA
db = main.SessionLocal()
USA.import_bls_occupations_to_db(db)
u = main.User(email="ie_us@test.local", name="IE", password="x", country="US", county="",
              gender="F", dob="1990-01-01", profession="17-2112", company_size="+1000",
              role="voter", referral_code="FRESHIEUS")
db.add(u); db.commit(); db.refresh(u)
main._assign_user_tier(u, db)
db.refresh(u)
assert u.estimated_income_usd, "Industrial Engineer (US) must resolve an income estimate"
assert u.se_tier, "Industrial Engineer (US) must resolve a tier"
print(f"OK us_income={u.estimated_income_usd} us_tier={u.se_tier}")
''')
        self.assertIn('OK', out)

    def test_industrial_engineer_soc_code_resolves_isco_group_for_non_us_user(self):
        """Non-US users querying by raw SOC code depend on
        occupation_unified.isco_group (derived, not from the CSV directly —
        see _BLS_MAJOR_GROUP_TO_ISCO in usa_data_agent.py). This proves that
        derivation actually lands a usable isco_group for 17-2112, from a
        completely fresh DB, with no manual seeding."""
        out = self._run('''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-bls4-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(d, 'fresh.db')}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)
import main
import usa_data_agent as USA
db = main.SessionLocal()
USA.import_bls_occupations_to_db(db)
row = db.execute(main.text(
    "SELECT isco_group FROM occupation_unified WHERE occupation_code=\\'17-2112\\' AND country_iso=\\'US\\'"
)).fetchone()
assert row and row[0] == 2, f"Industrial Engineer must derive isco_group=2 (Professionals), got {row}"
print(f"OK isco_group={row[0]}")
''')
        self.assertIn('OK', out)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 11 — fresh database: full pipeline, not just schema
# ═══════════════════════════════════════════════════════════════════════

class TestFreshDatabaseFullPipeline(unittest.TestCase):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 11 — a SEPARATE,
    genuinely fresh sqlite file/import (subprocess), proving the ENTIRE
    chain works with ONLY repository-supported migrations/seeding and no
    hidden production-only requirement: occupation tables exist ->
    reference data loads reproducibly (the tracked BLS CSV) -> Industrial
    Engineer resolves -> income estimation works -> socioeconomic
    classification works -> CHANGE-002 matching actually CONSUMES that
    classification correctly (both a resolved tier passing a matching
    campaign, and an unresolved tier being denied one) -- not just that
    the schema exists (TestFreshDatabaseOccupationSchema) or that one
    occupation resolves in isolation (TestBLSOccupationImport)."""

    def test_full_chain_from_empty_db_to_a_matching_decision(self):
        import subprocess, sys
        script = '''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-full-")
_dbpath = os.path.join(d, "fresh.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_dbpath}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)

# 1. _migrate() alone (import main) must have created occupation_unified.
import main
from sqlalchemy import inspect as sa_inspect
assert sa_inspect(main.engine).has_table("occupation_unified"), "occupation_unified missing after fresh migrate"

# 2. Reference data loads reproducibly from the tracked repo CSV -- no
#    production dependency, no manual seed, just the repo-supported import.
import usa_data_agent as USA
r1 = USA.import_bls_occupations_to_db(main.SessionLocal())
r2 = USA.import_bls_occupations_to_db(main.SessionLocal())
assert r1["total"] == r2["total"] == 818, (r1, r2)

# 3. Industrial Engineer resolves end to end -> income estimation works.
db = main.SessionLocal()
u = main.User(email="ie@fresh.local", name="IE", password="x", country="US", county="",
              gender="F", dob="1990-01-01", profession="17-2112", company_size="+1000",
              role="voter", referral_code="FRESHFULL1")
db.add(u); db.commit(); db.refresh(u)
main._assign_user_tier(u, db)
db.refresh(u)
assert u.estimated_income_usd, "income estimation did not run"

# 4. Socioeconomic classification worked -- se_tier is a real letter.
assert u.se_tier in ("A", "B", "C", "D"), f"classification failed: se_tier={u.se_tier!r}"

# 5. CHANGE-002 matching actually CONSUMES that classification: a
#    same-tier-restricted campaign must ALLOW this user...
import eligibility as E
prof = main._build_profile(u, db)
target_same = E.CampaignTarget(tiers={u.se_tier}, gender="all")
decision_same = E.evaluate_campaign(prof, target_same)
assert decision_same.allowed, f"resolved tier did not satisfy its own tier target: {decision_same.reasons}"

# ...and a DIFFERENT-tier-restricted campaign must DENY this user.
_other_tier = "A" if u.se_tier != "A" else "D"
target_other = E.CampaignTarget(tiers={_other_tier}, gender="all")
decision_other = E.evaluate_campaign(prof, target_other)
assert not decision_other.allowed, "wrong-tier campaign incorrectly matched"

# 6. An UNRESOLVED user (no occupation, no commune, no country data at
#    all) must be DENIED a tier-restricted campaign, never guessed.
u2 = main.User(email="unresolved@fresh.local", name="U2", password="x", country="ZZ", county="",
               gender="F", dob="1990-01-01", profession="", company_size="",
               role="voter", referral_code="FRESHFULL2")
db.add(u2); db.commit(); db.refresh(u2)
main._assign_user_tier(u2, db)
db.refresh(u2)
assert u2.se_tier == "", f"expected UNRESOLVED, got se_tier={u2.se_tier!r}"
prof2 = main._build_profile(u2, db)
# A PROPER SUBSET of tiers, not all four -- targeting every tier is the
# documented NOT_CONSTRAINED case (a campaign with no real tier
# preference), which correctly passes ANY user including an unresolved
# one; this must genuinely constrain to actually exercise UNKNOWN/deny.
target_some_tiers = E.CampaignTarget(tiers={"A", "B"}, gender="all")
decision_unresolved = E.evaluate_campaign(prof2, target_some_tiers)
assert not decision_unresolved.allowed, "an UNRESOLVED tier must never satisfy a tier-restricted target"

print(f"OK income={u.estimated_income_usd} tier={u.se_tier} "
      f"matched_own_tier={decision_same.allowed} denied_other_tier={not decision_other.allowed} "
      f"unresolved_denied={not decision_unresolved.allowed}")
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(main.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5 — age: boundary values + no compounding
# ═══════════════════════════════════════════════════════════════════════

class TestAgeBoundaries(unittest.TestCase):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 5 — every boundary
    age named in the task, at the pure-function level. Brackets are
    inclusive-inclusive: (lo, hi) with `lo <= a <= hi`."""

    _EXPECTED = {
        18: 0.55, 19: 0.55, 24: 0.55,   # 0-24
        25: 0.72, 29: 0.72,             # 25-29
        30: 0.87, 34: 0.87,             # 30-34
        35: 1.00, 44: 1.00,             # 35-44 (peak)
        45: 1.08, 54: 1.08,             # 45-54
        55: 1.05, 64: 1.05,             # 55-64
        65: 0.85,                       # 65+
    }

    def test_every_specified_boundary_age(self):
        for age, expected in self._EXPECTED.items():
            self.assertAlmostEqual(S.age_income_multiplier(age), expected, places=6,
                                   msg=f'age={age}')

    def test_bracket_transitions_are_exactly_where_expected(self):
        # One year on either side of each boundary must NOT share a value
        # with the boundary itself, proving the cut is exactly there.
        self.assertNotEqual(S.age_income_multiplier(24), S.age_income_multiplier(25))
        self.assertNotEqual(S.age_income_multiplier(29), S.age_income_multiplier(30))
        self.assertNotEqual(S.age_income_multiplier(34), S.age_income_multiplier(35))
        self.assertNotEqual(S.age_income_multiplier(44), S.age_income_multiplier(45))
        self.assertNotEqual(S.age_income_multiplier(54), S.age_income_multiplier(55))
        self.assertNotEqual(S.age_income_multiplier(64), S.age_income_multiplier(65))

    def test_unknown_age_is_neutral_not_penalized_or_boosted(self):
        self.assertEqual(S.age_income_multiplier(None), 1.0)
        self.assertEqual(S.age_income_multiplier(''), 1.0)
        self.assertEqual(S.age_income_multiplier('not-a-number'), 1.0)
        self.assertEqual(S.age_income_multiplier(-5), 1.0)


class TestAgeBoundariesEndToEnd(Base):
    """Same 14 boundary ages, through the REAL estimator end-to-end, each
    recomputed 10x to prove no compounding at any specific boundary (not
    just the single age=40 already covered by TestIdempotency)."""

    def test_every_boundary_age_is_stable_across_10_recomputations(self):
        for age in (18, 19, 24, 25, 29, 30, 34, 35, 44, 45, 54, 55, 64, 65):
            u = self.mk_user(age=age, profession='17-2112', company_size='+1000')
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1,
                             f'age={age} diverged across 10 recomputations: {results}')

    def test_older_bracket_never_produces_a_lower_income_than_the_peak_for_identical_role(self):
        """Sanity check on the curve's own documented shape (peak at 35-44,
        not a monotonic claim across the whole curve) -- 45-54 (1.08) must
        exceed the 35-44 peak (1.00) reference, per the curve's own values,
        not re-derive the multipliers."""
        u_peak = self.mk_user(age=40, profession='17-2112', company_size='+1000')
        u_45 = self.mk_user(age=50, profession='17-2112', company_size='+1000')
        income_peak, _, _ = self.recompute(u_peak)
        income_45, _, _ = self.recompute(u_45)
        self.assertGreater(income_45, income_peak)


# ═══════════════════════════════════════════════════════════════════════
# FIX 5 — cargo: documented as unused, not invented
# ═══════════════════════════════════════════════════════════════════════

class TestCargoHasNoEffect(Base):

    def test_cargo_never_changes_the_estimate(self):
        results = []
        for cargo in ('', 'ceo', 'gerente', 'analista', 'becario'):
            u = self.mk_user(age=40, profession='17-2112', company_size='+1000', cargo=cargo)
            results.append(self.recompute(u))
        estimates = {r[0] for r in results}
        tiers = {r[1] for r in results}
        self.assertEqual(len(estimates), 1, f'cargo changed the estimate: {results}')
        self.assertEqual(len(tiers), 1, f'cargo changed the tier: {results}')

    def test_cargo_tier_dict_is_confirmed_dead_never_read(self):
        """_CARGO_TIER (main.py) is the archaeological remnant of the exact
        cargo->tier promotion bug CHANGE-003 already documented removing
        elsewhere in this same file. Its own comment used to claim it
        "eleva el tier independientemente de profesión o comuna" — this
        proves that claim is false: the dict is defined and never read
        anywhere else. If a future change ever wires it up, restoring a
        direct cargo->tier mapping would be exactly the R1/R8 violation
        CHANGE-003 exists to prevent — this test must keep failing that."""
        # Only count references on NON-comment lines — main.py's own
        # remediation comment explaining this dead-code finding mentions
        # the name too, which is not a code reference.
        code_matches = [line for line in MAIN_SRC.splitlines()
                        if '_CARGO_TIER' in line and not line.strip().startswith('#')]
        self.assertEqual(len(code_matches), 1,
                         f'_CARGO_TIER referenced in code {len(code_matches)} times — expected '
                         f'exactly 1 (its own definition); if this grew, cargo may now silently '
                         f'promote the tier: {code_matches}')

    def test_no_cargo_income_multiplier_exists_in_the_estimator(self):
        """Structural: no numeric read of user.cargo anywhere in the
        estimator body (only the diagnostic professional-profile dict may
        reference it)."""
        for node in ast.walk(MAIN_TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '_assign_user_tier_inner':
                body = ast.get_source_segment(MAIN_SRC, node)
                # Only comment-text mentions of "cargo" are allowed; no
                # `.cargo` attribute read anywhere in this function.
                self.assertNotIn('.cargo', body,
                                 '_assign_user_tier_inner reads .cargo — a cargo multiplier '
                                 'was added without business authorization')
                break
        else:
            self.fail('_assign_user_tier_inner not found')


# ═══════════════════════════════════════════════════════════════════════
# FIX 7 — declared-income integrity
# ═══════════════════════════════════════════════════════════════════════

class TestDeclaredIncomeIntegrity(Base):

    def test_estimate_never_overwrites_declared(self):
        u = self.mk_user(age=40, profession='17-2112', company_size='+1000',
                         declared_income_amount=5_000_000, declared_income_currency='CLP',
                         declared_income_period='monthly', declared_income_confirmed=False)
        est, tier, src = self.recompute(u)
        self.assertEqual(src, 'declared')

    def test_unconfirmed_declared_still_outranks_any_estimate(self):
        u = self.mk_user(age=40, profession='17-2112', company_size='+1000',
                         declared_income_amount=1, declared_income_currency='CLP',
                         declared_income_period='annual', declared_income_confirmed=False)
        est, tier, src = self.recompute(u)
        self.assertEqual(src, 'declared', 'an unconfirmed declared figure must still outrank an estimate')

    def test_household_income_never_substitutes_for_individual(self):
        u = self.mk_user(age=40, profession='', company_size='', county='',
                         household_income_amount=999_999_999, household_income_currency='CLP',
                         household_income_period='annual')
        obs = main._individual_income_observations(u, self.db)
        self.assertEqual(obs, [], 'household income leaked into individual observations')

    def test_currency_conversion_is_deterministic(self):
        u1 = self.mk_user(age=40, profession='', company_size='', county='',
                          declared_income_amount=1000, declared_income_currency='USD',
                          declared_income_period='annual')
        u2 = self.mk_user(age=40, profession='', company_size='', county='',
                          declared_income_amount=1000, declared_income_currency='USD',
                          declared_income_period='annual')
        obs1 = main._individual_income_observations(u1, self.db)
        obs2 = main._individual_income_observations(u2, self.db)
        self.assertEqual(obs1[0].annual_usd, obs2[0].annual_usd)

    def test_period_annualization_is_deterministic(self):
        u_monthly = self.mk_user(age=40, profession='', company_size='', county='',
                                 declared_income_amount=1000, declared_income_currency='USD',
                                 declared_income_period='monthly')
        obs = main._individual_income_observations(u_monthly, self.db)
        self.assertEqual(obs[0].annual_usd, 12000.0)


# ═══════════════════════════════════════════════════════════════════════
# FIX 9 — input-sensitivity regression, each profile run 10x for idempotency
# ═══════════════════════════════════════════════════════════════════════

class TestInputSensitivityRegression(Base):

    def _run_10x(self, **kw):
        u = self.mk_user(**kw)
        results = [self.recompute(u) for _ in range(10)]
        self.assertEqual(len(set(results)), 1, f'10x repeat diverged for {kw}: {results}')
        return results[0]

    def test_age_sensitivity_chile_conchali_industrial_engineer(self):
        seen = {}
        for age in (19, 25, 30, 40, 50, 60):
            est, tier, src = self._run_10x(age=age, profession='Ingeniero Industrial',
                                            company_size='251-1000', county='Conchalí')
            seen[age] = (est, tier)
        estimates = [v[0] for v in seen.values()]
        self.assertEqual(len(set(estimates)), len(estimates),
                         f'age produced no differentiation: {seen}')
        self.assertEqual(max(seen, key=lambda a: seen[a][0]), 50,
                         'peak-ish age band should yield the highest estimate in this profile')

    def test_company_size_sensitivity_all_canonical_buckets(self):
        seen = {}
        for size in ('1-10', '11-50', '51-250', '251-1000', '+1000'):
            est, tier, src = self._run_10x(age=40, profession='Ingeniero Industrial', company_size=size)
            seen[size] = est
        ordered = [seen[s] for s in ('1-10', '11-50', '51-250', '251-1000', '+1000')]
        self.assertEqual(ordered, sorted(ordered), f'company-size estimates not monotonic: {seen}')

    def test_occupation_sensitivity_multiple_recognized_occupations(self):
        est_industrial, _, _ = self._run_10x(age=40, profession='Ingeniero Industrial', company_size='+1000')
        est_unresolved, _, _ = self._run_10x(age=40, profession='Astronauta Marciano', company_size='+1000')
        self.assertNotEqual(est_industrial, est_unresolved)


_PHASE10_SEEDED = {'done': False}


def _seed_phase10_matrix_data_once(db):
    """Extends the shared fixture with 3 more Chilean communes (Ñuñoa,
    Puente Alto, Providencia -- alongside the already-seeded Conchalí/Las
    Condes) and occupation_salary rows for 4 more ISCO groups (1/3/5/7,
    alongside the already-seeded 2), all LOCAL test fixture data, so the
    Phase 10 controlled sensitivity matrix has >=5 materially different
    communes and occupations to vary. Exactly once per module run."""
    if _PHASE10_SEEDED['done']:
        return
    for commune, tier, idx in [('Ñuñoa', 'B', 65.0), ('Puente Alto', 'D', 30.0),
                               ('Providencia', 'A', 85.0)]:
        db.add(main.CommuneMarketData(country='CL', commune=commune, se_tier=tier,
                                      income_index=idx, price_m2_avg=idx, cpm_usd=6.0))
    for isco, usd, score in [(1, 3400.0, 88.0), (3, 1700.0, 48.0), (5, 900.0, 28.0), (7, 1100.0, 34.0)]:
        db.execute(main.text("""
            INSERT OR REPLACE INTO occupation_salary (country_iso, isco_group, median_monthly_usd, profession_score, year, source)
            VALUES ('CL', :ig, :usd, :sc, 2025, 'phase10-matrix-test-seed')
        """), {'ig': isco, 'usd': usd, 'sc': score})
    db.commit()
    _PHASE10_SEEDED['done'] = True


class TestControlledSensitivityMatrix(Base):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 10 — the full
    controlled matrix: age x company-size x >=5 occupations x >=5 Chilean
    communes (including Conchalí and Las Condes), each stable over 10
    recomputations, with the commune dimension tested BOTH with a resolved
    occupation (proving Phase 2's "no adjustment, no double-counting"
    finding -- the estimate must be commune-INVARIANT) and without one
    (proving the commune fallback itself still varies correctly). Every
    expected value below was derived from this exact real pipeline (not a
    parallel formula) and is pinned exactly as a regression guard -- see
    the standalone matrix-generation run for the full worked table in the
    final hardening report."""

    def setUp(self):
        super().setUp()
        _seed_phase10_matrix_data_once(self.db)

    def test_age_sweep_matches_the_documented_curve_exactly(self):
        expected = {19: 26103.0, 25: 34171.0, 30: 41290.0, 40: 47460.0, 50: 51257.0, 60: 49833.0}
        for age, exp in expected.items():
            u = self.mk_user(age=age, profession='17-2112', company_size='251-1000', county='Las Condes')
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1, f'age={age} unstable across 10x: {results}')
            self.assertAlmostEqual(results[0][0], exp, delta=1.0, msg=f'age={age}')

    def test_company_size_sweep_matches_the_documented_multipliers_exactly(self):
        expected = {'1-10': 30240.0, '11-50': 35700.0, '51-250': 42000.0,
                   '251-1000': 47460.0, '+1000': 51240.0}
        for size, exp in expected.items():
            u = self.mk_user(age=35, profession='17-2112', company_size=size, county='Las Condes')
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1, f'size={size} unstable across 10x: {results}')
            self.assertAlmostEqual(results[0][0], exp, delta=1.0, msg=f'size={size}')

    def test_occupation_sweep_five_materially_different_occupations(self):
        expected = {'empresario': (46104.0, 'A'), '17-2112': (47460.0, 'A'),
                   'tecnico': (23052.0, 'B'), 'vendedor': (12204.0, 'C'),
                   'mecanico': (14916.0, 'C')}
        for slug, (exp_income, exp_tier) in expected.items():
            u = self.mk_user(age=35, profession=slug, company_size='251-1000', county='Las Condes')
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1, f'profession={slug} unstable across 10x: {results}')
            income, tier, _ = results[0]
            self.assertAlmostEqual(income, exp_income, delta=1.0, msg=slug)
            self.assertEqual(tier, exp_tier, msg=slug)
        estimates = {v[0] for v in expected.values()}
        self.assertEqual(len(estimates), 5, 'all 5 occupations must be materially different')

    def test_commune_sweep_with_resolved_occupation_is_invariant_no_double_counting(self):
        """Direct proof of the Phase 2 finding: once occupation resolves a
        real estimate, commune must NOT additionally adjust it -- not even
        for Conchalí vs Las Condes, the task's own named example."""
        communes = ['Conchalí', 'Las Condes', 'Ñuñoa', 'Puente Alto', 'Providencia']
        estimates = set()
        for commune in communes:
            u = self.mk_user(age=35, profession='17-2112', company_size='251-1000', county=commune)
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1, f'commune={commune} unstable across 10x: {results}')
            estimates.add(results[0][0])
        self.assertEqual(len(estimates), 1,
                         f'commune must not adjust a resolved occupation estimate, got: {estimates}')

    def test_commune_sweep_without_occupation_is_the_only_place_commune_adjusts_income(self):
        expected = {'Conchalí': (11700.0, 'C'), 'Las Condes': (24700.0, 'B'),
                   'Ñuñoa': (16900.0, 'C'), 'Puente Alto': (7800.0, 'D'),
                   'Providencia': (22100.0, 'B')}
        for commune, (exp_income, exp_tier) in expected.items():
            u = self.mk_user(age=35, profession='', company_size='', county=commune)
            results = [self.recompute(u) for _ in range(10)]
            self.assertEqual(len(set(results)), 1, f'commune={commune} unstable across 10x: {results}')
            income, tier, _ = results[0]
            self.assertAlmostEqual(income, exp_income, delta=1.0, msg=commune)
            self.assertEqual(tier, exp_tier, msg=commune)
        # Not tuned to force a particular outcome: Conchalí (C) and Las
        # Condes (B) both land where their OWN seeded income_index puts
        # them, not forced apart or together by this test.


# ═══════════════════════════════════════════════════════════════════════
# FIX 10 — structural: no direct-to-tier shortcut anywhere
# ═══════════════════════════════════════════════════════════════════════

class TestProfessionTierNeverReachesSeTier(Base):
    """FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 4/9 (direct-shortcut
    search) — _PROFESSION_TIER maps occupation category codes directly to
    A/B/C/D letters (its own original comment said as much: "Profesiones
    que indican ingreso alto (elevan tier a A si la comuna lo permite)").
    That is exactly the "occupation -> A/B/C/D" pattern this hardening task
    forbids. It is reachable (computed into the local `profession_tier`
    variable, including via a "_static_floor" that can raise it) but never
    read afterward — only user.estimated_income_usd, written separately
    alongside it wherever real data exists, survives into classify(). This
    proves that behaviorally, not just by inspection: 'estudiante' is in
    _PROFESSION_TIER (-> 'C') but in NONE of the ISCO/SOC vocabularies
    (_OCC_TO_ISCO, _US_PROFESSION_SOC, occupation_salary_agent.
    PROFESSION_TO_ISCO), so every real-income-data path fails for it and
    _PROFESSION_TIER is the ONLY thing that would resolve anything — yet
    the user's tier still comes back UNRESOLVED, not 'C'."""

    def test_static_dict_maps_estudiante_to_a_real_letter(self):
        self.assertEqual(main._PROFESSION_TIER.get('estudiante'), 'C')

    def test_estudiante_is_absent_from_every_isco_soc_vocabulary(self):
        import occupation_salary_agent as OSA
        self.assertIsNone(main._OCC_TO_ISCO.get('estudiante'))
        self.assertIsNone(main._US_PROFESSION_SOC.get('estudiante'))
        self.assertIsNone(OSA.PROFESSION_TO_ISCO.get('estudiante'))

    def test_a_user_reachable_only_via_profession_tier_still_ends_up_unresolved(self):
        # country='XX' has no world_countries GDP row and no CommuneMarketData
        # rows in this test fixture (only 'CL' is seeded) — this isolates the
        # occupation path from BOTH the commune fallback AND the country-median
        # fallback (main.py: "if ... _country_median_income and ..."), both of
        # which are legitimate, occupation-independent income signals that
        # would otherwise also resolve a tier here and make this test a false
        # negative for what it actually needs to isolate: whether
        # _PROFESSION_TIER itself ever leaks into se_tier.
        u = self.mk_user(age=40, profession='estudiante', company_size='',
                         country='XX', county='Nowhereville')
        income, tier, source = self.recompute(u)
        self.assertEqual(tier, '', 'a static occupation->letter dict must never resolve a real tier')

    def test_no_se_tier_assignment_appears_near_the_profession_tier_variable(self):
        body = ast.get_source_segment(MAIN_SRC, next(
            n for n in ast.walk(MAIN_TREE)
            if isinstance(n, ast.FunctionDef) and n.name == '_assign_user_tier_inner'
        ))
        start = body.index('profession_tier = None')
        end = body.index('_classification = _socio.classify(')
        window = body[start:end]
        self.assertNotIn('user.se_tier', window,
                         'profession_tier (or _PROFESSION_TIER) must never be assigned to se_tier')


class TestNoDirectTierShortcut(unittest.TestCase):
    """Fix 10 — exhaustive search for every writer of user.se_tier.

    Found exactly THREE sites (originally four — see below):
      1. _assign_user_tier_inner — RESOLVED branch: se_tier = classify().tier
      2. _assign_user_tier_inner — UNRESOLVED branch: se_tier = '' (clears stale)
      3. _assign_user_tier (outer wrapper) — re-applies the SAME value #1/#2
         already computed, in case the inner transaction aborted; not a
         second decision, a re-assertion of the first.

    A FOURTH site — _voter_register_inner copying a REFERRER's se_tier
    directly onto a brand-new user via raw SQL whenever the new user's own
    tier could not be resolved — was found by this same audit, reported,
    and then REMOVED by FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 1
    (see the "CHANGE-003 remediation (audit finding Q, BLOCKER)" comment at
    its former call site, and TestReferralTierNoLongerInherited above,
    which regression-tests and mutation-tests the removal). It assigned a
    real, actionable A/B/C/D with NO economic signal about the new user at
    all — exactly the "income -> classify() -> tier" architecture violation
    this whole test class exists to catch, just reached via a referral
    relationship instead of age/occupation/company-size/commune. This test
    pins the site list exactly so a FOURTH, unreported site can never
    reappear silently.
    """

    _KNOWN_SE_TIER_WRITER_FUNCTIONS = {
        '_assign_user_tier_inner': 2,   # resolved + unresolved-clears branches
        '_assign_user_tier':       1,   # re-applies the inner function's own result
    }

    def test_every_se_tier_writer_is_a_known_named_site(self):
        offenders = []
        for node in ast.walk(MAIN_TREE):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(MAIN_SRC, node) or ''
            n = len(re.findall(r'\buser\.se_tier\s*=(?!=)', body))
            if n == 0:
                continue
            expected = self._KNOWN_SE_TIER_WRITER_FUNCTIONS.get(node.name)
            if expected is None:
                offenders.append(f'{node.name} writes user.se_tier ({n}x) but is not a known site')
            elif n != expected:
                offenders.append(f'{node.name} writes user.se_tier {n}x, expected exactly {expected}')
        self.assertEqual(offenders, [], '\n'.join(offenders))
        total_known = sum(self._KNOWN_SE_TIER_WRITER_FUNCTIONS.values())
        total_actual = len(re.findall(r'\buser\.se_tier\s*=(?!=)', MAIN_SRC))
        self.assertEqual(total_actual, total_known,
                         f'total user.se_tier writes ({total_actual}) does not match the '
                         f'fully-accounted-for known set ({total_known}) — a new, unreported '
                         f'site exists somewhere outside a FunctionDef (e.g. module level)')

    def test_no_age_variable_assigned_directly_into_se_tier(self):
        for node in ast.walk(MAIN_TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '_assign_user_tier_inner':
                body = ast.get_source_segment(MAIN_SRC, node)
                self.assertNotRegex(body, r'se_tier\s*=\s*[\'"]?[ABCD][\'"]?\s*if\s+\w*age',
                                    'a conditional age->tier assignment was found')
                break

    def test_professional_profile_docstring_still_says_it_does_not_promote_tier(self):
        src = None
        for node in ast.walk(MAIN_TREE):
            if isinstance(node, ast.FunctionDef) and node.name == '_professional_profile':
                src = ast.get_source_segment(MAIN_SRC, node)
                break
        self.assertIsNotNone(src)
        self.assertIn('NO promueve el tier', src)


if __name__ == '__main__':
    unittest.main()
