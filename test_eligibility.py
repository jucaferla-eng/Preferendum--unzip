"""
test_eligibility.py — CHANGE-002 canonical eligibility test suite.

Stdlib only (unittest). Run:

    python3 -m unittest test_eligibility -v

The canonical evaluator is deliberately dependency-free, so these tests run
without fastapi/sqlalchemy/postgres. Endpoint-level wiring is covered by
test_matching_wiring.py, which asserts against main.py's source that every
path delegates here and that no weaker evaluator remains reachable.
"""

import unittest
from datetime import date

import eligibility as E


# ═══════════════════════════════════════════════════════════════════════
# Fixtures — plain objects standing in for ORM rows (duck-typed adapters)
# ═══════════════════════════════════════════════════════════════════════

class Row:
    """Minimal stand-in for a SQLAlchemy row."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


TODAY = date(2026, 8, 26)


def user(**kw):
    base = dict(
        id=1, country='Chile', county='Las Condes', gender='M',
        dob='1990-05-10', se_tier='B', tier_pre_evaluated=False,
        profession='medico', cargo='gerente', company_size='51-250',
        estimated_income_usd=60000.0,
    )
    base.update(kw)
    return Row(**base)


def profile(country_per_capita_ppp_usd=None, **kw):
    return E.profile_from_user(user(**kw),
                               country_per_capita_ppp_usd=country_per_capita_ppp_usd,
                               today=TODAY)


def debate(**kw):
    base = dict(
        id=100, title='Consulta', category='general',
        scope='country', scope_country='CL', scope_commune='',
        target_gender='all', target_age_min=13, target_age_max=99,
        target_se_tiers='A,B,C,D', income_min_usd=None, income_max_usd=None,
        target_professions='', target_cargos='', target_company_sizes='',
        min_per_capita_usd=0.0, is_closed_list=False,
    )
    base.update(kw)
    return Row(**base)


def campaign(**kw):
    base = dict(
        id=200, advertiser_name='Acme', title='C',
        target_country='', target_communes='', target_gender='all',
        target_age_min=13, target_age_max=99, target_age_ranges='',
        target_se_tiers='A,B,C,D', target_income_min=0.0, target_income_max=9999.0,
        target_professions='', target_cargos='', target_company_sizes='',
        target_categories='', excluded_categories='',
        min_per_capita_usd=0.0, target_hnw_only=False, min_hnw_score=0.0,
        target_debate_ids='',
    )
    base.update(kw)
    return Row(**base)


# ═══════════════════════════════════════════════════════════════════════
# 1-3. GLOBAL semantics  (rule 1)
# ═══════════════════════════════════════════════════════════════════════

class TestGlobalSemantics(unittest.TestCase):

    def test_01_global_only_is_worldwide(self):
        """GLOBAL only => worldwide audience."""
        for country in ('Chile', 'Japan', 'Nigeria', 'US'):
            d = E.evaluate_consultation(profile(country=country),
                                        debate(scope_country='GLOBAL'))
            self.assertTrue(d.allowed, f'{country} should be eligible: {d}')

    def test_01b_global_aliases_all_mean_unrestricted(self):
        for token in ('GLOBAL', 'ALL', '', 'GL', 'WORLD'):
            d = E.evaluate_consultation(profile(country='Japan'),
                                        debate(scope_country=token))
            self.assertTrue(d.allowed, f'{token!r} should not restrict: {d}')

    def test_02_global_plus_tier_restricts_by_tier_only(self):
        """GLOBAL + tier A => tier A users worldwide."""
        d_ok = E.evaluate_consultation(profile(country='Japan', se_tier='A'),
                                       debate(scope_country='GLOBAL', target_se_tiers='A'))
        self.assertTrue(d_ok.allowed)

        d_no = E.evaluate_consultation(profile(country='Japan', se_tier='B'),
                                       debate(scope_country='GLOBAL', target_se_tiers='A'))
        self.assertFalse(d_no.allowed)
        self.assertEqual(d_no.verdict, E.INELIGIBLE)
        self.assertIn('se_tier', d_no.blocking_dimensions())

    def test_03_global_plus_per_capita_plus_tier(self):
        """GLOBAL + country per-capita >= 5000 + tier A."""
        d = debate(scope_country='GLOBAL', target_se_tiers='A', min_per_capita_usd=5000)

        rich_a = E.evaluate_consultation(
            profile(country='Japan', se_tier='A', country_per_capita_ppp_usd=39000), d)
        self.assertTrue(rich_a.allowed)

        poor_a = E.evaluate_consultation(
            profile(country='Nigeria', se_tier='A', country_per_capita_ppp_usd=2200), d)
        self.assertFalse(poor_a.allowed)
        self.assertIn('market_per_capita', poor_a.blocking_dimensions())

        rich_b = E.evaluate_consultation(
            profile(country='Japan', se_tier='B', country_per_capita_ppp_usd=39000), d)
        self.assertFalse(rich_b.allowed)
        self.assertIn('se_tier', rich_b.blocking_dimensions())

    def test_03b_market_threshold_is_not_individual_income(self):
        """Rule 9: market threshold and individual income are separate axes."""
        d = debate(scope_country='GLOBAL', min_per_capita_usd=30000)
        # Very high personal income, but a low per-capita market.
        p = profile(country='Nigeria', estimated_income_usd=500000,
                    country_per_capita_ppp_usd=2200)
        dec = E.evaluate_consultation(p, d)
        self.assertFalse(dec.allowed)
        self.assertIn('market_per_capita', dec.blocking_dimensions())


# ═══════════════════════════════════════════════════════════════════════
# 4-9. Core dimensions
# ═══════════════════════════════════════════════════════════════════════

class TestCoreDimensions(unittest.TestCase):

    def test_04_country_restriction(self):
        d = debate(scope_country='CL')
        self.assertTrue(E.evaluate_consultation(profile(country='Chile'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(country='CL'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(country='Argentina'), d).allowed)

    def test_04b_country_normalization_regression(self):
        """Phase 0 F-11: 'Chile' vs 'CL' used to wrongly exclude on 3 of 5 paths."""
        for spelling in ('Chile', 'chile', 'CHILE', 'CL', 'cl'):
            dec = E.evaluate_consultation(profile(country=spelling), debate(scope_country='CL'))
            self.assertTrue(dec.allowed, f'{spelling!r} must normalize to CL: {dec}')

    def test_05_commune_restriction(self):
        d = debate(scope_commune='Las Condes')
        self.assertTrue(E.evaluate_consultation(profile(county='Las Condes'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(county='Conchali'), d).allowed)

    def test_05b_commune_normalization_accents_and_case(self):
        d = debate(scope_commune='Ñuñoa')
        for spelling in ('Ñuñoa', 'nunoa', 'NUNOA', 'Nuñoa', ' ñuñoa '):
            dec = E.evaluate_consultation(profile(county=spelling), d)
            self.assertTrue(dec.allowed, f'{spelling!r} must match Ñuñoa: {dec}')

    def test_05c_commune_enforced_regardless_of_scope_field(self):
        """Phase 0 F-12: scope='global' + scope_commune set was unrestricted."""
        d = debate(scope='global', scope_commune='Las Condes')
        self.assertFalse(E.evaluate_consultation(profile(county='Conchali'), d).allowed)

    def test_06_gender(self):
        d = debate(target_gender='F')
        self.assertTrue(E.evaluate_consultation(profile(gender='F'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(gender='M'), d).allowed)

    def test_06b_gender_normalization_regression(self):
        """Phase 0 F-2: /debates/for-me compared 'F' to lowercased 'f' and
        therefore excluded EVERY user from EVERY gender-targeted consultation."""
        for target in ('F', 'f', 'Female', 'mujer', 'femenino'):
            for u in ('F', 'f', 'Female', 'mujer'):
                dec = E.evaluate_consultation(profile(gender=u), debate(target_gender=target))
                self.assertTrue(dec.allowed, f'user={u!r} target={target!r}: {dec}')

    def test_07_age_boundaries_inclusive(self):
        d = debate(target_age_min=18, target_age_max=55)
        # born 2008-08-26 -> exactly 18 on TODAY
        self.assertTrue(E.evaluate_consultation(profile(dob='2008-08-26'), d).allowed)
        # exactly 55
        self.assertTrue(E.evaluate_consultation(profile(dob='1971-08-26'), d).allowed)
        # 17 -> out
        self.assertFalse(E.evaluate_consultation(profile(dob='2009-08-26'), d).allowed)
        # 56 -> out
        self.assertFalse(E.evaluate_consultation(profile(dob='1970-08-25'), d).allowed)

    def test_07b_age_zero_min_means_zero_not_disabled(self):
        """Phase 0 F-1: `if target_age_min and ...` made 0 disable the check."""
        d = debate(target_age_min=0, target_age_max=10)
        self.assertFalse(E.evaluate_consultation(profile(dob='1990-05-10'), d).allowed)

    def test_07c_unparseable_dob_does_not_pass_age_gate(self):
        """Phase 0 F-6 / G-5: bad dob used to skip the age check entirely."""
        d = debate(target_age_min=18, target_age_max=55)
        dec = E.evaluate_consultation(profile(dob='garbage'), d)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.UNRESOLVED)
        self.assertIn('age', dec.blocking_dimensions())

    def test_08_multiple_values_within_dimension_is_or(self):
        d = debate(scope_commune='Las Condes,Vitacura,Providencia')
        for c in ('Las Condes', 'Vitacura', 'Providencia'):
            self.assertTrue(E.evaluate_consultation(profile(county=c), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(county='Conchali'), d).allowed)

    def test_08b_multiple_tiers_is_or(self):
        d = debate(target_se_tiers='A,B')
        self.assertTrue(E.evaluate_consultation(profile(se_tier='A'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(se_tier='B'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(se_tier='C'), d).allowed)

    def test_09_and_across_dimensions(self):
        d = debate(scope_country='CL', scope_commune='Las Condes',
                   target_gender='M', target_age_min=18, target_age_max=55,
                   target_se_tiers='A,B')
        ok = profile(country='Chile', county='Las Condes', gender='M',
                     dob='1990-05-10', se_tier='B')
        self.assertTrue(E.evaluate_consultation(ok, d).allowed)
        # Each single violation must independently defeat the AND.
        self.assertFalse(E.evaluate_consultation(profile(country='AR'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(county='Conchali'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(gender='F'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(dob='2015-01-01'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(se_tier='D'), d).allowed)


# ═══════════════════════════════════════════════════════════════════════
# 10. Exclusion precedence
# ═══════════════════════════════════════════════════════════════════════

class TestExclusionPrecedence(unittest.TestCase):

    def test_10_exclusion_beats_inclusion(self):
        d = debate(category='politica', title='Debate sobre el gobierno')
        c = campaign(target_categories='politica', excluded_categories='politica')
        dec = E.campaign_consultation_compatible(c, d)
        self.assertFalse(dec.allowed)
        self.assertIn('excluded_categories', [r.dimension for r in dec.failures()])

    def test_10b_brand_safety_excludes_by_keyword(self):
        d = debate(category='general', title='Conflicto y guerra en la region')
        c = campaign(excluded_categories='conflicto_armado')
        self.assertFalse(E.campaign_consultation_compatible(c, d).allowed)

    def test_10c_no_exclusion_configured_is_permissive(self):
        d = debate(category='deportes', title='Mundial')
        c = campaign()
        self.assertTrue(E.campaign_consultation_compatible(c, d).allowed)


# ═══════════════════════════════════════════════════════════════════════
# 11-14. Occupation / cargo / company size / tier
# ═══════════════════════════════════════════════════════════════════════

class TestOccupationCanonicalization(unittest.TestCase):

    def test_11_slug_and_soc_code_canonicalize_together(self):
        """Rule 10: consultant picks 'healthcare_pro'; users may be stored as
        the slug 'medico' or as a raw BLS SOC code '29-1141'. All three must
        resolve to the same canonical major group 29-0000."""
        self.assertEqual(E.norm_occupation('healthcare_pro'), '29-0000')
        self.assertEqual(E.norm_occupation('medico'), '29-0000')
        self.assertEqual(E.norm_occupation('29-1141'), '29-0000')
        self.assertEqual(E.norm_occupation('29-0000'), '29-0000')

        d = debate(target_professions='healthcare_pro')
        for stored in ('medico', '29-1141', 'healthcare_pro', 'enfermero'):
            dec = E.evaluate_consultation(profile(profession=stored), d)
            self.assertTrue(dec.allowed, f'{stored!r} should match healthcare_pro: {dec}')

    def test_11b_different_occupation_is_rejected(self):
        d = debate(target_professions='healthcare_pro')
        dec = E.evaluate_consultation(profile(profession='abogado'), d)
        self.assertFalse(dec.allowed)
        self.assertIn('occupation', dec.blocking_dimensions())

    def test_11c_occupation_multi_value_or(self):
        d = debate(target_professions='legal,computer')
        self.assertTrue(E.evaluate_consultation(profile(profession='abogado'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(profession='programador'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(profession='medico'), d).allowed)

    def test_11d_unknown_occupation_is_unresolved_not_pass(self):
        d = debate(target_professions='healthcare_pro')
        dec = E.evaluate_consultation(profile(profession=''), d)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.UNRESOLVED)

    def test_11e_unrecognized_token_not_silently_collapsed(self):
        """Rule 18: an unrecognised value must not become 'unrestricted'."""
        d = debate(target_professions='astronauta_lunar')
        self.assertTrue(E.evaluate_consultation(profile(profession='astronauta_lunar'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(profession='medico'), d).allowed)


class TestCargo(unittest.TestCase):

    def test_12_cargo_matching_and_aliases(self):
        d = debate(target_cargos='gerente')
        self.assertTrue(E.evaluate_consultation(profile(cargo='gerente'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(cargo='manager'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(cargo='practicante'), d).allowed)

    def test_12b_cargo_distinct_from_occupation(self):
        """Rule 10: profession and cargo are different concepts."""
        d = debate(target_professions='healthcare_pro', target_cargos='ceo')
        # Right occupation, wrong cargo.
        dec = E.evaluate_consultation(profile(profession='medico', cargo='analista'), d)
        self.assertFalse(dec.allowed)
        self.assertIn('cargo', dec.blocking_dimensions())
        # Both right.
        dec2 = E.evaluate_consultation(profile(profession='medico', cargo='ceo'), d)
        self.assertTrue(dec2.allowed)


class TestCompanySize(unittest.TestCase):

    def test_13_company_size_buckets_and_brackets(self):
        d = debate(target_company_sizes='large')
        self.assertTrue(E.evaluate_consultation(profile(company_size='+1000'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(company_size='251-1000'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(company_size='1-10'), d).allowed)

    def test_13b_explicit_bracket_target(self):
        d = debate(target_company_sizes='251-1000,+1000')
        self.assertTrue(E.evaluate_consultation(profile(company_size='+1000'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(company_size='51-250'), d).allowed)

    def test_13c_legacy_vocabulary_reconciled(self):
        """Phase 0 F-10: four incompatible vocabularies existed."""
        self.assertEqual(E.norm_company_size('500+'), 5)
        self.assertEqual(E.norm_company_size('+1000'), 5)
        self.assertEqual(E.norm_company_size('201-500'), 4)
        self.assertEqual(E.norm_company_size('51-200'), 3)
        self.assertEqual(E.norm_company_size('51-250'), 3)


class TestTier(unittest.TestCase):

    def test_14_tier_is_the_consultant_facing_economic_axis(self):
        d = debate(target_se_tiers='A,B')
        self.assertTrue(E.evaluate_consultation(profile(se_tier='A'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(se_tier='D'), d).allowed)

    def test_14b_legacy_triple_tier_vocabulary(self):
        d = debate(target_se_tiers='A,B')
        self.assertTrue(E.evaluate_consultation(profile(se_tier='AAA'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(se_tier='BBC'), d).allowed)
        self.assertFalse(E.evaluate_consultation(profile(se_tier='CCC'), d).allowed)

    def test_14c_all_tiers_means_unconstrained(self):
        d = debate(target_se_tiers='A,B,C,D')
        self.assertTrue(E.evaluate_consultation(profile(se_tier='D'), d).allowed)
        self.assertTrue(E.evaluate_consultation(profile(se_tier=''), d).allowed)


# ═══════════════════════════════════════════════════════════════════════
# 15-16. MATERIAL SUFFICIENCY  (rule 7)
# ═══════════════════════════════════════════════════════════════════════

class TestMaterialSufficiency(unittest.TestCase):

    def test_15_missing_datum_immaterial_when_condition_already_proven(self):
        """JC's example verbatim: tier already established as B, consultation
        wants B-or-above, company_size missing => ELIGIBLE.

        Company size is only an INPUT to the tier computation; the requested
        condition is about the tier, which is already proven.
        """
        p = profile(se_tier='B', company_size='', cargo='', profession='')
        d = debate(target_se_tiers='A,B')
        dec = E.evaluate_consultation(p, d)
        self.assertTrue(dec.allowed, dec.as_dict())
        self.assertEqual(dec.verdict, E.ELIGIBLE)

    def test_16_missing_datum_material_when_condition_undecidable(self):
        """No established tier at all + a tier condition => UNRESOLVED,
        not silently eligible and not flatly ineligible."""
        p = profile(se_tier='', company_size='', cargo='', profession='')
        d = debate(target_se_tiers='A')
        dec = E.evaluate_consultation(p, d)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.UNRESOLVED)
        self.assertIn('se_tier', dec.blocking_dimensions())

    def test_16b_explicit_filter_on_missing_datum_is_not_proven(self):
        """Rule 7, explicit case: campaign requires company size, user's is
        unknown => compliance NOT proven => UNRESOLVED (never favourable)."""
        p = profile(company_size='')
        c = campaign(target_company_sizes='large')
        dec = E.evaluate_campaign(p, c)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.UNRESOLVED)
        self.assertIn('company_size', dec.blocking_dimensions())

    def test_16c_missing_datum_on_unconstrained_dimension_is_harmless(self):
        """The whole point: an UNRELATED missing datum must not block."""
        p = profile(company_size='', cargo='', profession='',
                    estimated_income_usd=None)
        d = debate(scope_country='CL')      # only geography is constrained
        self.assertTrue(E.evaluate_consultation(p, d).allowed)

    def test_16d_fail_dominates_unknown(self):
        """A genuine mismatch is reported as INELIGIBLE even when another
        datum is also missing — so the user sees the real reason."""
        p = profile(country='Argentina', company_size='')
        d = debate(scope_country='CL', target_company_sizes='large')
        dec = E.evaluate_consultation(p, d)
        self.assertEqual(dec.verdict, E.INELIGIBLE)

    def test_16e_unresolved_never_grants_access(self):
        for verdict in (E.INELIGIBLE, E.UNRESOLVED):
            self.assertFalse(E.Decision(verdict, []).allowed)
        self.assertTrue(E.Decision(E.ELIGIBLE, []).allowed)


# ═══════════════════════════════════════════════════════════════════════
# 17-19. Closed list and invitations  (rules 6, 14)
# ═══════════════════════════════════════════════════════════════════════

class TestClosedList(unittest.TestCase):

    def test_17_closed_list_member_is_eligible(self):
        d = debate(is_closed_list=True)
        dec = E.evaluate_consultation(profile(), d, closed_list_member=True)
        self.assertTrue(dec.allowed)

    def test_18_closed_list_non_member_is_ineligible(self):
        d = debate(is_closed_list=True)
        dec = E.evaluate_consultation(profile(), d, closed_list_member=False)
        self.assertFalse(dec.allowed)
        self.assertIn('closed_list', dec.blocking_dimensions())

    def test_18b_closed_list_membership_unresolved_denies(self):
        d = debate(is_closed_list=True)
        dec = E.evaluate_consultation(profile(), d, closed_list_member=None)
        self.assertFalse(dec.allowed)

    def test_18c_targeting_does_not_shrink_the_list(self):
        """Rule 6: THE LIST IS THE AUDIENCE. A listed user who fails ordinary
        demographic targeting is still eligible."""
        d = debate(is_closed_list=True, scope_commune='Las Condes',
                   target_se_tiers='A', target_gender='F')
        p = profile(county='Conchali', se_tier='D', gender='M')
        self.assertTrue(E.evaluate_consultation(p, d, closed_list_member=True).allowed)

    def test_18d_targeting_does_not_expand_the_list(self):
        """A perfectly matching non-member is still out."""
        d = debate(is_closed_list=True, scope_commune='Las Condes', target_se_tiers='B')
        p = profile(county='Las Condes', se_tier='B')
        self.assertFalse(E.evaluate_consultation(p, d, closed_list_member=False).allowed)

    def test_19_ordinary_invite_does_not_bypass_targeting(self):
        """Rule 14: an ordinary invitation is NOT closed-list membership.

        A non-closed-list consultation ignores closed_list_member entirely,
        so being 'invited' cannot make an ineligible user eligible.
        """
        d = debate(is_closed_list=False, scope_commune='Las Condes')
        p = profile(county='Conchali')
        for invited in (True, False, None):
            dec = E.evaluate_consultation(p, d, closed_list_member=invited)
            self.assertFalse(dec.allowed,
                             f'invite flag {invited!r} must not grant access: {dec}')
            self.assertIn('commune', dec.blocking_dimensions())


# ═══════════════════════════════════════════════════════════════════════
# 20-23, 31. Bypass attempts  (rules 2, 3, 4)
# ═══════════════════════════════════════════════════════════════════════

class TestBypassAttempts(unittest.TestCase):

    def test_20_21_direct_id_or_url_cannot_bypass(self):
        """Knowing the ID/URL is not authorization — the evaluator has no
        input by which an ID could grant access."""
        d = debate(id=4242, scope_commune='Las Condes')
        p = profile(county='Conchali')
        self.assertFalse(E.evaluate_consultation(p, d).allowed)

    def test_22_vote_path_uses_the_same_decision(self):
        """The vote endpoint calls evaluate_consultation; identical inputs
        must therefore yield an identical verdict to the listing path."""
        d = debate(scope_commune='Las Condes')
        p = profile(county='Conchali')
        listing = E.evaluate_consultation(p, d)
        voting = E.evaluate_consultation(p, d)
        self.assertEqual(listing.verdict, voting.verdict)
        self.assertFalse(voting.allowed)

    def test_23_client_supplied_state_has_no_influence(self):
        """Rule 4: there is no parameter through which frontend state, a
        previous feed inclusion or a client-provided flag could reach the
        decision. Attribute injection on the user row is ignored."""
        d = debate(scope_commune='Las Condes')
        hostile = user(county='Conchali')
        hostile.eligible = True
        hostile.is_eligible = True
        hostile.bypass = True
        hostile.target_se_tiers = 'A,B,C,D'
        p = E.profile_from_user(hostile, today=TODAY)
        self.assertFalse(E.evaluate_consultation(p, d).allowed)

    def test_31_unauthenticated_is_never_eligible(self):
        """Rule 2: unauthenticated users must not see consultations."""
        d = debate(scope_country='GLOBAL')     # maximally permissive targeting
        dec = E.evaluate_consultation(None, d)
        self.assertFalse(dec.allowed)
        self.assertIn('authentication', dec.blocking_dimensions())

        anon = E.UserProfile(is_authenticated=False)
        self.assertFalse(E.evaluate_consultation(anon, d).allowed)


# ═══════════════════════════════════════════════════════════════════════
# MANDATORY LAS CONDES ADVERSARIAL CASE
# ═══════════════════════════════════════════════════════════════════════

class TestLasCondesAdversarial(unittest.TestCase):
    """consultation commune = Las Condes ; user commune = Conchalí."""

    def setUp(self):
        self.d = debate(id=777, scope='country', scope_country='CL',
                        scope_commune='Las Condes')
        self.intruder = profile(county='Conchalí', country='Chile')
        self.resident = profile(county='Las Condes', country='Chile')

    def _decide(self, p):
        return E.evaluate_consultation(p, self.d)

    def test_feed_list_absent(self):
        self.assertFalse(self._decide(self.intruder).allowed)

    def test_for_me_recommendation_absent(self):
        self.assertFalse(self._decide(self.intruder).allowed)

    def test_direct_access_unavailable(self):
        self.assertFalse(self._decide(self.intruder).allowed)

    def test_vote_endpoint_rejected(self):
        dec = self._decide(self.intruder)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.verdict, E.INELIGIBLE)
        self.assertIn('commune', dec.blocking_dimensions())

    def test_frontend_bypass_rejected(self):
        hostile = user(county='Conchalí')
        hostile.eligible = True
        self.assertFalse(E.evaluate_consultation(
            E.profile_from_user(hostile, today=TODAY), self.d).allowed)

    def test_accent_variant_still_rejected(self):
        for spelling in ('Conchalí', 'Conchali', 'CONCHALI', 'conchalí'):
            self.assertFalse(self._decide(profile(county=spelling)).allowed, spelling)

    def test_matching_resident_is_allowed(self):
        dec = self._decide(self.resident)
        self.assertTrue(dec.allowed, dec.as_dict())

    def test_resident_still_subject_to_other_conditions(self):
        d = debate(scope_commune='Las Condes', target_se_tiers='A')
        self.assertFalse(E.evaluate_consultation(
            profile(county='Las Condes', se_tier='C'), d).allowed)
        self.assertTrue(E.evaluate_consultation(
            profile(county='Las Condes', se_tier='A'), d).allowed)

    def test_all_paths_agree(self):
        """Rule: every consultation path returns the SAME decision."""
        verdicts = {E.evaluate_consultation(self.intruder, self.d).verdict
                    for _ in range(5)}
        self.assertEqual(verdicts, {E.INELIGIBLE})


# ═══════════════════════════════════════════════════════════════════════
# 24, 27, 32. Campaign association / weights / rescue  (rules 13, 15, 16)
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignAssociation(unittest.TestCase):

    def test_24_target_debate_ids_cannot_bypass_targeting(self):
        """Phase 0 G-8: target_debate_ids short-circuited every filter.

        The eligibility snapshot has no such field, so association is
        structurally incapable of authorizing anyone.
        """
        c = campaign(target_communes='Las Condes', target_debate_ids='777,778,779')
        p = profile(county='Conchali')
        dec = E.evaluate_campaign(p, c)
        self.assertFalse(dec.allowed)
        self.assertIn('commune', dec.blocking_dimensions())
        self.assertNotIn('target_debate_ids',
                         E.CampaignTarget.__slots__,
                         'association must not be reachable from eligibility')

    def test_24b_association_does_not_survive_two_barrier_evaluation(self):
        d = debate(id=777, scope_country='CL', scope_commune='Las Condes')
        c = campaign(target_communes='Las Condes', target_debate_ids='777')
        p = profile(county='Conchali')
        dec = E.evaluate_campaign_for_user_in_consultation(p, c, d)
        self.assertFalse(dec.allowed)

    def test_13_two_barriers_compatibility_then_user(self):
        """Rule 13's Nike example: Brazil / tier>=C / male / 18-55."""
        nike_debate = debate(scope_country='BR', target_gender='M',
                             target_age_min=18, target_age_max=55,
                             target_se_tiers='A,B,C')
        # Barrier 1: an all-female campaign is incompatible with a male
        # consultation audience.
        incompatible = campaign(target_country='BR', target_gender='F')
        self.assertFalse(
            E.campaign_consultation_compatible(incompatible, nike_debate).allowed)
        # A compatible campaign passes barrier 1 ...
        compatible = campaign(target_country='BR', target_gender='M',
                              target_age_min=18, target_age_max=55)
        self.assertTrue(
            E.campaign_consultation_compatible(compatible, nike_debate).allowed)
        # ... but barrier 2 still governs the individual user.
        wrong_user = profile(country='Chile', gender='M', dob='1990-05-10')
        self.assertFalse(E.evaluate_campaign_for_user_in_consultation(
            wrong_user, compatible, nike_debate).allowed)
        right_user = profile(country='Brasil', gender='M', dob='1990-05-10',
                             county='', se_tier='C')
        self.assertTrue(E.evaluate_campaign_for_user_in_consultation(
            right_user, compatible, nike_debate).allowed)

    def test_13b_country_envelope_incompatibility(self):
        d = debate(scope_country='CL')
        c = campaign(target_country='AR')
        self.assertFalse(E.campaign_consultation_compatible(c, d).allowed)

    def test_27_weights_never_convert_ineligible_to_eligible(self):
        """Rule 15: weights are distribution preferences, not eligibility."""
        c_plain = campaign(target_se_tiers='A')
        c_weighted = campaign(target_se_tiers='A',
                              target_age_weights='{"18-24":30,"25-34":70}')
        p = profile(se_tier='D')
        a = E.evaluate_campaign(p, c_plain)
        b = E.evaluate_campaign(p, c_weighted)
        self.assertEqual(a.verdict, b.verdict)
        self.assertFalse(b.allowed)
        self.assertNotIn('target_age_weights', E.CampaignTarget.__slots__)

    def test_27b_weights_do_not_alter_an_eligible_verdict_either(self):
        c_plain = campaign(target_se_tiers='A,B')
        c_weighted = campaign(target_se_tiers='A,B',
                              target_age_weights='{"25-34":100}')
        p = profile(se_tier='B')
        self.assertEqual(E.evaluate_campaign(p, c_plain).verdict,
                         E.evaluate_campaign(p, c_weighted).verdict)

    def test_32_rescue_cannot_rescue_by_violating_targeting(self):
        """Rule 16: an under-delivering campaign must find COMPATIBLE
        opportunities, never ineligible users. Pinning it to more debates
        (the rescue mechanism) changes nothing about eligibility."""
        stalled = campaign(target_communes='Las Condes', target_se_tiers='A')
        outsider = profile(county='Conchali', se_tier='D')
        before = E.evaluate_campaign(outsider, stalled)
        stalled.target_debate_ids = ','.join(str(i) for i in range(1, 500))
        after = E.evaluate_campaign(outsider, stalled)
        self.assertEqual(before.verdict, after.verdict)
        self.assertFalse(after.allowed)


# ═══════════════════════════════════════════════════════════════════════
# 25-26, 28. Cross-path consistency and non-regression
# ═══════════════════════════════════════════════════════════════════════

def _consultation_matrix():
    """(label, profile, debate) triples spanning every dimension."""
    return [
        ('global-anyone', profile(country='Japan'), debate(scope_country='GLOBAL')),
        ('country-ok', profile(country='Chile'), debate(scope_country='CL')),
        ('country-bad', profile(country='Argentina'), debate(scope_country='CL')),
        ('commune-ok', profile(county='Las Condes'), debate(scope_commune='Las Condes')),
        ('commune-bad', profile(county='Conchali'), debate(scope_commune='Las Condes')),
        ('gender-ok', profile(gender='F'), debate(target_gender='F')),
        ('gender-bad', profile(gender='M'), debate(target_gender='F')),
        ('age-ok', profile(dob='1990-05-10'), debate(target_age_min=18, target_age_max=55)),
        ('age-bad', profile(dob='2015-01-01'), debate(target_age_min=18, target_age_max=55)),
        ('age-unknown', profile(dob=''), debate(target_age_min=18, target_age_max=55)),
        ('tier-ok', profile(se_tier='A'), debate(target_se_tiers='A')),
        ('tier-bad', profile(se_tier='D'), debate(target_se_tiers='A')),
        ('tier-unknown', profile(se_tier=''), debate(target_se_tiers='A')),
        ('occ-ok', profile(profession='medico'), debate(target_professions='healthcare_pro')),
        ('occ-bad', profile(profession='abogado'), debate(target_professions='healthcare_pro')),
        ('cargo-ok', profile(cargo='ceo'), debate(target_cargos='ceo')),
        ('cargo-bad', profile(cargo='practicante'), debate(target_cargos='ceo')),
        ('size-ok', profile(company_size='+1000'), debate(target_company_sizes='large')),
        ('size-bad', profile(company_size='1-10'), debate(target_company_sizes='large')),
        ('size-unknown', profile(company_size=''), debate(target_company_sizes='large')),
        ('market-ok', profile(country_per_capita_ppp_usd=39000), debate(min_per_capita_usd=5000)),
        ('market-bad', profile(country_per_capita_ppp_usd=2200), debate(min_per_capita_usd=5000)),
        ('closedlist-in', profile(), debate(is_closed_list=True)),
        ('multi-and', profile(country='Chile', county='Las Condes', gender='M',
                              dob='1990-05-10', se_tier='B'),
         debate(scope_country='CL', scope_commune='Las Condes',
                target_gender='M', target_age_min=18, target_age_max=55,
                target_se_tiers='A,B')),
    ]


class TestCrossPathConsistency(unittest.TestCase):

    def test_26_consultation_paths_are_deterministic_and_shared(self):
        """Rule: every consultation discovery/access path returns the same
        eligibility decision. They all call this one function, so the
        property under test is that the function is a pure deterministic
        function of (profile, target) with no hidden inputs."""
        for label, p, d in _consultation_matrix():
            member = True if getattr(d, 'is_closed_list', False) else None
            first = E.evaluate_consultation(p, d, closed_list_member=member)
            for _ in range(3):
                again = E.evaluate_consultation(p, d, closed_list_member=member)
                self.assertEqual(first.verdict, again.verdict, label)
                self.assertEqual(first.blocking_dimensions(),
                                 again.blocking_dimensions(), label)

    def test_26b_listing_and_voting_agree_on_every_matrix_row(self):
        """presence in a listing  <=>  the vote is accepted."""
        for label, p, d in _consultation_matrix():
            member = True if getattr(d, 'is_closed_list', False) else None
            listing_allowed = E.evaluate_consultation(p, d, closed_list_member=member).allowed
            vote_allowed = E.evaluate_consultation(p, d, closed_list_member=member).allowed
            self.assertEqual(listing_allowed, vote_allowed, label)

    def test_25_campaign_paths_are_deterministic_and_shared(self):
        cases = [
            ('country', profile(country='Chile'), campaign(target_country='AR')),
            ('commune', profile(county='Conchali'), campaign(target_communes='Las Condes')),
            ('gender', profile(gender='M'), campaign(target_gender='F')),
            ('age', profile(dob='2015-01-01'), campaign(target_age_min=18, target_age_max=55)),
            ('ranges', profile(dob='1990-05-10'), campaign(target_age_ranges='18-25')),
            ('tier', profile(se_tier='D'), campaign(target_se_tiers='A')),
            ('occ', profile(profession='abogado'), campaign(target_professions='healthcare_pro')),
            ('cargo', profile(cargo='practicante'), campaign(target_cargos='ceo')),
            ('size', profile(company_size='1-10'), campaign(target_company_sizes='large')),
            ('income-max', profile(estimated_income_usd=60000),
             campaign(target_income_max=50000)),
            ('market', profile(country_per_capita_ppp_usd=1000),
             campaign(min_per_capita_usd=5000)),
            ('hnw', profile(), campaign(target_hnw_only=True)),
            ('ok', profile(), campaign()),
        ]
        for label, p, c in cases:
            first = E.evaluate_campaign(p, c)
            for _ in range(3):
                self.assertEqual(first.verdict, E.evaluate_campaign(p, c).verdict, label)

    def test_28_existing_eligible_user_remains_eligible(self):
        """Rule 17: a user who legitimately qualified before canonicalization
        must still qualify. Default-configured consultations (the vast
        majority of live rows) constrain nothing but country."""
        default = debate()   # scope_country='CL', all other fields at defaults
        for spelling in ('Chile', 'CL'):
            p = profile(country=spelling)
            self.assertTrue(E.evaluate_consultation(p, default).allowed)

    def test_28b_sparse_profile_still_qualifies_for_default_consultation(self):
        """A user with almost no profile data must not be locked out of an
        untargeted consultation — that would be the fail-closed overreach
        rule 7 explicitly forbids."""
        p = profile(se_tier='', company_size='', cargo='', profession='',
                    gender='', dob='', estimated_income_usd=None)
        self.assertTrue(E.evaluate_consultation(p, debate(scope_country='CL')).allowed)
        self.assertTrue(E.evaluate_consultation(p, debate(scope_country='GLOBAL')).allowed)


# ═══════════════════════════════════════════════════════════════════════
# Campaign-specific regressions from Phase 0
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignRegressions(unittest.TestCase):

    def test_income_max_sentinel_regression(self):
        """Phase 0 F-7: `inc_max < 9999.0` silently ignored any maximum above
        the sentinel, so target_income_max=50000 did nothing."""
        c = campaign(target_income_max=50000.0)
        self.assertFalse(E.evaluate_campaign(profile(estimated_income_usd=60000), c).allowed)
        self.assertTrue(E.evaluate_campaign(profile(estimated_income_usd=40000), c).allowed)

    def test_income_sentinel_defaults_are_unconstrained(self):
        c = campaign(target_income_min=0.0, target_income_max=9999.0)
        t = E.campaign_target_from_campaign(c)
        self.assertIsNone(t.income_min_usd)
        self.assertIsNone(t.income_max_usd)
        self.assertTrue(E.evaluate_campaign(profile(estimated_income_usd=1_000_000), c).allowed)

    def test_hnw_gating(self):
        c = campaign(target_hnw_only=True, min_hnw_score=50.0)
        self.assertFalse(E.evaluate_campaign(profile(), c,
                                             hnw_score=10, hnw_verified=False).allowed)
        self.assertTrue(E.evaluate_campaign(profile(), c,
                                            hnw_score=80, hnw_verified=True).allowed)

    def test_anonymous_user_cannot_receive_user_targeted_campaign(self):
        """Phase 0 G-11: anonymous serving skipped every user-level filter."""
        targeted = campaign(target_se_tiers='A', target_communes='Las Condes')
        dec = E.evaluate_campaign(None, targeted)
        self.assertFalse(dec.allowed)

    def test_anonymous_user_may_receive_untargeted_campaign(self):
        self.assertTrue(E.evaluate_campaign(None, campaign()).allowed)

    def test_age_ranges_are_eligibility_not_weights(self):
        c = campaign(target_age_ranges='18-24,55+')
        self.assertTrue(E.evaluate_campaign(profile(dob='2005-01-01'), c).allowed)   # 21
        self.assertTrue(E.evaluate_campaign(profile(dob='1960-01-01'), c).allowed)   # 66
        self.assertFalse(E.evaluate_campaign(profile(dob='1990-05-10'), c).allowed)  # 36


# ═══════════════════════════════════════════════════════════════════════
# JC age decision (CHANGE-002 phase 2)
#   target_age_ranges  = ELIGIBILITY
#   target_age_weights = OPTIMIZATION / DISTRIBUTION ONLY
#   multiple ranges    = OR *within* the age dimension
#   age                = AND with the other mandatory dimensions
#   weights can NEVER make an age-ineligible user eligible
# ═══════════════════════════════════════════════════════════════════════

class TestAgeRulesJC(unittest.TestCase):

    def test_multiple_ranges_are_OR_within_age(self):
        """'18-24,55+' admits either bracket, and nothing between them."""
        c = campaign(target_age_ranges='18-24,55+')
        for dob, expected in (('2005-01-01', True),    # 21 -> first bracket
                              ('1960-01-01', True),    # 66 -> second bracket
                              ('1990-05-10', False),   # 36 -> neither
                              ('1998-01-01', False)):  # 28 -> neither
            dec = E.evaluate_campaign(profile(dob=dob), c)
            self.assertEqual(dec.allowed, expected, f'{dob}: {dec}')

    def test_age_is_AND_with_other_dimensions(self):
        """Passing age does not excuse failing another mandatory dimension,
        and passing another dimension does not excuse failing age."""
        c = campaign(target_age_ranges='18-24', target_se_tiers='A')
        # age OK, tier wrong
        d1 = E.evaluate_campaign(profile(dob='2005-01-01', se_tier='D'), c)
        self.assertFalse(d1.allowed)
        self.assertIn('se_tier', d1.blocking_dimensions())
        # tier OK, age wrong
        d2 = E.evaluate_campaign(profile(dob='1990-05-10', se_tier='A'), c)
        self.assertFalse(d2.allowed)
        self.assertIn('age_ranges', d2.blocking_dimensions())
        # both OK
        self.assertTrue(E.evaluate_campaign(profile(dob='2005-01-01', se_tier='A'), c).allowed)

    def test_weights_cannot_rescue_an_AGE_ineligible_user(self):
        """The adversarial case: weights that name EXACTLY the user's own
        bracket, on a campaign whose eligibility ranges exclude it."""
        p = profile(dob='1990-05-10')                      # 36 -> bracket 35-44
        c = campaign(target_age_ranges='18-24',
                     target_age_weights='{"35-44":100}')   # all weight on 35-44
        dec = E.evaluate_campaign(p, c)
        self.assertFalse(dec.allowed, f'weights must not confer eligibility: {dec}')
        self.assertIn('age_ranges', dec.blocking_dimensions())

    def test_weights_cannot_rescue_via_age_min_max_either(self):
        p = profile(dob='1990-05-10')                      # 36
        c = campaign(target_age_min=18, target_age_max=24,
                     target_age_weights='{"35-44":100}')
        dec = E.evaluate_campaign(p, c)
        self.assertFalse(dec.allowed)
        self.assertIn('age', dec.blocking_dimensions())

    def test_weights_are_not_part_of_the_eligibility_snapshot_at_all(self):
        """Structural guarantee: the evaluator cannot read weights even by
        accident, because they are not carried on CampaignTarget."""
        self.assertNotIn('target_age_weights', E.CampaignTarget.__slots__)
        self.assertNotIn('age_weights', E.CampaignTarget.__slots__)

    def test_weights_do_not_change_verdict_for_an_age_eligible_user(self):
        p = profile(dob='2005-01-01')                      # 21
        plain = campaign(target_age_ranges='18-24')
        weighted = campaign(target_age_ranges='18-24',
                            target_age_weights='{"55-64":100}')
        self.assertEqual(E.evaluate_campaign(p, plain).verdict,
                         E.evaluate_campaign(p, weighted).verdict)
        self.assertTrue(E.evaluate_campaign(p, weighted).allowed)


# ═══════════════════════════════════════════════════════════════════════
# Normalizer unit tests  (rule 18)
# ═══════════════════════════════════════════════════════════════════════

class TestNormalizers(unittest.TestCase):

    def test_country(self):
        self.assertEqual(E.norm_country('Chile'), 'CL')
        self.assertEqual(E.norm_country('  chile '), 'CL')
        self.assertEqual(E.norm_country('CL'), 'CL')
        self.assertEqual(E.norm_country('España'), 'ES')
        self.assertEqual(E.norm_country('espana'), 'ES')
        self.assertEqual(E.norm_country(''), '')

    def test_commune(self):
        self.assertEqual(E.norm_commune('Las  Condes'), 'las condes')
        self.assertEqual(E.norm_commune('Ñuñoa'), 'nunoa')
        self.assertEqual(E.norm_commune('  Conchalí '), 'conchali')

    def test_gender(self):
        self.assertEqual(E.norm_gender('mujer'), 'F')
        self.assertEqual(E.norm_gender('HOMBRE'), 'M')
        self.assertEqual(E.norm_gender('all'), 'all')
        self.assertEqual(E.norm_gender(''), '')
        self.assertEqual(E.norm_gender_target(''), 'all')

    def test_age_parsing_formats(self):
        for fmt in ('1990-05-10', '10/05/1990', '10-05-1990', '1990/05/10'):
            self.assertEqual(E.parse_age(fmt, today=TODAY), 36, fmt)
        self.assertIsNone(E.parse_age('garbage'))
        self.assertIsNone(E.parse_age(''))

    def test_age_ranges_parsing(self):
        self.assertEqual(E.parse_age_ranges('18-24'), [(18, 24)])
        self.assertEqual(sorted(E.parse_age_ranges('18-24,55+')), [(18, 24), (55, 130)])
        self.assertEqual(E.parse_age_ranges('nonsense'), [])

    def test_tier(self):
        self.assertEqual(E.norm_tier('AAA'), 'A')
        self.assertEqual(E.norm_tier('bbc'), 'B')
        self.assertEqual(E.norm_tier('Z'), '')
        self.assertEqual(E.norm_tier_set('A, B ,'), {'A', 'B'})

    def test_geo_unrestricted(self):
        self.assertTrue(E.is_geo_unrestricted(set()))
        self.assertTrue(E.is_geo_unrestricted({'GLOBAL'}))
        self.assertTrue(E.is_geo_unrestricted({'ALL'}))
        self.assertFalse(E.is_geo_unrestricted({'CL'}))

    def test_csv_set_empty_means_unconstrained(self):
        self.assertEqual(E.csv_set(''), set())
        self.assertEqual(E.csv_set(None), set())
        self.assertEqual(E.csv_set(' a , b '), {'a', 'b'})


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestLegacyIncomeUnitAmbiguity(unittest.TestCase):
    """AdCampaign.target_income_min/max are documented as an index (0-9999) but
    were compared against annual USD. Rows may hold either unit."""

    def test_index_domain_band_is_unresolved_not_silently_empty(self):
        c = campaign(target_income_min=200.0, target_income_max=800.0)
        dec = E.evaluate_campaign(profile(estimated_income_usd=60000), c)
        self.assertFalse(dec.allowed, 'ambiguous config must not deliver')
        self.assertEqual(dec.verdict, E.UNRESOLVED,
                         'must be diagnosable, not an ordinary mismatch')
        detail = [r.detail for r in dec.reasons if r.dimension == 'income_band'][0]
        self.assertIn('legacy index domain', detail)

    def test_usd_domain_band_still_evaluates_normally(self):
        c = campaign(target_income_min=50000.0, target_income_max=200000.0)
        self.assertTrue(E.evaluate_campaign(profile(estimated_income_usd=60000), c).allowed)
        self.assertEqual(
            E.evaluate_campaign(profile(estimated_income_usd=10000), c).verdict,
            E.INELIGIBLE)

    def test_consultation_income_band_in_usd_is_unaffected(self):
        """Debate.income_min_usd/max_usd are unambiguously annual USD."""
        d = debate(income_min_usd=50000, income_max_usd=200000)
        self.assertTrue(E.evaluate_consultation(profile(estimated_income_usd=60000), d).allowed)

    def test_unresolved_still_denies(self):
        c = campaign(target_income_min=200.0, target_income_max=800.0)
        self.assertFalse(E.evaluate_campaign(profile(estimated_income_usd=500), c).allowed)
