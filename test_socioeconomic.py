"""
test_socioeconomic.py — CHANGE-003 canonical classification test suite.

Stdlib only (unittest). Run:

    python3 -m unittest test_socioeconomic -v

The canonical classifier is dependency-free, so these run without fastapi /
sqlalchemy / postgres. Endpoint wiring is covered by test_socioeconomic_wiring
and the HTTP suite.

Several tests here exist specifically to FAIL if a historical defect is
reintroduced — the nominal-GDP-as-PPP confusion, and the age/title promotions.
"""

import unittest
from datetime import date, datetime

import socioeconomic as S


def ctx(country='CL', ppp=29500, source='world_bank_ny_gnp_pcap_pp_cd',
        median=None, year=2023):
    return S.CountryEconomicContext(
        country=country, ppp_per_capita_usd=ppp, ppp_source=source,
        ppp_year=year, median_personal_income_usd=median)


def income(amount, **kw):
    """Test-fixture convenience only: unless a test says otherwise, its
    income figures are explicit USD/annual so the fixture is testing TIER
    logic, not currency/period ambiguity. Production code paths (main.py's
    adapters) must always pass currency/period explicitly and never rely on
    a default — see the CHANGE-003 remediation note on IncomeObservation."""
    kw.setdefault('source', S.DECLARED)
    kw.setdefault('currency', 'USD')
    kw.setdefault('period', S.PERIOD_ANNUAL)
    return S.IncomeObservation(amount=amount, **kw)


# ═══════════════════════════════════════════════════════════════════════
# 1. PPP field selection — the historical bug must stay dead
# ═══════════════════════════════════════════════════════════════════════

class TestPPPFieldSelection(unittest.TestCase):

    def test_accepted_ppp_source_resolves(self):
        c = ctx(ppp=29500, source='world_bank_ny_gnp_pcap_pp_cd')
        self.assertTrue(c.resolved)
        self.assertEqual(c.ppp_per_capita_usd, 29500.0)

    def test_reference_table_source_is_accepted(self):
        c = ctx(source='marketer_table_v2_gni_per_capita_ppp')
        self.assertTrue(c.resolved)

    def test_NOMINAL_source_is_REFUSED(self):
        """THE regression test. If someone wires a nominal series into the
        PPP slot again, this fails."""
        for bad in ('nominal_gdp_per_capita', 'world_bank_ny_gdp_pcap_cd', 'nominal'):
            with self.subTest(source=bad):
                c = ctx(ppp=17000, source=bad)
                self.assertFalse(c.resolved, f'{bad} must not resolve')
                self.assertIsNone(c.ppp_per_capita_usd)
                self.assertIn('refused', c.rejected_reason.lower())

    def test_unrecognised_provenance_is_refused(self):
        c = ctx(ppp=29500, source='some_spreadsheet')
        self.assertFalse(c.resolved)
        self.assertIn('unrecognised', c.rejected_reason.lower())

    def test_missing_provenance_is_refused(self):
        c = ctx(ppp=29500, source='')
        self.assertFalse(c.resolved)

    def test_nominal_and_ppp_produce_DIFFERENT_tiers(self):
        """Why the confusion mattered: same income, different verdict.

        Chile nominal ~17k vs PPP ~29.5k. An income of 30k USD is 2.0x the
        derived median under PPP (tier B) but 3.5x under nominal (tier A).
        """
        ppp_ctx = ctx(ppp=29500, source='world_bank_ny_gnp_pcap_pp_cd')
        # Simulate the OLD behaviour: a nominal figure accepted as if PPP.
        nominal_as_if_ppp = S.CountryEconomicContext(
            country='CL', ppp_per_capita_usd=17000,
            ppp_source='test_fixture_ppp')
        t_ppp, _ = S.tier_from_income(30000, ppp_ctx)
        t_nom, _ = S.tier_from_income(30000, nominal_as_if_ppp)
        self.assertEqual(t_ppp, 'B')
        self.assertEqual(t_nom, 'A')
        self.assertNotEqual(t_ppp, t_nom)

    def test_ppp_must_be_positive(self):
        for bad in (0, -1):
            self.assertFalse(ctx(ppp=bad).resolved)

    def test_missing_ppp_leaves_context_unresolved(self):
        self.assertFalse(ctx(ppp=None).resolved)


# ═══════════════════════════════════════════════════════════════════════
# 2. A/B/C/D from known income  (R1, R2)
# ═══════════════════════════════════════════════════════════════════════

class TestTierFromIncome(unittest.TestCase):

    def setUp(self):
        # median measured at 20,000 so the bands are exact round numbers
        self.c = ctx(median=20000)

    def test_band_boundaries_are_inclusive_at_the_floor(self):
        for amount, expected in ((60000, 'A'), (59999, 'B'),
                                 (30000, 'B'), (29999, 'C'),
                                 (14000, 'C'), (13999, 'D'),
                                 (0, 'D')):
            with self.subTest(amount=amount):
                self.assertEqual(S.tier_from_income(amount, self.c)[0], expected)

    def test_ratio_is_reported(self):
        t, r = S.tier_from_income(40000, self.c)
        self.assertEqual(t, 'B')
        self.assertAlmostEqual(r, 2.0)

    def test_country_relative_same_income_different_tier(self):
        """R2: A/B/C/D is a position in the LOCAL market."""
        poor = ctx(country='NG', median=2000)
        rich = ctx(country='CH', median=60000)
        self.assertEqual(S.tier_from_income(30000, poor)[0], 'A')
        self.assertEqual(S.tier_from_income(30000, rich)[0], 'D')

    def test_unresolved_context_gives_no_tier(self):
        self.assertEqual(S.tier_from_income(50000, ctx(ppp=None)), (None, None))

    def test_non_numeric_income_gives_no_tier(self):
        for bad in ('abc', None, object()):
            self.assertEqual(S.tier_from_income(bad, self.c), (None, None))

    def test_negative_income_is_not_silently_zero(self):
        self.assertEqual(S.tier_from_income(-100, self.c), (None, None))


# ═══════════════════════════════════════════════════════════════════════
# 3. Income is PRIMARY — profession/title/company may not promote  (R1)
# ═══════════════════════════════════════════════════════════════════════

class TestNoPromotionFromProfile(unittest.TestCase):

    def setUp(self):
        self.c = ctx(median=20000)

    def test_prestigious_title_does_not_change_tier(self):
        low = [income(12000, source=S.DECLARED_CONFIRMED)]
        plain = S.classify(low, self.c, {})
        fancy = S.classify(low, self.c, {
            'occupation': 'medico', 'cargo': 'ceo', 'company_size_rank': 5})
        self.assertEqual(plain.tier, fancy.tier)
        self.assertEqual(fancy.tier, 'D')

    def test_big_company_does_not_promote(self):
        obs = [income(25000, source=S.DECLARED_CONFIRMED)]
        for rank in (0, 1, 2, 3, 4, 5):
            with self.subTest(company_size_rank=rank):
                c = S.classify(obs, self.c, {'company_size_rank': rank})
                self.assertEqual(c.tier, 'C')

    def test_professional_profile_is_recorded_but_flagged_unused(self):
        c = S.classify([income(25000)], self.c, {'cargo': 'gerente'})
        self.assertEqual(c.professional.get('cargo'), 'gerente')
        self.assertTrue(any('not used for tier' in r for r in c.reasons))

    def test_ceo_of_tiny_firm_with_low_income_stays_low(self):
        c = S.classify([income(9000, source=S.DECLARED_CONFIRMED)], self.c,
                       {'cargo': 'ceo', 'company_size_rank': 1})
        self.assertEqual(c.tier, 'D')


# ═══════════════════════════════════════════════════════════════════════
# 4. Individual vs household  (R5)
# ═══════════════════════════════════════════════════════════════════════

class TestIndividualVsHousehold(unittest.TestCase):

    def setUp(self):
        self.c = ctx(median=20000)

    def test_household_observation_is_never_used_for_tier(self):
        household = S.IncomeObservation(amount=90000, source=S.DECLARED,
                                        note='household')
        individual = income(15000, source=S.DECLARED_CONFIRMED)
        c = S.classify([individual, household], self.c, {})
        self.assertEqual(c.tier, 'C')          # from 15k, not 90k
        self.assertEqual(c.income_used, 15000)

    def test_household_alone_does_not_resolve_a_tier(self):
        household = S.IncomeObservation(amount=90000, source=S.DECLARED,
                                        note='household')
        c = S.classify([household], self.c, {})
        self.assertFalse(c.resolved)
        self.assertEqual(c.verdict, S.UNRESOLVED)

    def test_select_income_filters_household(self):
        household = S.IncomeObservation(amount=99999, note='household')
        self.assertIsNone(S.select_income([household]))


# ═══════════════════════════════════════════════════════════════════════
# 5. Declared beats estimated  (R6)
# ═══════════════════════════════════════════════════════════════════════

class TestIncomePrecedence(unittest.TestCase):

    def setUp(self):
        self.c = ctx(median=20000)

    def test_confirmed_declared_beats_every_estimate(self):
        obs = [
            income(70000, source=S.ESTIMATED_OCCUPATION),
            income(15000, source=S.DECLARED_CONFIRMED),
            income(90000, source=S.ESTIMATED_COUNTRY),
        ]
        c = S.classify(obs, self.c, {})
        self.assertEqual(c.income_source, S.DECLARED_CONFIRMED)
        self.assertEqual(c.tier, 'C')
        self.assertTrue(c.based_on_declared_income)

    def test_estimate_may_never_overwrite_declared(self):
        self.assertFalse(S.may_overwrite(S.DECLARED, None, S.ESTIMATED_OCCUPATION, None))
        self.assertFalse(S.may_overwrite(S.DECLARED_CONFIRMED, None, S.DECLARED, None))

    def test_declared_overwrites_estimate(self):
        self.assertTrue(S.may_overwrite(S.ESTIMATED_OCCUPATION, None, S.DECLARED, None))

    def test_same_rank_requires_strictly_newer(self):
        old, new = date(2025, 1, 1), date(2026, 1, 1)
        self.assertTrue(S.may_overwrite(S.DECLARED, old, S.DECLARED, new))
        self.assertFalse(S.may_overwrite(S.DECLARED, new, S.DECLARED, old))
        self.assertFalse(S.may_overwrite(S.DECLARED, new, S.DECLARED, new))

    def test_estimate_ordering_among_estimates(self):
        obs = [income(50000, source=S.ESTIMATED_COUNTRY),
               income(30000, source=S.ESTIMATED_OCCUPATION)]
        self.assertEqual(S.select_income(obs).source, S.ESTIMATED_OCCUPATION)

    def test_classification_flags_that_it_rests_on_an_estimate(self):
        c = S.classify([income(30000, source=S.ESTIMATED_OCCUPATION)], self.c, {})
        self.assertFalse(c.based_on_declared_income)
        self.assertTrue(any('ESTIMATE' in r for r in c.reasons))


# ═══════════════════════════════════════════════════════════════════════
# 6. Income representation — normalize without destroying  (R8)
# ═══════════════════════════════════════════════════════════════════════

class TestIncomeRepresentation(unittest.TestCase):

    def test_monthly_normalizes_to_annual(self):
        self.assertEqual(income(1000, period='monthly').annual_usd, 12000)

    def test_period_aliases(self):
        for alias in ('mensual', 'month', 'MONTHLY', 'mes'):
            self.assertEqual(S.normalize_period(alias), S.PERIOD_MONTHLY)
        for alias in ('anual', 'year', 'YEARLY', 'año'):
            self.assertEqual(S.normalize_period(alias), S.PERIOD_ANNUAL)

    def test_weekly_daily_hourly(self):
        self.assertEqual(income(1000, period='weekly').annual_usd, 52000)
        self.assertEqual(income(100, period='daily').annual_usd, 26000)
        self.assertEqual(income(50, period='hourly').annual_usd, 104000)

    def test_original_declaration_is_preserved(self):
        o = income(850000, currency='CLP', period='monthly',
                   fx_rate_to_usd=1 / 950)
        self.assertEqual(o.amount, 850000)          # untouched
        self.assertEqual(o.currency, 'CLP')         # untouched
        self.assertEqual(o.period, 'monthly')       # untouched
        self.assertAlmostEqual(o.annual_usd, 850000 / 950 * 12, places=2)

    def test_range_uses_the_midpoint_not_the_top(self):
        o = income(20000, amount_max=40000)
        self.assertTrue(o.is_range)
        self.assertEqual(o.annual_usd, 30000)

    def test_range_endpoints_are_both_preserved(self):
        o = income(20000, amount_max=40000)
        self.assertEqual((o.amount, o.amount_max), (20000, 40000))

    def test_foreign_currency_without_fx_is_UNUSABLE_not_assumed_usd(self):
        """R7: refusing to guess is the correct behaviour."""
        o = income(850000, currency='CLP')      # no fx rate supplied
        self.assertIsNone(o.annual_usd)

    def test_unusable_observation_is_skipped_by_selection(self):
        good = income(30000)
        bad = income(850000, currency='CLP')     # unusable
        self.assertIs(S.select_income([bad, good]), good)

    def test_as_dict_carries_both_original_and_normalized(self):
        d = income(1000, period='monthly').as_dict()
        self.assertEqual(d['amount'], 1000)
        self.assertEqual(d['period'], 'monthly')
        self.assertEqual(d['annual_usd'], 12000)


# ═══════════════════════════════════════════════════════════════════════
# 6b. Blocker B1 — an ambiguous currency can NEVER produce a tier
# ═══════════════════════════════════════════════════════════════════════
#
# A prior version of IncomeObservation defaulted a missing/blank currency to
# 'USD' — including when a caller explicitly passed '' — so a user row with
# a blank declared_income_currency column (the column's own SQL default) was
# silently priced as USD. Every test below fails against that version.

class TestAmbiguousCurrencyNeverClassifies(unittest.TestCase):

    def setUp(self):
        self.ctx = ctx(median=20000)

    def _assert_unusable(self, **kw):
        """Isolation fix (re-audit finding): a valid `period` is defaulted
        here UNLESS the caller overrides it, so every test in this class
        proves the CURRENCY protection specifically rather than incidentally
        passing because period is also unset. Before this default, most
        tests here would keep passing even if the currency-defaulting fix
        alone were reverted, because the (separate) period-defaulting fix
        would still block resolution — verified by mutation: reverting only
        the currency default previously failed 2 of 9 tests in this class,
        not 9. With the default below, all of them isolate currency."""
        kw.setdefault('period', S.PERIOD_ANNUAL)
        o = S.IncomeObservation(amount=1_000_000, source=S.DECLARED_CONFIRMED, **kw)
        self.assertIsNone(o.annual_usd,
                          f'ambiguous currency {kw.get("currency")!r} produced annual_usd')
        c = S.classify([o], self.ctx, {})
        self.assertFalse(c.resolved,
                         f'ambiguous currency {kw.get("currency")!r} produced a resolved tier')
        self.assertIsNone(c.tier)

    def test_none_currency_never_classifies(self):
        self._assert_unusable(currency=None)

    def test_omitted_currency_never_classifies(self):
        """No currency argument at all — not even the keyword — must behave
        identically to explicitly passing None/''. There is no 'default
        currency' in this module; a caller who means USD must say USD.

        `period` IS supplied explicitly here (unlike currency) so this test
        isolates the currency default specifically, not the period one."""
        o = S.IncomeObservation(amount=1_000_000, period=S.PERIOD_ANNUAL,
                                source=S.DECLARED_CONFIRMED)
        self.assertIsNone(o.annual_usd)

    def test_empty_string_currency_never_classifies(self):
        self._assert_unusable(currency='')

    def test_whitespace_only_currency_never_classifies(self):
        for blank in ('   ', '\t', '\n', '  \t \n '):
            self._assert_unusable(currency=blank)

    def test_unknown_currency_with_no_fx_never_classifies(self):
        """A well-formed but unpriced code (e.g. a real ISO currency this
        platform has no FX rate for yet) is different from a blank one — but
        it must ALSO never classify, because compliance with 'this is a
        priceable amount' is not proven (R7)."""
        self._assert_unusable(currency='XYZ')

    def test_blank_currency_is_not_rescued_by_a_present_fx_rate(self):
        """A stray fx_rate_to_usd attached to a blank currency must not
        smuggle a number through — the currency check happens first."""
        self._assert_unusable(currency='', fx_rate_to_usd=1.0)
        self._assert_unusable(currency='   ', fx_rate_to_usd=0.001)

    def test_invalid_fx_never_defaults_to_usd(self):
        for bad_rate in (0, -1, None, 'not-a-number'):
            self._assert_unusable(currency='CLP', fx_rate_to_usd=bad_rate)

    def test_non_finite_fx_never_classifies(self):
        """Re-audit finding: NaN and +/-Infinity are not caught by
        `if not rate or rate <= 0` (both comparisons are False for NaN), so
        a non-finite fx_rate_to_usd used to slip through IncomeObservation
        and, via tier_from_income's `ratio >= floor` loop (also always False
        for NaN), get RESOLVED into tier 'D' instead of UNRESOLVED. A
        non-finite rate is not a rate the platform actually knows (R7) —
        same principle as a blank currency."""
        for bad_rate in (float('nan'), float('inf'), float('-inf')):
            self._assert_unusable(currency='CLP', fx_rate_to_usd=bad_rate)

    def test_non_finite_amount_never_classifies(self):
        """Same defect class, the other input _num() feeds: a non-finite
        AMOUNT must not classify either, even with a perfectly valid
        currency and period (isolating this from the currency/period
        checks entirely)."""
        for bad_amount in (float('nan'), float('inf'), float('-inf')):
            o = S.IncomeObservation(amount=bad_amount, currency='USD',
                                    period=S.PERIOD_ANNUAL, source=S.DECLARED_CONFIRMED)
            self.assertIsNone(o.annual_usd, f'amount={bad_amount!r} produced annual_usd')
            c = S.classify([o], self.ctx, {})
            self.assertFalse(c.resolved, f'amount={bad_amount!r} produced a resolved tier')
            self.assertIsNone(c.tier)

    def test_non_finite_fx_cannot_be_laundered_via_a_huge_amount(self):
        """Mirrors test_blank_currency_cannot_be_laundered_via_a_huge_amount:
        a NaN FX rate must not resolve even when attached to a large,
        otherwise-plausible declaration."""
        o = S.IncomeObservation(amount=1_000_000, currency='CLP', period=S.PERIOD_ANNUAL,
                                source=S.DECLARED_CONFIRMED, fx_rate_to_usd=float('nan'))
        self.assertIsNone(o.annual_usd)
        c = S.classify([o], self.ctx, {})
        self.assertFalse(c.resolved)
        self.assertIsNone(c.tier)
        self.assertNotEqual(c.tier, 'D', 'NaN must be UNRESOLVED, not silently tier D')

    def test_blank_currency_cannot_be_laundered_via_a_huge_amount(self):
        """However large the number, ambiguous currency stays ambiguous —
        this is the exact shape of the B1 defect: a $20,000,000 declaration
        with a blank currency column must never resolve to tier A."""
        o = S.IncomeObservation(amount=20_000_000, currency='',
                                period=S.PERIOD_MONTHLY, source=S.DECLARED_CONFIRMED)
        self.assertIsNone(o.annual_usd)
        c = S.classify([o], self.ctx, {})
        self.assertFalse(c.resolved)
        self.assertNotEqual(c.tier, 'A')
        self.assertIsNone(c.tier)

    def test_currency_is_never_invented_from_country(self):
        """No country-implied-currency rule exists in this codebase (and this
        module must not invent one): a Chilean user with a blank currency
        does not get CLP assumed for them."""
        o = S.IncomeObservation(amount=20_000_000, currency='', country='CL',
                                period=S.PERIOD_ANNUAL, source=S.DECLARED_CONFIRMED)
        self.assertIsNone(o.annual_usd)


# ═══════════════════════════════════════════════════════════════════════
# 6c. Medium finding E — a malformed/unrecognised period never classifies
# ═══════════════════════════════════════════════════════════════════════

class TestMalformedPeriodNeverClassifies(unittest.TestCase):

    def setUp(self):
        self.ctx = ctx(median=20000)

    def _assert_unusable(self, period):
        o = S.IncomeObservation(amount=100000, currency='USD', period=period,
                                source=S.DECLARED_CONFIRMED)
        self.assertIsNone(o.annual_usd, f'period {period!r} produced annual_usd')
        self.assertFalse(S.classify([o], self.ctx, {}).resolved)

    def test_quincenal_is_not_recognised_and_does_not_default_to_annual(self):
        self._assert_unusable('quincenal')

    def test_arbitrary_garbage_period(self):
        for garbage in ('fortnightly', 'biweekly', 'xyz', '???', '12', ''):
            self._assert_unusable(garbage)

    def test_none_period_never_classifies(self):
        self._assert_unusable(None)

    def test_omitted_period_never_classifies(self):
        """Mirrors the currency case: there is no implicit default period.
        A caller who means annual must say 'annual'."""
        o = S.IncomeObservation(amount=100000, currency='USD', source=S.DECLARED_CONFIRMED)
        self.assertIsNone(o.annual_usd)

    def test_normalize_period_itself_never_guesses(self):
        for garbage in ('quincenal', 'fortnightly', None, '', '   ', 'xyz'):
            self.assertEqual(S.normalize_period(garbage), '',
                             f'normalize_period({garbage!r}) should be unrecognised')

    def test_accepted_periods_are_the_only_ones_that_resolve(self):
        for period in S.ACCEPTED_PERIODS:
            o = S.IncomeObservation(amount=100000, currency='USD', period=period,
                                    source=S.DECLARED_CONFIRMED)
            self.assertIsNotNone(o.annual_usd, f'accepted period {period!r} failed to resolve')


# ═══════════════════════════════════════════════════════════════════════
# 7. Age + occupation progression — adjusts INCOME, never the tier
# ═══════════════════════════════════════════════════════════════════════

class TestAgeOccupationProgression(unittest.TestCase):

    def test_engineer_24_earns_less_than_engineer_30(self):
        """JC's example, expressed where it belongs: on income."""
        base = 60000
        y = S.estimate_occupation_income(base, age=24)
        o = S.estimate_occupation_income(base, age=30)
        self.assertLess(y, o)
        self.assertAlmostEqual(y, base * 0.55)
        self.assertAlmostEqual(o, base * 0.87)

    def test_curve_peaks_in_mid_career(self):
        base = 50000
        vals = {a: S.estimate_occupation_income(base, age=a)
                for a in (22, 27, 32, 40, 50, 60, 70)}
        self.assertEqual(max(vals, key=vals.get), 50)

    def test_unknown_age_does_not_move_the_estimate(self):
        self.assertEqual(S.age_income_multiplier(None), 1.0)
        self.assertEqual(S.estimate_occupation_income(50000, age=None), 50000)

    def test_company_size_scales_pay_not_tier(self):
        self.assertAlmostEqual(S.estimate_occupation_income(50000, company_size_rank=5),
                               50000 * 1.22)
        self.assertAlmostEqual(S.estimate_occupation_income(50000, company_size_rank=1),
                               50000 * 0.72)

    def test_unknown_company_size_is_neutral_not_small(self):
        """R7: UNKNOWN must not be silently treated as a small employer."""
        self.assertEqual(S.company_size_income_multiplier(0), 1.0)
        self.assertEqual(S.company_size_income_multiplier(None), 1.0)
        self.assertEqual(S.estimate_occupation_income(50000, company_size_rank=0), 50000)

    def test_age_alone_cannot_change_a_tier_when_income_is_known(self):
        """The historical defect: age moved the TIER directly."""
        c = ctx(median=20000)
        obs = [income(25000, source=S.DECLARED_CONFIRMED)]
        base = S.classify(obs, c, {})
        for age in (22, 30, 40, 50, 65):
            with self.subTest(age=age):
                same = S.classify(obs, c, {'age': age})
                self.assertEqual(same.tier, base.tier)
                self.assertEqual(same.tier, 'C')


class TestTierIndexingIsSingleScheme(unittest.TestCase):
    """The off-by-one that promoted C->A and D->B on age alone came from
    mixing a 1-based rank with a 0-indexed ladder. One scheme now."""

    def test_index_is_zero_based_and_ordered(self):
        self.assertEqual([S.tier_index(t) for t in ('D', 'C', 'B', 'A')], [0, 1, 2, 3])

    def test_round_trip(self):
        for t in ('A', 'B', 'C', 'D'):
            self.assertEqual(S.tier_from_index(S.tier_index(t)), t)

    def test_unknown_tier_is_minus_one_not_zero(self):
        """Returning 0 would silently mean 'D'."""
        for bad in ('', None, 'Z', '1', 'unknown'):
            with self.subTest(value=bad):
                self.assertEqual(S.tier_index(bad), -1)

    def test_legacy_triples_collapse_by_first_letter(self):
        """Matches CHANGE-002's eligibility.norm_tier, which already treats
        'AAA'/'BBC' as A/B. Two different collapsings would be a bug."""
        import eligibility as E
        for legacy in ('AAA', 'AAB', 'BBB', 'BBC', 'CCC', 'DDD'):
            with self.subTest(legacy=legacy):
                self.assertEqual(S.tier_from_index(S.tier_index(legacy)),
                                 E.norm_tier(legacy))

    def test_tier_from_index_clamps(self):
        self.assertEqual(S.tier_from_index(-5), 'D')
        self.assertEqual(S.tier_from_index(99), 'A')

    def test_normalization_accepts_lowercase_and_whitespace(self):
        self.assertEqual(S.tier_index(' a '), 3)
        self.assertEqual(S.tier_index('b'), 2)


# ═══════════════════════════════════════════════════════════════════════
# 8. Missing data  (R7)
# ═══════════════════════════════════════════════════════════════════════

class TestMissingData(unittest.TestCase):

    def test_missing_income_is_unresolved(self):
        c = S.classify([], ctx(median=20000), {})
        self.assertEqual(c.verdict, S.UNRESOLVED)
        self.assertIsNone(c.tier)
        self.assertIn('income', c.unresolved_reason)

    def test_missing_ppp_is_unresolved(self):
        c = S.classify([income(30000)], ctx(ppp=None), {})
        self.assertEqual(c.verdict, S.UNRESOLVED)
        self.assertIsNone(c.tier)

    def test_unresolved_never_produces_a_tier_that_could_be_matched(self):
        """CHANGE-002 treats an empty tier as UNKNOWN, which denies."""
        for c in (S.classify([], ctx(median=20000), {}),
                  S.classify([income(30000)], ctx(ppp=None), {}),
                  S.classify([income(30000)], ctx(ppp=17000, source='nominal'), {})):
            self.assertFalse(c.resolved)
            self.assertIsNone(c.tier)

    def test_refused_ppp_reason_is_surfaced(self):
        c = S.classify([income(30000)], ctx(ppp=17000, source='nominal'), {})
        self.assertIn('refused', c.unresolved_reason.lower())


# ═══════════════════════════════════════════════════════════════════════
# 9. Derived vs measured country median  (R3 auditability)
# ═══════════════════════════════════════════════════════════════════════

class TestCountryMedianProvenance(unittest.TestCase):

    def test_measured_median_is_used_and_flagged_not_derived(self):
        c = ctx(ppp=29500, median=18000)
        self.assertEqual(c.median_personal_income_usd, 18000)
        self.assertFalse(c.derived_median)

    def test_derived_median_uses_the_documented_ratio(self):
        c = ctx(ppp=30000, median=None)
        self.assertTrue(c.derived_median)
        self.assertEqual(c.median_personal_income_usd,
                         30000 * S.DERIVED_MEDIAN_FROM_PPP_RATIO)

    def test_classification_discloses_a_derived_median(self):
        c = S.classify([income(30000)], ctx(ppp=30000), {})
        self.assertTrue(any('DERIVED' in r for r in c.reasons))
        self.assertTrue(c.as_dict()['derived_country_median'])

    def test_ppp_and_tier_stay_separable(self):
        """R3: the two numbers must remain independently queryable, which is
        what makes 'PPP >= 5000 AND tier = A' expressible."""
        c = ctx(ppp=29500, median=20000)
        cl = S.classify([income(80000)], c, {})
        self.assertEqual(cl.tier, 'A')
        self.assertEqual(cl.context.ppp_per_capita_usd, 29500)


# ═══════════════════════════════════════════════════════════════════════
# 10. Privacy  (income is sensitive)
# ═══════════════════════════════════════════════════════════════════════

class TestPrivacy(unittest.TestCase):

    def test_as_dict_never_carries_the_income_figure(self):
        c = S.classify([income(123456, source=S.DECLARED_CONFIRMED)],
                       ctx(median=20000), {})
        d = c.as_dict()
        self.assertNotIn('income_used', d)
        self.assertNotIn('123456', str(d))

    def test_redact_strips_every_sensitive_field(self):
        payload = {'tier': 'A', 'income_used': 99999, 'household_income_usd': 5,
                   'estimated_income_usd': 7, 'annual_usd': 3}
        out = S.redact_for_api(payload)
        self.assertEqual(out, {'tier': 'A'})

    def test_redact_can_opt_in(self):
        out = S.redact_for_api({'tier': 'A', 'income_used': 5}, include_income=True)
        self.assertEqual(out['income_used'], 5)

    def test_log_summary_carries_no_income(self):
        c = S.classify([income(987654, source=S.DECLARED_CONFIRMED)],
                       ctx(median=20000), {})
        line = S.safe_log_summary(c)
        self.assertNotIn('987654', line)
        self.assertIn('tier=', line)


# ═══════════════════════════════════════════════════════════════════════
# 10b. Threshold policy — provisional, versioned, never silently final
# ═══════════════════════════════════════════════════════════════════════
#
# JC has NOT approved TIER_BANDS (3.0x/1.5x/0.7x). These tests do not assert
# those specific numbers are correct — that would be exactly the mistake the
# remediation warns against. They assert the numbers are (a) defined exactly
# once, (b) travel with an explicit "not yet approved" flag everywhere a
# classification or impact report leaves this module, and (c) are tied to a
# policy_version that would need to change if the bands ever do.

class TestThresholdPolicyTransparency(unittest.TestCase):

    def test_thresholds_are_marked_not_yet_approved(self):
        self.assertFalse(S.THRESHOLDS_APPROVED_BY_BUSINESS,
                         'flip this only after an actual business approval, never '
                         'as a drive-by edit')

    def test_classification_carries_the_approval_flag(self):
        c = S.classify([income(50000, source=S.DECLARED_CONFIRMED)], ctx(median=20000), {})
        self.assertTrue(c.resolved)
        d = c.as_dict()
        self.assertIn('thresholds_approved_by_business', d)
        self.assertEqual(d['thresholds_approved_by_business'], S.THRESHOLDS_APPROVED_BY_BUSINESS)

    def test_impact_report_surfaces_the_bands_and_the_approval_flag(self):
        c = S.classify([income(50000, source=S.DECLARED_CONFIRMED)], ctx(median=20000), {})
        report = S.impact_report([(1, '', c)])
        self.assertIn('tier_bands', report)
        self.assertEqual(report['tier_bands'], list(S.TIER_BANDS))
        self.assertIn('thresholds_approved_by_business', report)
        self.assertFalse(report['thresholds_approved_by_business'])
        self.assertIn('PROVISIONAL', report['note'])

    def test_tier_bands_defined_exactly_once(self):
        """No second table of cut points anywhere in this module — the one
        in TIER_BANDS is the only source tier_from_income reads."""
        import inspect
        src = inspect.getsource(S)
        # TIER_BANDS itself, plus its one consumer in tier_from_income.
        self.assertEqual(src.count('for tier, floor in TIER_BANDS'), 1)

    def test_policy_version_is_a_single_versioned_string(self):
        """Every Classification and every impact_report trace to the SAME
        policy_version — changing the bands without bumping this would be
        the actual defect this test guards against."""
        c1 = S.classify([income(50000, source=S.DECLARED_CONFIRMED)], ctx(median=20000), {})
        c2 = S.classify([income(5000, source=S.DECLARED_CONFIRMED)], ctx(median=20000), {})
        self.assertEqual(c1.policy_version, c2.policy_version, S.POLICY_VERSION)
        report = S.impact_report([(1, '', c1), (2, '', c2)])
        self.assertEqual(report['policy_version'], S.POLICY_VERSION)


# ═══════════════════════════════════════════════════════════════════════
# 11. Reference data governance  (propose -> validate -> approve)
# ═══════════════════════════════════════════════════════════════════════

def proposal(**kw):
    base = dict(country='CL', field='ppp_per_capita_usd', new_value=29500,
                source='world_bank_ny_gnp_pcap_pp_cd', data_year=2023)
    base.update(kw)
    return S.ReferenceProposal(**base)


class TestReferenceGovernance(unittest.TestCase):

    def test_valid_proposal_is_pending_not_applied(self):
        p = S.validate_proposal(proposal(), current_year=2026)
        self.assertEqual(p.status, S.PROPOSAL_PENDING)
        self.assertEqual(p.validation_errors, [])

    def test_nominal_source_is_REJECTED(self):
        p = S.validate_proposal(proposal(source='nominal_gdp_per_capita'),
                                current_year=2026)
        self.assertEqual(p.status, S.PROPOSAL_REJECTED)
        self.assertTrue(any('NOMINAL' in e for e in p.validation_errors))

    def test_missing_year_is_rejected(self):
        p = S.validate_proposal(proposal(data_year=None), current_year=2026)
        self.assertEqual(p.status, S.PROPOSAL_REJECTED)
        self.assertTrue(any('data_year' in e for e in p.validation_errors))

    def test_future_year_is_rejected(self):
        p = S.validate_proposal(proposal(data_year=2030), current_year=2026)
        self.assertEqual(p.status, S.PROPOSAL_REJECTED)

    def test_stale_data_is_flagged_for_review(self):
        p = S.validate_proposal(proposal(data_year=2015), current_year=2026)
        self.assertTrue(p.requires_review)
        self.assertTrue(any('stale' in r for r in p.review_reasons))

    def test_large_jump_requires_review(self):
        """A 2-3x jump is the signature of a unit error / nominal series."""
        p = S.validate_proposal(proposal(new_value=29500), current_year=2026)
        p.old_value = 10000
        p = S.validate_proposal(p, current_year=2026)
        self.assertTrue(p.requires_review)

    def test_small_drift_does_not_require_review(self):
        p = proposal(new_value=30000)
        p.old_value = 29500
        S.validate_proposal(p, current_year=2026)
        self.assertFalse(p.requires_review)

    def test_rejected_proposal_cannot_be_approved(self):
        p = S.validate_proposal(proposal(source='nominal'), current_year=2026)
        S.approve_proposal(p, approver='jc')
        self.assertEqual(p.status, S.PROPOSAL_REJECTED)

    def test_review_flagged_proposal_needs_force(self):
        p = proposal(new_value=29500); p.old_value = 10000
        S.validate_proposal(p, current_year=2026)
        S.approve_proposal(p, approver='jc')
        self.assertEqual(p.status, S.PROPOSAL_PENDING)
        S.approve_proposal(p, approver='jc', force=True)
        self.assertEqual(p.status, S.PROPOSAL_APPROVED)

    def test_approval_requires_an_approver(self):
        p = S.validate_proposal(proposal(), current_year=2026)
        S.approve_proposal(p, approver='')
        self.assertEqual(p.status, S.PROPOSAL_PENDING)

    def test_clean_proposal_approves(self):
        p = S.validate_proposal(proposal(), current_year=2026)
        S.approve_proposal(p, approver='jc')
        self.assertEqual(p.status, S.PROPOSAL_APPROVED)

    def test_bad_country_code_rejected(self):
        self.assertEqual(
            S.validate_proposal(proposal(country='CHILE'), current_year=2026).status,
            S.PROPOSAL_REJECTED)


# ═══════════════════════════════════════════════════════════════════════
# 12. Impact diagnostic (dry run)
# ═══════════════════════════════════════════════════════════════════════

class TestImpactDiagnostic(unittest.TestCase):

    def setUp(self):
        self.c = ctx(median=20000)

    def _cls(self, amount):
        return S.classify([income(amount, source=S.DECLARED_CONFIRMED)], self.c, {})

    def test_counts_and_transitions(self):
        rows = [
            (1, 'C', self._cls(25000)),                      # unchanged
            (2, 'A', self._cls(25000)),                      # changed A->C
            (3, '',  self._cls(70000)),                      # newly resolved
            (4, 'B', S.classify([], self.c, {})),            # became unresolved
            (5, '',  S.classify([], self.c, {})),            # still unresolved
        ]
        r = S.impact_report(rows)
        self.assertEqual(r['evaluable'], 5)
        self.assertEqual(r['counts']['unchanged'], 1)
        self.assertEqual(r['counts']['changed'], 1)
        self.assertEqual(r['counts']['newly_resolved'], 1)
        self.assertEqual(r['counts']['became_unresolved'], 1)
        self.assertEqual(r['counts']['still_unresolved'], 1)
        self.assertEqual(r['would_change'], 1)
        self.assertIn('A->C', r['transitions'])
        self.assertEqual(r['changed_user_ids_sample'], [2])

    def test_report_states_it_wrote_nothing(self):
        r = S.impact_report([(1, 'C', self._cls(25000))])
        self.assertIn('DRY RUN', r['note'])

    def test_unresolved_reasons_are_aggregated(self):
        rows = [(i, 'B', S.classify([], self.c, {})) for i in range(3)]
        r = S.impact_report(rows)
        self.assertEqual(sum(r['unresolved_reasons'].values()), 3)

    def test_report_carries_no_income_figures(self):
        rows = [(1, 'C', self._cls(987654))]
        self.assertNotIn('987654', str(S.impact_report(rows)))

    def test_diff_classification_cases(self):
        self.assertEqual(S.diff_classification('C', self._cls(25000)), 'unchanged')
        self.assertEqual(S.diff_classification('A', self._cls(25000)), 'changed')
        self.assertEqual(S.diff_classification('', self._cls(25000)), 'newly_resolved')
        self.assertEqual(
            S.diff_classification('B', S.classify([], self.c, {})), 'became_unresolved')
        self.assertEqual(
            S.diff_classification('', S.classify([], self.c, {})), 'still_unresolved')


# ═══════════════════════════════════════════════════════════════════════
# 13. Adversarial
# ═══════════════════════════════════════════════════════════════════════

class TestAdversarial(unittest.TestCase):

    def setUp(self):
        self.c = ctx(median=20000)

    def test_cannot_reach_tier_A_by_stacking_profile_attributes(self):
        """Every professional lever at maximum, income still says D."""
        c = S.classify([income(5000, source=S.DECLARED_CONFIRMED)], self.c,
                       {'occupation': 'medico', 'cargo': 'ceo',
                        'company_size_rank': 5, 'age': 55})
        self.assertEqual(c.tier, 'D')

    def test_cannot_launder_household_income_into_the_tier(self):
        obs = [S.IncomeObservation(amount=200000, source=S.DECLARED_CONFIRMED,
                                   note='household'),
               income(8000, source=S.DECLARED)]
        self.assertEqual(S.classify(obs, self.c, {}).tier, 'D')

    def test_cannot_inflate_by_declaring_a_huge_range_top(self):
        """The midpoint governs, not the top of the band.

        10,000-60,000 against a 20,000 median: the top alone would be exactly
        3.00x (tier A), while the midpoint 35,000 is 1.75x (tier B). If the
        reading ever changed to top-of-band this flips to A.
        """
        c = S.classify([income(10000, amount_max=60000)], self.c, {})
        self.assertEqual(c.tier, 'B')
        # …and the top of that same band, read alone, WOULD have been A.
        self.assertEqual(S.tier_from_income(60000, self.c)[0], 'A')

    def test_cannot_use_an_unpriced_currency_to_smuggle_a_number(self):
        c = S.classify([income(999999999, currency='XYZ')], self.c, {})
        self.assertFalse(c.resolved)

    def test_stale_estimate_does_not_beat_fresh_declaration(self):
        obs = [income(90000, source=S.ESTIMATED_OCCUPATION, as_of=date(2026, 8, 1)),
               income(12000, source=S.DECLARED_CONFIRMED, as_of=date(2020, 1, 1))]
        self.assertEqual(S.classify(obs, self.c, {}).income_source,
                         S.DECLARED_CONFIRMED)

    def test_zero_income_is_D_not_unresolved(self):
        c = S.classify([income(0, source=S.DECLARED_CONFIRMED)], self.c, {})
        self.assertTrue(c.resolved)
        self.assertEqual(c.tier, 'D')

    def test_policy_version_is_recorded_on_every_classification(self):
        c = S.classify([income(30000)], self.c, {})
        self.assertEqual(c.policy_version, S.POLICY_VERSION)
        self.assertIn('change-003', c.policy_version)


if __name__ == '__main__':
    unittest.main()
