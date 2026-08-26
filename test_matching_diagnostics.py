"""
test_matching_diagnostics.py — CHANGE-002 Phase 2.

Covers the two read-only diagnostics JC required before deploy:

  * the PPP/PPA audit (is any country's market thermometer holding a NOMINAL
    figure where PPP is required?)
  * the legacy personal-income audit (which rows carry an ambiguous unit?)

The governing constraint in both cases is NEGATIVE: the diagnostic must
identify rows needing review WITHOUT guessing a unit and WITHOUT writing
anything. Most of the assertions below exist to prove the guessing does not
happen.

    python3 -m unittest test_matching_diagnostics -v
"""

import unittest

import matching_diagnostics as D
import eligibility as E


# ═══════════════════════════════════════════════════════════════════════
# 1. PPP / PPA audit
# ═══════════════════════════════════════════════════════════════════════

class TestPPPAudit(unittest.TestCase):

    def test_value_matching_reference_is_ok(self):
        r = D.classify_ppp_row('CL', 29000.0, 29500.0)
        self.assertEqual(r['status'], D.PPP_OK)

    def test_normal_vintage_drift_is_not_flagged(self):
        """World Bank vintages move a few percent year to year; that must not
        read as a unit error."""
        for stored in (29500 * 0.75, 29500 * 0.9, 29500 * 1.0, 29500 * 1.25):
            r = D.classify_ppp_row('CL', stored, 29500.0)
            self.assertEqual(r['status'], D.PPP_OK, f'{stored}: {r}')

    def test_nominal_figure_is_flagged_for_review(self):
        """Chile: nominal ~17k vs PPP ~29.5k. That gap is the signature of a
        nominal value loaded into the PPP column."""
        r = D.classify_ppp_row('CL', 17000.0, 29500.0)
        self.assertEqual(r['status'], D.PPP_SUSPECTED_NOMINAL)
        self.assertIn('review', r['note'].lower())

    def test_emerging_market_nominal_is_flagged(self):
        # India: nominal ~2.5k vs PPP ~9.2k (~3.7x).
        r = D.classify_ppp_row('IN', 2500.0, 9200.0)
        self.assertEqual(r['status'], D.PPP_SUSPECTED_NOMINAL)
        # Nigeria: nominal ~1.6k vs PPP ~5.7k.
        r = D.classify_ppp_row('NG', 1600.0, 5700.0)
        self.assertEqual(r['status'], D.PPP_SUSPECTED_NOMINAL)

    def test_missing_stored_value_falls_back_not_fails(self):
        r = D.classify_ppp_row('CL', None, 29500.0)
        self.assertEqual(r['status'], D.PPP_MISSING)
        self.assertIn('reference', r['note'])

    def test_no_stored_and_no_reference_denies(self):
        r = D.classify_ppp_row('ZZ', None, None)
        self.assertEqual(r['status'], D.PPP_NO_REFERENCE)
        self.assertIn('DENIES', r['note'])

    def test_unreferenced_country_is_not_silently_declared_ok(self):
        r = D.classify_ppp_row('ZZ', 12345.0, None)
        self.assertEqual(r['status'], D.PPP_NO_REFERENCE)
        self.assertNotEqual(r['status'], D.PPP_OK)

    def test_non_numeric_does_not_raise(self):
        for bad in ('abc', object()):
            r = D.classify_ppp_row('CL', bad, 29500.0)
            self.assertEqual(r['status'], D.PPP_NO_REFERENCE)

    def test_zero_reference_does_not_raise(self):
        r = D.classify_ppp_row('CL', 100.0, 0.0)
        self.assertEqual(r['status'], D.PPP_NO_REFERENCE)

    def test_audit_aggregates_and_lists_review_rows(self):
        stored = {'CL': 17000.0, 'JP': 48000.0, 'NG': None}
        reference = {'CL': 29500.0, 'JP': 47000.0, 'NG': 5700.0, 'default': 10000.0}
        rep = D.ppp_audit(stored, reference)
        self.assertEqual(rep['total_countries'], 3)
        self.assertEqual([r['iso2'] for r in rep['requires_review']], ['CL'])
        self.assertEqual(rep['counts'].get(D.PPP_SUSPECTED_NOMINAL), 1)

    def test_audit_ignores_the_reference_default_sentinel(self):
        rep = D.ppp_audit({}, {'CL': 29500.0, 'default': 10000.0})
        self.assertNotIn('default', [r['iso2'] for r in rep['rows']])

    def test_audit_is_read_only(self):
        """The audit must not mutate the dicts it is handed."""
        stored = {'CL': 17000.0}
        reference = {'CL': 29500.0}
        D.ppp_audit(stored, reference)
        self.assertEqual(stored, {'CL': 17000.0})
        self.assertEqual(reference, {'CL': 29500.0})


class TestPPPProvenance(unittest.TestCase):
    """JC: THE MARKET THERMOMETER IS PPP/PPA PER CAPITA."""

    def test_provenance_constants_name_the_ppp_indicator(self):
        self.assertIn('NY.GNP.PCAP.PP.CD', E.PPP_SOURCE_DB)
        self.assertTrue(E.PPP_SOURCE_REFERENCE)

    def test_reference_table_is_the_in_repo_ppp_dataset(self):
        from marketer_table_v2 import GNI_PER_CAPITA
        self.assertIn('default', GNI_PER_CAPITA)
        # Sanity: these are PPP magnitudes, not nominal ones.
        self.assertGreater(GNI_PER_CAPITA.get('CL', 0), 20000)


# ═══════════════════════════════════════════════════════════════════════
# 2. Legacy personal income audit
# ═══════════════════════════════════════════════════════════════════════

class TestLegacyIncomeAudit(unittest.TestCase):

    def test_schema_defaults_mean_not_targeted(self):
        r = D.classify_income_row(1, 0.0, 9999.0)
        self.assertEqual(r['status'], D.INCOME_NOT_TARGETED)

    def test_nulls_mean_not_targeted(self):
        r = D.classify_income_row(1, None, None)
        self.assertEqual(r['status'], D.INCOME_NOT_TARGETED)

    def test_values_above_index_ceiling_are_provably_currency(self):
        r = D.classify_income_row(2, 30000.0, 120000.0)
        self.assertEqual(r['status'], D.INCOME_USD_DOMAIN)

    def test_ambiguous_band_is_flagged_never_interpreted(self):
        r = D.classify_income_row(3, 500.0, 2000.0)
        self.assertEqual(r['status'], D.INCOME_INDEX_DOMAIN)
        self.assertIn('NOT provable', r['evidence'])
        self.assertIn('REQUIRES REVIEW', r['action'])

    def test_diagnostic_never_names_a_unit_as_the_answer(self):
        """The report must not RESOLVE the ambiguity by asserting a unit.

        Note it is fine — and useful — for the text to *describe* the
        competing candidate units ("the schema calls this an index while the
        only live comparison was against annual USD"). What must never appear
        is a verdict picking one. So the assertions below target resolution
        verbs, anchored on word boundaries.
        """
        import re
        r = D.classify_income_row(3, 500.0, 2000.0)
        blob = (r['evidence'] + ' ' + r['action']).lower()

        resolution_claims = [
            r'\bthe (?:original )?unit is\b(?! not\b)',
            r'\bvalue is (?:an index|annual usd|monthly|ppp)\b',
            r'\binterpreted as\b',
            r'\bassumed to be\b',
            r'\btreated as\b',
            r'\bwe (?:conclude|assume|infer)\b',
        ]
        for pattern in resolution_claims:
            self.assertIsNone(re.search(pattern, blob),
                              f'diagnostic resolves the unit via {pattern!r}: {blob}')

        # And it must positively state that the unit is NOT provable.
        self.assertRegex(blob, r'\bnot provable\b')

    def test_only_lower_bound_set_is_still_classified(self):
        r = D.classify_income_row(4, 800.0, 9999.0)
        self.assertEqual(r['status'], D.INCOME_INDEX_DOMAIN)

    def test_only_upper_bound_set_is_still_classified(self):
        r = D.classify_income_row(5, 0.0, 3000.0)
        self.assertEqual(r['status'], D.INCOME_INDEX_DOMAIN)

    def test_upper_bound_above_ceiling_alone_is_currency(self):
        r = D.classify_income_row(6, 0.0, 80000.0)
        self.assertEqual(r['status'], D.INCOME_USD_DOMAIN)

    def test_non_numeric_bounds_do_not_raise(self):
        r = D.classify_income_row(7, 'abc', None)
        self.assertIn(r['status'], (D.INCOME_NOT_TARGETED, D.INCOME_INDEX_DOMAIN))

    def test_audit_aggregates_and_lists_review_rows(self):
        rows = [
            ('campaign', 1, 'default', 0.0, 9999.0),
            ('campaign', 2, 'usd band', 30000.0, 120000.0),
            ('campaign', 3, 'ambiguous', 500.0, 2000.0),
            ('debate', 4, 'ambiguous too', 100.0, 900.0),
        ]
        rep = D.income_audit(rows)
        self.assertEqual(rep['total_rows'], 4)
        self.assertEqual(sorted(r['id'] for r in rep['requires_review']), [3, 4])
        self.assertEqual(rep['counts'].get(D.INCOME_NOT_TARGETED), 1)
        self.assertEqual(rep['counts'].get(D.INCOME_USD_DOMAIN), 1)

    def test_audit_preserves_kind_and_label(self):
        rep = D.income_audit([('debate', 9, 'Consulta X', 500.0, 2000.0)])
        row = rep['rows'][0]
        self.assertEqual(row['kind'], 'debate')
        self.assertEqual(row['label'], 'Consulta X')


class TestDiagnosticAgreesWithEvaluator(unittest.TestCase):
    """The diagnostic exists to explain the evaluator, so the two must not
    disagree about which rows are undecidable."""

    def test_ambiguous_band_denies_in_the_evaluator(self):
        flagged = D.classify_income_row(1, 500.0, 2000.0)
        self.assertEqual(flagged['status'], D.INCOME_INDEX_DOMAIN)

        reason = E._check_income_band(60000.0, 500.0, 2000.0)
        self.assertEqual(reason.outcome, E.UNKNOWN)

    def test_provable_currency_band_is_decided_normally(self):
        provable = D.classify_income_row(2, 30000.0, 120000.0)
        self.assertEqual(provable['status'], D.INCOME_USD_DOMAIN)

        self.assertEqual(E._check_income_band(60000.0, 30000.0, 120000.0).outcome, E.PASS)
        self.assertEqual(E._check_income_band(10000.0, 30000.0, 120000.0).outcome, E.FAIL)

    def test_ceilings_are_the_same_constant_in_both_modules(self):
        self.assertEqual(float(D.INDEX_DOMAIN_CEILING),
                         float(E.LEGACY_INCOME_INDEX_CEILING))


if __name__ == '__main__':
    unittest.main()
