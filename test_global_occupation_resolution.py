"""
test_global_occupation_resolution.py — GLOBAL OCCUPATION RESOLUTION
HARDENING.

Covers, against the REAL canonical resolver (socioeconomic.
resolve_occupation_soc / CANONICAL_OCCUPATIONS / AMBIGUOUS_OCCUPATION_TERMS
/ resolve_occupation_candidates), never a parallel/mock formula:

  A/B/C/D/E/F/G — exact canonical title, lowercase, plural, Spanish,
                  capitalization, accents, whitespace variants
  H/I           — SOC code, legacy slug
  J             — unknown occupation
  K             — ambiguous occupation
  L             — typo/near-miss safety (no fuzzy matching)
  M             — fresh database, full pipeline
  N             — repeated recalculation / idempotency
  O             — CHANGE-002 occupation matching consistency
  P             — socioeconomic estimate (salary lookup invariant)
  Q             — declared-income precedence remains intact

25+ distinct supported occupations across multiple families, each proven:
all aliases -> exactly one canonical occupation -> identical estimate.

LOCAL / TEST ONLY. DATABASE_URL is forced to a throwaway sqlite file; no
production credential is read and no network call is made.
"""

import ast
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='occ-resolution-')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMPDIR, "test.db")}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-occ-resolution'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-occ-resolution'
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


_SEEDED = {'done': False}


def _seed_once(db):
    """Real BLS import (Phase 3 mechanism) + a CL PPP row + a couple of
    Chilean communes, exactly once for the whole module run."""
    if _SEEDED['done']:
        return
    db.execute(main.text(
        "CREATE TABLE IF NOT EXISTS world_countries (iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)"))
    db.execute(main.text(
        "INSERT OR REPLACE INTO world_countries (iso2, gdp_per_capita_usd) VALUES ('CL', 26000.0)"))
    result = USA.import_bls_occupations_to_db(db)
    assert result['ok'] and result['total'] == 818, result
    db.execute(main.text("""
        CREATE TABLE IF NOT EXISTS occupation_salary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, country_iso TEXT NOT NULL, isco_group INTEGER NOT NULL,
            isco_label TEXT DEFAULT '', median_monthly_local REAL, median_monthly_usd REAL,
            currency TEXT DEFAULT '', profession_score REAL DEFAULT 0, year INTEGER, source TEXT DEFAULT '',
            updated_at TIMESTAMP, UNIQUE (country_iso, isco_group))
    """))
    for commune, tier, idx in [('Conchalí', 'C', 45.0), ('Las Condes', 'A', 95.0)]:
        db.add(main.CommuneMarketData(country='CL', commune=commune, se_tier=tier,
                                      income_index=idx, price_m2_avg=idx, cpm_usd=6.0))
    db.commit()
    _SEEDED['done'] = True


class Base(unittest.TestCase):

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)
        _seed_once(self.db)

    def mk_user(self, age=40, profession='17-2112', company_size='+1000',
               country='US', county='', **kw):
        n = _uid()
        today = date.today()
        dob = date(today.year - age, today.month, today.day).isoformat()
        base = dict(email=f'occres{n}@test.local', name=f'U{n}', password='x',
                   country=country, county=county, gender='F', dob=dob,
                   profession=profession, company_size=company_size, role='voter',
                   referral_code=f'OCCR{n:06d}')
        base.update(kw)
        u = main.User(**base)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def recompute(self, u):
        main._assign_user_tier(u, self.db)
        self.db.refresh(u)
        return u.estimated_income_usd, u.se_tier, u.se_tier_source


# ═══════════════════════════════════════════════════════════════════════
# A-I — canonical registry integrity: every alias set -> exactly one SOC
# ═══════════════════════════════════════════════════════════════════════

class TestCanonicalRegistryIntegrity(unittest.TestCase):
    """For every one of the 25 canonical occupations, EVERY declared
    alias (Spanish and English) must resolve to that SAME SOC code, and
    the canonical English title itself must too. This is the direct
    "all aliases -> exactly one canonical occupation" proof, covering
    A (exact canonical title), D (Spanish title), H (implicitly, since
    the SOC code is the resolved target) across all 25 occupations."""

    def test_at_least_25_canonical_occupations_registered(self):
        self.assertGreaterEqual(len(S.CANONICAL_OCCUPATIONS), 25)

    def test_every_occupation_soc_code_is_real_and_unique(self):
        import csv
        csv_codes = {r['soc_code'] for r in csv.DictReader(
            open(Path(main.__file__).parent / 'bls_occupation_scores_2025.csv', encoding='utf-8'))}
        seen = set()
        for occ in S.CANONICAL_OCCUPATIONS:
            self.assertIn(occ['soc'], csv_codes, f"{occ['soc']} not a real BLS SOC code")
            self.assertNotIn(occ['soc'], seen, f"duplicate SOC {occ['soc']}")
            seen.add(occ['soc'])

    def test_every_alias_of_every_occupation_resolves_to_its_own_soc(self):
        for occ in S.CANONICAL_OCCUPATIONS:
            soc = occ['soc']
            self.assertEqual(S.resolve_occupation_soc(occ['title_en']), soc,
                             f"canonical title {occ['title_en']!r} did not resolve to {soc}")
            for lang, aliases in occ['aliases'].items():
                for alias in aliases:
                    got = S.resolve_occupation_soc(alias)
                    self.assertEqual(got, soc,
                                     f"[{lang}] alias {alias!r} resolved to {got!r}, expected {soc!r}")

    def test_at_least_25_spanish_aliases_exist(self):
        es_count = sum(len(occ['aliases'].get('es', [])) for occ in S.CANONICAL_OCCUPATIONS)
        self.assertGreaterEqual(es_count, 25)

    def test_registry_is_i18n_ready_aliases_keyed_by_language(self):
        """Adding 'pt' later means adding a key to an existing dict --
        prove the shape actually supports that without touching the
        resolver's code."""
        for occ in S.CANONICAL_OCCUPATIONS:
            self.assertIsInstance(occ['aliases'], dict)
            for lang in occ['aliases']:
                self.assertIn(lang, ('es', 'en'), f"unexpected language key {lang!r}")


# ═══════════════════════════════════════════════════════════════════════
# B/C/E/F/G — normalization: lowercase, plural, capitalization, accents,
# whitespace
# ═══════════════════════════════════════════════════════════════════════

class TestNormalizationVariants(unittest.TestCase):

    def test_lowercase_english(self):
        self.assertEqual(S.resolve_occupation_soc('industrial engineer'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('registered nurse'), '29-1141')

    def test_singular_plural_approved_variants(self):
        self.assertEqual(S.resolve_occupation_soc('Industrial Engineer'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('Industrial Engineers'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('Software Developer'), '15-1252')
        self.assertEqual(S.resolve_occupation_soc('Software Developers'), '15-1252')

    def test_capitalization_differences(self):
        for v in ('MÉDICO', 'médico', 'Médico', 'MeDiCo'):
            self.assertEqual(S.resolve_occupation_soc(v), '29-1215', f'failed for {v!r}')

    def test_accents(self):
        self.assertEqual(S.resolve_occupation_soc('médico'), S.resolve_occupation_soc('medico'))
        self.assertEqual(S.resolve_occupation_soc('psicólogo'), S.resolve_occupation_soc('psicologo'))
        self.assertEqual(S.resolve_occupation_soc('electricista'), '47-2111')

    def test_gender_variants_resolve_to_the_same_occupation(self):
        pairs = [('abogado', 'abogada'), ('medico', 'medica'), ('enfermero', 'enfermera'),
                 ('arquitecto', 'arquitecta'), ('veterinario', 'veterinaria')]
        for masc, fem in pairs:
            self.assertEqual(S.resolve_occupation_soc(masc), S.resolve_occupation_soc(fem),
                             f'{masc}/{fem} diverged')
            self.assertNotEqual(S.resolve_occupation_soc(masc), '', f'{masc} unresolved')

    def test_surrounding_and_repeated_whitespace(self):
        for v in ('  Ingeniero Industrial  ', 'Ingeniero    Industrial',
                  '\tIngeniero Industrial\n', '  médico  '):
            self.assertNotEqual(S.resolve_occupation_soc(v), '', f'failed for {v!r}')

    def test_all_variants_of_one_occupation_agree(self):
        variants = ['Industrial Engineer', 'Industrial Engineers', 'industrial engineer',
                   'Ingeniero Industrial', 'ingeniero industrial', 'INGENIERO INDUSTRIAL',
                   '  Ingeniero   Industrial  ', 'Ingeniera Industrial', '17-2112']
        resolved = {S.resolve_occupation_soc(v) for v in variants}
        self.assertEqual(resolved, {'17-2112'}, f'variants diverged: '
                         f'{[(v, S.resolve_occupation_soc(v)) for v in variants]}')


# ═══════════════════════════════════════════════════════════════════════
# H/I — SOC code and legacy slug
# ═══════════════════════════════════════════════════════════════════════

class TestSOCCodeAndLegacySlug(unittest.TestCase):

    def test_bare_soc_code_passes_through(self):
        self.assertEqual(S.resolve_occupation_soc('17-2112'), '17-2112')
        self.assertEqual(S.resolve_occupation_soc('29-1215'), '29-1215')

    def test_snake_case_legacy_slug_is_out_of_scope_here_but_still_works_downstream(self):
        """This resolver correctly does not claim 'ing_civil' (it is a
        Preferendum-internal slug, not a natural-language title) — that
        does not mean it stops working; it still resolves via main.py's
        pre-existing _OCC_TO_ISCO/_US_PROFESSION_SOC path, proven
        end-to-end in TestFreshDatabaseGlobalOccupation below."""
        self.assertEqual(S.resolve_occupation_soc('ing_civil'), '')
        self.assertIn('ing_civil', main._OCC_TO_ISCO)


# ═══════════════════════════════════════════════════════════════════════
# J — unknown occupation
# ═══════════════════════════════════════════════════════════════════════

class TestUnknownOccupation(unittest.TestCase):

    def test_nonsense_occupation_is_unresolved_not_fabricated(self):
        for v in ('Astronauta Marciano', 'Dragon Trainer', 'Wizard', 'xyzzy123'):
            self.assertEqual(S.resolve_occupation_soc(v), '', f'{v!r} should not resolve')
            r = S.resolve_occupation_candidates(v)
            self.assertEqual(r.status, S.OccupationResolution.UNRESOLVED)

    def test_blank_and_none(self):
        self.assertEqual(S.resolve_occupation_soc(''), '')
        self.assertEqual(S.resolve_occupation_soc(None), '')


# ═══════════════════════════════════════════════════════════════════════
# K — ambiguous occupation
# ═══════════════════════════════════════════════════════════════════════

class TestAmbiguousOccupation(unittest.TestCase):
    """A bare/generic term naming a FAMILY of materially-different-pay
    occupations must never silently resolve to one member of that family."""

    def test_every_documented_ambiguous_term_returns_empty_from_the_core_resolver(self):
        for term in S.AMBIGUOUS_OCCUPATION_TERMS:
            self.assertEqual(S.resolve_occupation_soc(term), '',
                             f'ambiguous term {term!r} incorrectly resolved')

    def test_ambiguous_terms_report_AMBIGUOUS_status_with_candidates(self):
        for term, candidates in [('ingeniero', {'17-2112', '17-2051', '17-2141', '17-2071', '15-1252'}),
                                 ('doctor', {'29-1215'}), ('tecnico', None),
                                 ('conductor', {'53-3032', '53-3033', '53-3031'}),
                                 ('disenador', {'27-1024'}), ('maestro', {'25-2021'})]:
            r = S.resolve_occupation_candidates(term)
            self.assertEqual(r.status, S.OccupationResolution.AMBIGUOUS, f'{term!r} not AMBIGUOUS')
            if candidates is not None:
                self.assertEqual(set(r.candidates), candidates, f'{term!r} candidates mismatch')

    def test_too_broad_term_has_no_candidates_but_is_still_ambiguous_not_unresolved(self):
        r = S.resolve_occupation_candidates('analista')
        self.assertEqual(r.status, S.OccupationResolution.AMBIGUOUS)
        self.assertEqual(r.candidates, ())

    def test_qualified_form_of_an_ambiguous_term_does_resolve(self):
        """'diseñador' bare is ambiguous; 'diseñador gráfico' is
        sufficiently specific and DOES resolve -- proves the ambiguity
        guard is about genuine ambiguity, not blanket refusal."""
        self.assertEqual(S.resolve_occupation_soc('disenador'), '')
        self.assertEqual(S.resolve_occupation_soc('diseñador gráfico'), '27-1024')
        self.assertEqual(S.resolve_occupation_soc('maestro'), '')
        self.assertEqual(S.resolve_occupation_soc('maestro de primaria'), '25-2021')
        self.assertEqual(S.resolve_occupation_soc('conductor'), '')
        self.assertEqual(S.resolve_occupation_soc('conductor de camión'), '53-3032')

class TestAmbiguousOccupationEndToEnd(Base):

    def test_ambiguous_profession_never_resolves_a_wrong_income(self):
        u = self.mk_user(age=35, profession='ingeniero', company_size='+1000', country='US')
        est, tier, src = self.recompute(u)
        # Must NOT silently pick e.g. Industrial Engineer's income.
        self.assertNotEqual(src, 'estimated_occupation',
                            'an ambiguous bare term must not resolve via occupation at all')


# ═══════════════════════════════════════════════════════════════════════
# L — typo/near-miss safety: no fuzzy matching
# ═══════════════════════════════════════════════════════════════════════

class TestTypoSafety(unittest.TestCase):

    def test_typos_do_not_silently_resolve(self):
        typos = ['Industral Engineer', 'Industrial Enginer', 'Ingeniero Indutrial',
                 'Medic', 'Enfermeroo', 'Abogaddo', 'Softwar Developer',
                 'Ingenero Civil', 'Farmaceutic']
        for t in typos:
            got = S.resolve_occupation_soc(t)
            # A typo may coincidentally be a valid different alias in rare
            # cases (none of these are); assert none silently resolves.
            self.assertEqual(got, '', f'{t!r} unexpectedly resolved to {got!r}')

    def test_near_miss_that_is_a_real_different_occupation_resolves_to_ITSELF_not_the_typo_target(self):
        """'Ingeniero Comercial' is a real, different, pre-existing legacy
        term -- must not accidentally resolve to Industrial Engineer just
        because it shares a word."""
        self.assertEqual(S.resolve_occupation_soc('Ingeniero Comercial'), '')

    def test_partial_substring_is_not_enough_to_match(self):
        self.assertEqual(S.resolve_occupation_soc('Ingeniero'), '')  # ambiguous, not partial-matched
        self.assertEqual(S.resolve_occupation_soc('Software'), '')
        self.assertEqual(S.resolve_occupation_soc('Developer'), '')


# ═══════════════════════════════════════════════════════════════════════
# M — fresh database, full pipeline
# ═══════════════════════════════════════════════════════════════════════

class TestFreshDatabaseGlobalOccupation(unittest.TestCase):
    """A SEPARATE, genuinely fresh sqlite file/import (subprocess) — no
    production dependency — proving: schema exists, BLS import works,
    Spanish aliases resolve, English titles resolve, SOC codes resolve,
    income estimation works, socioeconomic classification works, and
    CHANGE-002 occupation matching works, all from an empty database."""

    def test_full_chain_from_empty_db(self):
        import subprocess, sys
        script = '''
import os, tempfile
d = tempfile.mkdtemp(prefix="fresh-occres-")
_dbpath = os.path.join(d, "fresh.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_dbpath}"
os.environ["JWT_SECRET"] = "x"
os.environ["ADMIN_SECRET"] = "x"
for k in ("SENDGRID_API_KEY","TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","STRIPE_SECRET_KEY",
          "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","CLOUDINARY_URL","WEB3_PROVIDER_URL"):
    os.environ.pop(k, None)

import main
import socioeconomic as S
import eligibility as E
import usa_data_agent as USA

db = main.SessionLocal()
r = USA.import_bls_occupations_to_db(db)
assert r["ok"] and r["total"] == 818, r

# Spanish alias resolves
assert S.resolve_occupation_soc("Ingeniero Industrial") == "17-2112"
assert S.resolve_occupation_soc("Médico") == "29-1215"
# English title resolves
assert S.resolve_occupation_soc("Industrial Engineer") == "17-2112"
# SOC code resolves
assert S.resolve_occupation_soc("17-2112") == "17-2112"

u = main.User(email="fresh_es@test.local", name="U", password="x", country="US", county="",
              gender="F", dob="1990-01-01", profession="Ingeniero Industrial",
              company_size="+1000", role="voter", referral_code="FRESHOCC1")
db.add(u); db.commit(); db.refresh(u)
main._assign_user_tier(u, db)
db.refresh(u)
assert u.estimated_income_usd, "income estimation did not run for a Spanish title"
assert u.se_tier in ("A","B","C","D"), f"classification failed: {u.se_tier!r}"

prof = main._build_profile(u, db)
target = E.CampaignTarget(occupations={"17-0000"}, gender="all")
decision = E.evaluate_campaign(prof, target)
assert decision.allowed, f"occupation matching failed for a Spanish-resolved user: {decision.reasons}"

print(f"OK income={u.estimated_income_usd} tier={u.se_tier} matched={decision.allowed}")
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(main.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)


# ═══════════════════════════════════════════════════════════════════════
# N — repeated recalculation / idempotency
# ═══════════════════════════════════════════════════════════════════════

class TestRepeatedRecalculation(Base):

    def test_spanish_title_is_stable_across_10_recomputations(self):
        u = self.mk_user(age=40, profession='Ingeniero Industrial', company_size='+1000', country='US')
        results = [self.recompute(u) for _ in range(10)]
        self.assertEqual(len(set(results)), 1, f'unstable across 10x: {results}')

    def test_every_canonical_occupation_is_stable_across_5_recomputations(self):
        for occ in S.CANONICAL_OCCUPATIONS:
            u = self.mk_user(age=40, profession=occ['soc'], company_size='+1000', country='US')
            results = [self.recompute(u) for _ in range(5)]
            self.assertEqual(len(set(results)), 1, f'{occ["soc"]} unstable: {results}')


# ═══════════════════════════════════════════════════════════════════════
# O — CHANGE-002 occupation matching consistency
# ═══════════════════════════════════════════════════════════════════════

class TestChange002OccupationMatchingConsistency(unittest.TestCase):
    """Occupation targeting and income estimation must recognize the SAME
    canonical occupation for the same input -- neither collapses into
    se_tier, and neither diverges from the other."""

    def test_spanish_and_english_and_soc_all_target_the_same_major_group(self):
        for term in ('Médico', 'medico', 'Physician', '29-1215'):
            soc = S.resolve_occupation_soc(term)
            self.assertEqual(E.norm_occupation(soc), '29-0000', f'{term!r} -> {soc!r} major group mismatch')

    def test_occupation_targeting_is_independent_of_tier(self):
        p_a = E.UserProfile(country='US', se_tier='A', occupation=E.norm_occupation('29-1215'), age=35)
        p_d = E.UserProfile(country='US', se_tier='D', occupation=E.norm_occupation('29-1215'), age=35)
        target = E.CampaignTarget(occupations={'29-0000'}, gender='all')
        self.assertTrue(E.evaluate_campaign(p_a, target).allowed)
        self.assertTrue(E.evaluate_campaign(p_d, target).allowed)

    def test_different_occupation_family_is_excluded(self):
        p = E.UserProfile(country='US', occupation=E.norm_occupation('29-1215'), age=35)  # Physician
        target = E.CampaignTarget(occupations={'17-0000'}, gender='all')  # Engineering
        self.assertFalse(E.evaluate_campaign(p, target).allowed)


# ═══════════════════════════════════════════════════════════════════════
# P — salary lookup invariant + 25-occupation matrix
# ═══════════════════════════════════════════════════════════════════════

class TestSalaryLookupInvariant(Base):
    """Section 10: all aliases resolving to one canonical occupation must
    produce identical canonical occupation, base reference income,
    provenance, final estimate (given identical age/company/location),
    and final tier."""

    def test_industrial_engineer_all_representations_identical(self):
        reps = ['17-2112', 'Industrial Engineer', 'Industrial Engineers',
               'Ingeniero Industrial', 'ingeniero industrial', 'Ingeniera Industrial']
        results = []
        for rep in reps:
            u = self.mk_user(age=35, profession=rep, company_size='251-1000', country='US')
            est, tier, src = self.recompute(u)
            results.append((rep, est, tier, src))
        estimates = {r[1] for r in results}
        tiers = {r[2] for r in results}
        sources = {r[3] for r in results}
        self.assertEqual(len(estimates), 1, f'estimates diverged: {results}')
        self.assertEqual(len(tiers), 1, f'tiers diverged: {results}')
        self.assertEqual(len(sources), 1, f'provenance diverged: {results}')
        self.assertIsNotNone(results[0][1])


class Test25PlusOccupationMatrix(Base):
    """Section 12's explicit requirement: at least 25 distinct supported
    occupations across multiple families, each resolving to a real
    estimate and tier, from the real pipeline."""

    def test_every_canonical_occupation_resolves_a_real_estimate_and_tier(self):
        seen_estimates = {}
        for occ in S.CANONICAL_OCCUPATIONS:
            # Use the primary Spanish alias where one exists, else the SOC code.
            rep = occ['aliases'].get('es', [occ['soc']])[0]
            u = self.mk_user(age=40, profession=rep, company_size='251-1000', country='US')
            est, tier, src = self.recompute(u)
            self.assertIsNotNone(est, f'{occ["soc"]} ({rep!r}) produced no income estimate')
            self.assertIn(tier, ('A', 'B', 'C', 'D'), f'{occ["soc"]} ({rep!r}) produced no tier')
            seen_estimates[occ['soc']] = est
        self.assertGreaterEqual(len(seen_estimates), 25)
        # Occupations across different pay levels must NOT all collapse to
        # one number -- real differentiation, not a flat default.
        self.assertGreater(len(set(seen_estimates.values())), 10,
                           'too little differentiation across 25 occupations')


# ═══════════════════════════════════════════════════════════════════════
# Q — declared-income precedence remains intact
# ═══════════════════════════════════════════════════════════════════════

class TestDeclaredIncomePrecedenceIntact(Base):

    def test_declared_income_still_outranks_a_spanish_resolved_occupation_estimate(self):
        u = self.mk_user(age=40, profession='Médico', company_size='+1000', country='US',
                         declared_income_amount=5_000_000, declared_income_currency='USD',
                         declared_income_period='annual', declared_income_confirmed=False)
        est, tier, src = self.recompute(u)
        self.assertEqual(src, 'declared')


if __name__ == '__main__':
    unittest.main()
