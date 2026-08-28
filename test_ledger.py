"""
test_ledger.py — CHANGE-001 canonical ledger test suite.

Stdlib only (unittest). Run:

    python3 -m unittest test_ledger -v

Dependency-free like eligibility.py/socioeconomic.py, so these run without
fastapi/sqlalchemy/postgres. Endpoint wiring, concurrency and real-DB
behavior are covered by test_ledger_wiring.py.
"""

import unittest

import ledger as L


# ═══════════════════════════════════════════════════════════════════════
# 1. Every transaction balances (R2)
# ═══════════════════════════════════════════════════════════════════════

class TestDoubleEntryBalances(unittest.TestCase):

    def test_funding_balances_to_zero(self):
        p = L.build_funding(L.REAL, 1, 100)
        self.assertTrue(p.ok)
        self.assertAlmostEqual(sum(e.amount for e in p.entries), 0.0, places=6)

    def test_reservation_balances_to_zero(self):
        p = L.build_reservation(L.REAL, 1, 5, 40)
        self.assertAlmostEqual(sum(e.amount for e in p.entries), 0.0, places=6)

    def test_spend_balances_to_zero(self):
        p = L.build_spend(L.REAL, 5, 12.34)
        self.assertAlmostEqual(sum(e.amount for e in p.entries), 0.0, places=6)

    def test_release_balances_to_zero(self):
        p = L.build_release(L.REAL, 1, 5, 40)
        self.assertAlmostEqual(sum(e.amount for e in p.entries), 0.0, places=6)

    def test_demo_grant_balances_to_zero(self):
        p = L.build_demo_grant(1, already_issued_lifetime=0)
        self.assertAlmostEqual(sum(e.amount for e in p.entries), 0.0, places=6)

    def test_every_builder_produces_exactly_two_entries(self):
        for p in (L.build_funding(L.REAL, 1, 10), L.build_reservation(L.REAL, 1, 5, 10),
                 L.build_spend(L.REAL, 5, 10), L.build_release(L.REAL, 1, 5, 10)):
            self.assertEqual(len(p.entries), 2)

    def test_validate_entries_rejects_a_single_leg(self):
        self.assertEqual(L.validate_entries([L.Entry(L.USER_REAL, 1, 10)]), 'too_few_entries')

    def test_validate_entries_rejects_unbalanced(self):
        e = [L.Entry(L.USER_REAL, 1, -10), L.Entry(L.CAMPAIGN_REAL_RESERVED, 5, 9)]
        self.assertEqual(L.validate_entries(e), 'unbalanced')

    def test_validate_entries_accepts_a_balanced_pair(self):
        e = [L.Entry(L.USER_REAL, 1, -10), L.Entry(L.CAMPAIGN_REAL_RESERVED, 5, 10)]
        self.assertEqual(L.validate_entries(e), '')

    def test_validate_entries_rejects_zero_amount_leg(self):
        e = [L.Entry(L.USER_REAL, 1, 0), L.Entry(L.CAMPAIGN_REAL_RESERVED, 5, 0)]
        self.assertEqual(L.validate_entries(e), 'zero_amount_entry')

    def test_epsilon_tolerates_subcent_float_noise_but_not_real_drift(self):
        e = [L.Entry(L.USER_REAL, 1, -10.0000001), L.Entry(L.CAMPAIGN_REAL_RESERVED, 5, 10.0)]
        self.assertEqual(L.validate_entries(e), '')
        e2 = [L.Entry(L.USER_REAL, 1, -10.10), L.Entry(L.CAMPAIGN_REAL_RESERVED, 5, 10.0)]
        self.assertEqual(L.validate_entries(e2), 'unbalanced')


# ═══════════════════════════════════════════════════════════════════════
# 2. REAL and DEMO cannot mix (R3)
# ═══════════════════════════════════════════════════════════════════════

class TestRealDemoSeparation(unittest.TestCase):

    def test_account_kind_value_class_is_fixed_and_exhaustive(self):
        for kind in (L.ORIGIN_REAL, L.USER_REAL, L.CAMPAIGN_REAL_RESERVED, L.SPEND_REAL):
            self.assertEqual(L.value_class_of(kind), L.REAL)
        for kind in (L.ORIGIN_DEMO, L.USER_DEMO, L.CAMPAIGN_DEMO_RESERVED, L.SPEND_DEMO):
            self.assertEqual(L.value_class_of(kind), L.DEMO)

    def test_a_hand_built_mixed_transaction_is_rejected(self):
        mixed = [L.Entry(L.USER_REAL, 1, -10), L.Entry(L.USER_DEMO, 1, 10)]
        self.assertEqual(L.validate_entries(mixed), 'mixed_value_class')

    def test_no_builder_can_be_coerced_into_mixing_classes(self):
        """Every builder derives BOTH legs' account kinds from the SAME
        `value_class` argument — there is no parameter combination that
        produces a mixed transaction."""
        for value_class in (L.REAL, L.DEMO):
            for p in (L.build_funding(value_class, 1, 10),
                     L.build_reservation(value_class, 1, 5, 10),
                     L.build_spend(value_class, 5, 10),
                     L.build_release(value_class, 1, 5, 10)):
                classes = {e.value_class for e in p.entries}
                self.assertEqual(classes, {value_class})

    def test_demo_reservation_cannot_target_a_real_campaign_account(self):
        """Structural: campaign_account_kind(DEMO) can never equal
        campaign_account_kind(REAL)."""
        self.assertNotEqual(L.campaign_account_kind(L.REAL), L.campaign_account_kind(L.DEMO))
        self.assertNotEqual(L.user_account_kind(L.REAL), L.user_account_kind(L.DEMO))
        self.assertNotEqual(L.origin_account_kind(L.REAL), L.origin_account_kind(L.DEMO))
        self.assertNotEqual(L.spend_account_kind(L.REAL), L.spend_account_kind(L.DEMO))

    def test_release_cannot_cross_classes(self):
        """F: REAL -> REAL, DEMO -> DEMO, never cross. Both legs of a
        release derive from the same value_class parameter, so this is
        impossible to construct, not merely disallowed."""
        p = L.build_release(L.DEMO, 1, 5, 10)
        self.assertEqual({e.value_class for e in p.entries}, {L.DEMO})

    def test_expected_value_class_guard_catches_a_caller_mistake(self):
        e = [L.Entry(L.USER_DEMO, 1, -10), L.Entry(L.CAMPAIGN_DEMO_RESERVED, 5, 10)]
        self.assertEqual(L.validate_entries(e, expected_value_class=L.REAL),
                         'value_class_mismatch')

    def test_invalid_value_class_string_is_rejected(self):
        p = L.build_funding('FAKE', 1, 10)
        self.assertFalse(p.ok)
        self.assertEqual(p.reason, 'invalid_value_class')


# ═══════════════════════════════════════════════════════════════════════
# 3. Demo grant policy (G)
# ═══════════════════════════════════════════════════════════════════════

class TestDemoGrantPolicy(unittest.TestCase):

    def test_demo_grant_is_usable_for_testing(self):
        p = L.build_demo_grant(1, already_issued_lifetime=0)
        self.assertTrue(p.ok)
        self.assertEqual(p.value_class, L.DEMO)
        self.assertAlmostEqual(
            [e for e in p.entries if e.account_kind == L.USER_DEMO][0].amount,
            L.DEMO_GRANT_AMOUNT)

    def test_demo_grant_never_creates_real_funds(self):
        p = L.build_demo_grant(1, already_issued_lifetime=0)
        for e in p.entries:
            self.assertEqual(e.value_class, L.DEMO)
            self.assertNotEqual(e.value_class, L.REAL)

    def test_repeated_demo_requests_cannot_mint_unlimited_value(self):
        issued = 0.0
        grants = 0
        while True:
            p = L.build_demo_grant(1, already_issued_lifetime=issued)
            if not p.ok:
                break
            issued += L.DEMO_GRANT_AMOUNT
            grants += 1
            if grants > 1000:
                self.fail('demo grant policy allowed unbounded minting')
        self.assertLessEqual(issued, L.DEMO_GRANT_MAX_LIFETIME)
        self.assertGreater(grants, 0)

    def test_grant_exactly_at_the_cap_boundary(self):
        just_under = L.DEMO_GRANT_MAX_LIFETIME - L.DEMO_GRANT_AMOUNT
        self.assertTrue(L.demo_grant_allowed(just_under))
        self.assertFalse(L.demo_grant_allowed(just_under + 0.01))

    def test_idempotency_key_is_deterministic_per_user_per_day(self):
        k1 = L.demo_grant_idempotency_key(7, '2026-08-27')
        k2 = L.demo_grant_idempotency_key(7, '2026-08-27')
        k3 = L.demo_grant_idempotency_key(7, '2026-08-28')
        k4 = L.demo_grant_idempotency_key(8, '2026-08-27')
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertNotEqual(k1, k4)


# ═══════════════════════════════════════════════════════════════════════
# 4. Amount / invalid-input handling
# ═══════════════════════════════════════════════════════════════════════

class TestAmountValidation(unittest.TestCase):

    def test_round_amount_rounds_to_the_cent(self):
        self.assertEqual(L.round_amount(10.126), 10.13)
        self.assertEqual(L.round_amount('10.5'), 10.5)

    def test_round_amount_rejects_garbage(self):
        for bad in ('abc', None, object(), float('nan'), float('inf')):
            self.assertIsNone(L.round_amount(bad))

    def test_zero_and_negative_amounts_are_invalid_for_every_builder(self):
        for amount in (0, -1, -0.01):
            self.assertFalse(L.build_funding(L.REAL, 1, amount).ok)
            self.assertFalse(L.build_reservation(L.REAL, 1, 5, amount).ok)
            self.assertFalse(L.build_spend(L.REAL, 5, amount).ok)
            self.assertFalse(L.build_release(L.REAL, 1, 5, amount).ok)

    def test_non_numeric_amount_is_invalid(self):
        p = L.build_funding(L.REAL, 1, 'lots')
        self.assertFalse(p.ok)
        self.assertEqual(p.reason, 'invalid_amount')
        self.assertEqual(p.entries, [])


# ═══════════════════════════════════════════════════════════════════════
# 5. Reconciliation is read-only and reports, never resolves (H, R6)
# ═══════════════════════════════════════════════════════════════════════

class TestReconciliation(unittest.TestCase):

    def test_matching_balances_report_ok(self):
        r = L.reconcile_user_balance(100.00, 100.00)
        self.assertEqual(r['status'], L.RECON_OK)

    def test_diverging_balances_are_reported_not_resolved(self):
        r = L.reconcile_user_balance(150.00, 100.00)
        self.assertEqual(r['status'], L.RECON_MISMATCH)
        self.assertEqual(r['legacy'], 150.00)
        self.assertEqual(r['ledger'], 100.00)
        # crucially: the function returns BOTH numbers, decides neither.

    def test_missing_ledger_account_is_flagged_distinctly(self):
        r = L.reconcile_user_balance(50.0, None)
        self.assertEqual(r['status'], L.RECON_NO_LEDGER_ACCOUNT)

    def test_ambiguous_legacy_value_is_flagged_distinctly(self):
        r = L.reconcile_user_balance(None, 50.0)
        self.assertEqual(r['status'], L.RECON_AMBIGUOUS_LEGACY)

    def test_campaign_spend_reconciliation_flags_preexisting_overspend(self):
        r = L.reconcile_campaign_spend(budget_clp=100000, spent_clp=150000,
                                       impression_log_sum_clp=150000,
                                       ledger_spend_credits=None, usd_to_clp=950)
        self.assertEqual(r['status'], L.RECON_MISMATCH)
        self.assertTrue(any('EXCEEDS' in f for f in r['findings']))

    def test_campaign_spend_reconciliation_flags_spent_clp_drift(self):
        r = L.reconcile_campaign_spend(budget_clp=1000000, spent_clp=20000,
                                       impression_log_sum_clp=5000,
                                       ledger_spend_credits=None, usd_to_clp=950)
        self.assertEqual(r['status'], L.RECON_MISMATCH)

    def test_campaign_spend_reconciliation_clean_case(self):
        r = L.reconcile_campaign_spend(budget_clp=1000000, spent_clp=5000,
                                       impression_log_sum_clp=5000,
                                       ledger_spend_credits=None, usd_to_clp=950)
        self.assertEqual(r['status'], L.RECON_OK)
        self.assertEqual(r['findings'], [])

    def test_reconciliation_functions_never_mutate_their_inputs(self):
        """There is no way for a pure function to mutate an immutable
        float, but this documents the contract explicitly: these
        functions return a NEW dict and take no database handle."""
        import inspect
        for fn in (L.reconcile_user_balance, L.reconcile_campaign_spend):
            sig = inspect.signature(fn)
            for name in sig.parameters:
                self.assertNotIn('db', name.lower())
                self.assertNotIn('session', name.lower())


if __name__ == '__main__':
    unittest.main()
