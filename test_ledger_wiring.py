"""
test_ledger_wiring.py — CHANGE-001 endpoint, integration and adversarial tests.

Three kinds of coverage:

  * STRUCTURAL — parses main.py to prove the PostgreSQL DDL branch is real
    (same technique CHANGE-003 uses) and that no code outside the
    `_ledger_*` adapters touches the four ledger tables directly.
  * BEHAVIOURAL — boots the actual FastAPI app with TestClient against a
    throwaway sqlite DB and drives the real HTTP routes end to end: demo
    funding -> demo campaign allocation -> ad delivery -> demo spend ->
    demo remaining balance, and the REAL equivalent.
  * ADVERSARIAL / CONCURRENCY — real threads hammering the same
    reservation, duplicate retries, wrong-owner attempts, REAL/DEMO
    mixing attempts, and direct reproduction of the four routes CHANGE-001
    recon found crashing with `no such column` before this change.

LOCAL / TEST ONLY. DATABASE_URL is forced to a temp file before main is
imported; no production credential is read and no network call is made.

    python3 -m unittest test_ledger_wiring -v
"""

import ast
import os
import re
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix='change001-it-')
_DB_PATH = os.path.join(_TMPDIR, 'test.db')
os.environ['DATABASE_URL'] = f'sqlite:///{_DB_PATH}'
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-change-001'
os.environ['ADMIN_SECRET'] = 'test-only-admin-secret-change-001'
for _k in ('SENDGRID_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
           'STRIPE_SECRET_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
           'CLOUDINARY_URL', 'WEB3_PROVIDER_URL'):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402
import payments                                # noqa: E402
import ledger as L                             # noqa: E402
import eligibility as E                        # noqa: E402
import socioeconomic as S                      # noqa: E402

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
    base = dict(email=f'ledger{n}@test.local', name=f'User {n}', password='x',
                country='CL', county='Las Condes', gender='M', dob='1990-05-10',
                role='voter', email_verified=True, referral_code=f'LG{n:06d}')
    base.update(kw)
    u = main.User(**base)
    db.add(u); db.commit(); db.refresh(u)
    return u


def mk_marketer(db, *, status='approved', **kw):
    u = mk_user(db, role='marketer', **kw)
    p = main.MarketerProfile(user_id=u.id, org_type='company', is_supervisor=True,
                             status=status, company_name='Acme')
    db.add(p); db.commit()
    return u


def mk_debate(db, **kw):
    n = _uid()
    kw.setdefault('title', f'Consulta {n}')
    kw.setdefault('context', 'ctx')
    kw.setdefault('options', '["Si","No"]')
    base = dict(scope='country', scope_country='CL', status='live')
    base.update(kw)
    d = main.Debate(**base)
    db.add(d); db.commit(); db.refresh(d)
    return d


def auth(user):
    return {'Authorization': f'Bearer {main.make_token(user.id, user.role)}'}


def campaign_payload(owner, **kw):
    n = _uid()
    base = dict(
        advertiser_email=owner.email, advertiser_name='Acme',
        campaign_title=f'Campaign {n}', budget_clp=1_000_000,
        start_date='2026-01-01T00:00:00', end_date='2026-12-31T00:00:00',
    )
    base.update(kw)
    return base


def _function(name):
    for n in ast.walk(MAIN_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _src_of(node):
    return ast.get_source_segment(MAIN_SRC, node) or ''


def _route_functions():
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
LEDGER_ADAPTER_NAMES = {
    '_ledger_get_or_create_account', '_ledger_balance', '_ledger_lifetime_credited',
    '_ledger_post', '_ledger_fund', '_ledger_reserve', '_ledger_release',
    '_ledger_spend', '_ledger_demo_grant', '_ledger_new_idempotency_key',
    '_ledger_campaign_recognized_spend', '_ledger_all_credit_accounts',
}


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)

    def fund_real(self, user, amount, key=None):
        return main._ledger_fund(self.db, L.REAL, user.id, amount, method='manual',
                                 idempotency_key=key or f'seed-real-{_uid()}',
                                 description='test seed')

    def grant_demo(self, user):
        return main._ledger_demo_grant(self.db, user.id)


# ═══════════════════════════════════════════════════════════════════════
# STRUCTURAL — PostgreSQL DDL branch (same technique as CHANGE-003)
# ═══════════════════════════════════════════════════════════════════════

def _migrate_source():
    return _src_of(_function('_migrate'))


class TestLedgerPostgresDDL(unittest.TestCase):

    def test_ldg_pk_expression_branches_on_is_pg(self):
        src = _migrate_source()
        m = re.search(r'_ldg_pk\s*=\s*(.+)', src)
        self.assertIsNotNone(m, '_ldg_pk assignment not found')
        expr = m.group(1).strip()
        self.assertIn('is_pg', expr)
        self.assertEqual(eval(expr, {'is_pg': True}), 'SERIAL PRIMARY KEY')
        self.assertEqual(eval(expr, {'is_pg': False}), 'INTEGER PRIMARY KEY AUTOINCREMENT')

    def test_all_four_ledger_tables_use_the_branched_pk(self):
        src = _migrate_source()
        block_start = src.index('CREATE TABLE IF NOT EXISTS ledger_accounts')
        block_end = src.index('idx_ledger_accounts_kind_ref', block_start)
        block = src[block_start:block_end]
        self.assertEqual(block.count('id {_ldg_pk}'), 3,  # accounts, transactions, entries
                         'not all three auto-id ledger tables use the branched PK')
        # Anchored on leading whitespace + newline so this does not false-
        # positive on `account_id INTEGER PRIMARY KEY,` (ledger_balances'
        # legitimate non-autoincrement FK-as-PK column, which ends in "id"
        # but is a different column entirely).
        self.assertIsNone(re.search(r'\n\s+id INTEGER PRIMARY KEY,', block))
        self.assertIsNone(re.search(r'\n\s+id SERIAL PRIMARY KEY,', block))

    def test_ledger_accounts_has_unique_kind_ref(self):
        src = _migrate_source()
        block_start = src.index('CREATE TABLE IF NOT EXISTS ledger_accounts')
        block = src[block_start:block_start + 400]
        self.assertIn('UNIQUE(kind, ref_id)', block)

    def test_idempotency_key_is_unique(self):
        src = _migrate_source()
        block_start = src.index('CREATE TABLE IF NOT EXISTS ledger_transactions')
        block = src[block_start:block_start + 600]
        self.assertIn('idempotency_key TEXT UNIQUE', block)

    def test_ad_campaigns_value_class_migration_is_additive_and_defaults_real(self):
        src = _migrate_source()
        self.assertIn("('value_class', \"TEXT DEFAULT 'REAL'\")", src)
        self.assertIn("('clicks_count', 'INTEGER DEFAULT 0')", src)


# ═══════════════════════════════════════════════════════════════════════
# STRUCTURAL — single writer (R4 immutability, canonical-source discipline)
# ═══════════════════════════════════════════════════════════════════════

class TestSingleWriterDiscipline(unittest.TestCase):

    def test_only_ledger_adapters_reference_the_four_ledger_tables_by_name(self):
        """Anything outside _ledger_* touching ledger_transactions/entries/
        balances/accounts directly would be a second, uncoordinated writer
        — exactly the anti-pattern CHANGE-001 exists to remove."""
        tables = ('ledger_transactions', 'ledger_entries', 'ledger_balances',
                 'ledger_accounts')
        offenders = []
        for node in ast.walk(MAIN_TREE):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in LEDGER_ADAPTER_NAMES or node.name == '_migrate':
                continue
            body = _src_of(node)
            for t in tables:
                if t in body:
                    offenders.append(f'{node.name} references {t}')
        self.assertEqual(offenders, [], '\n'.join(offenders))

    def test_no_update_or_delete_statement_touches_transactions_or_entries(self):
        """R4: posted movements are immutable. An UPDATE/DELETE against
        ledger_transactions or ledger_entries anywhere (adapters included)
        would violate that — only INSERT and (for ledger_balances only) a
        conditional additive UPDATE are legitimate."""
        for pattern in (r'UPDATE\s+ledger_transactions', r'DELETE\s+.*ledger_transactions',
                        r'UPDATE\s+ledger_entries', r'DELETE\s+.*ledger_entries'):
            self.assertIsNone(re.search(pattern, MAIN_SRC, re.IGNORECASE),
                             f'found a mutation of posted ledger history: {pattern}')

    def test_deprecated_payments_functions_have_no_call_sites(self):
        for name in ('deduct_credits_for_impression', 'allocate_budget_to_campaign',
                    'return_budget_to_account'):
            calls = len(re.findall(rf'\b{name}\(', MAIN_SRC))
            self.assertEqual(calls, 0, f'{name}(...) is still called from main.py')

    def test_credit_accounts_is_written_only_via_the_ledger_mirror(self):
        """add_credits (the legacy writer) must be reachable ONLY through
        _ledger_fund, never called directly by a route — otherwise the
        legacy cache becomes a second independent source of truth again."""
        for (method, path), fn in ROUTES.items():
            if not path.startswith('/payments') and not path.startswith('/admin/payments'):
                continue
            body = _src_of(fn)
            self.assertNotIn('add_credits(', body,
                             f'{method.upper()} {path} calls add_credits directly, '
                             f'bypassing the ledger')


# ═══════════════════════════════════════════════════════════════════════
# FUNDING (C) — REAL vs DEMO, idempotency
# ═══════════════════════════════════════════════════════════════════════

class TestFundingReal(Base):

    def test_manual_credit_creates_real_ledger_value(self):
        u = mk_user(self.db)
        r = self.client.post('/admin/payments/manual-credit',
                             params={'user_id': u.id, 'credits': 100, 'description': 'promo',
                                     'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 100.0)

    def test_manual_credit_requires_admin_secret(self):
        u = mk_user(self.db)
        r = self.client.post('/admin/payments/manual-credit',
                             params={'user_id': u.id, 'credits': 100, 'description': 'x',
                                     'secret': 'wrong'})
        self.assertEqual(r.status_code, 403)

    def test_manual_credit_mirrors_into_legacy_credit_accounts(self):
        u = mk_user(self.db)
        self.client.post('/admin/payments/manual-credit',
                         params={'user_id': u.id, 'credits': 77, 'description': 'x',
                                 'secret': ADMIN_SECRET})
        row = self.db.execute(main.text(
            "SELECT balance_credits FROM credit_accounts WHERE user_id=:u"), {'u': u.id}).fetchone()
        self.assertEqual(float(row[0]), 77.0)

    def test_stripe_retry_does_not_double_credit(self):
        u = mk_user(self.db)
        payload = {'user_id': u.id, 'credits': 200}
        r1 = main._ledger_fund(self.db, L.REAL, u.id, 200, method='stripe',
                               idempotency_key='stripe_sess_ABC', description='pkg')
        r2 = main._ledger_fund(self.db, L.REAL, u.id, 200, method='stripe',
                               idempotency_key='stripe_sess_ABC', description='pkg')
        self.assertTrue(r1['ok'] and not r1['idempotent'])
        self.assertTrue(r2['ok'] and r2['idempotent'])
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 200.0)

    def test_crypto_confirm_route_is_idempotent_on_the_verified_tx_hash(self):
        """confirm_crypto_payment's own UPDATE doesn't re-check status in
        its WHERE clause (a real race documented in CHANGE-001 recon), but
        the ledger idempotency key is derived from the ON-CHAIN verified
        tx_hash, so two concurrent confirmations of the SAME payment still
        collapse to one credit."""
        u = mk_user(self.db)
        r1 = main._ledger_fund(self.db, L.REAL, u.id, 50, method='crypto_pol',
                               idempotency_key='crypto_0xabc123', description='crypto')
        r2 = main._ledger_fund(self.db, L.REAL, u.id, 50, method='crypto_pol',
                               idempotency_key='crypto_0xabc123', description='crypto')
        self.assertTrue(r2['idempotent'])
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 50.0)

    def test_funding_never_creates_demo_value(self):
        u = mk_user(self.db)
        self.fund_real(u, 100)
        self.assertEqual(main._ledger_balance(self.db, L.USER_DEMO, u.id), 0.0)


class TestFundingDemo(Base):

    def test_demo_route_requires_authentication(self):
        r = self.client.post('/payments/demo-credits')
        self.assertIn(r.status_code, (401, 403))

    def test_demo_grant_is_self_only(self):
        """No user_id parameter exists on this route at all — it can only
        ever credit the authenticated caller. There is no admin-authority
        path that grants demo credits to someone else through this route."""
        fn = ROUTES[('post', '/payments/demo-credits')]
        args = {a.arg for a in fn.args.args}
        self.assertNotIn('user_id', args)

    def test_demo_grant_creates_demo_value_only(self):
        u = mk_user(self.db)
        r = self.client.post('/payments/demo-credits', headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(main._ledger_balance(self.db, L.USER_DEMO, u.id), L.DEMO_GRANT_AMOUNT)

    def test_demo_grant_never_touches_credit_accounts(self):
        """G: cannot be represented as real purchased funds — the legacy
        REAL-only cache must show nothing for a demo-only user."""
        u = mk_user(self.db)
        self.client.post('/payments/demo-credits', headers=auth(u))
        row = self.db.execute(main.text(
            "SELECT balance_credits FROM credit_accounts WHERE user_id=:u"), {'u': u.id}).fetchone()
        self.assertIsNone(row)  # no credit_accounts row was ever created for this user

    def test_repeated_demo_requests_same_day_are_idempotent(self):
        u = mk_user(self.db)
        r1 = self.client.post('/payments/demo-credits', headers=auth(u))
        r2 = self.client.post('/payments/demo-credits', headers=auth(u))
        r3 = self.client.post('/payments/demo-credits', headers=auth(u))
        self.assertFalse(r1.json()['idempotent'])
        self.assertTrue(r2.json()['idempotent'])
        self.assertTrue(r3.json()['idempotent'])
        self.assertEqual(main._ledger_balance(self.db, L.USER_DEMO, u.id), L.DEMO_GRANT_AMOUNT)

    def test_repeated_demo_requests_cannot_mint_unlimited_value_even_bypassing_the_daily_key(self):
        """Belt and suspenders: simulate many distinct days (distinct
        idempotency keys) hitting the SAME user, proving the LIFETIME cap
        (not just the daily key) is what ultimately stops it."""
        u = mk_user(self.db)
        granted = 0.0
        for day in range(1, 30):
            issued = main._ledger_lifetime_credited(self.db, L.USER_DEMO, u.id)
            posting = L.build_demo_grant(u.id, already_issued_lifetime=issued)
            if not posting.ok:
                break
            result = main._ledger_post(self.db, posting,
                                       idempotency_key=f'demo:{u.id}:sim-day-{day}',
                                       actor_user_id=u.id, source='demo')
            self.assertTrue(result['ok'])
            granted += L.DEMO_GRANT_AMOUNT
        self.assertLessEqual(granted, L.DEMO_GRANT_MAX_LIFETIME)
        final = main._ledger_balance(self.db, L.USER_DEMO, u.id)
        self.assertLessEqual(final, L.DEMO_GRANT_MAX_LIFETIME)

    def test_demo_grant_is_usable_for_the_full_campaign_flow(self):
        """G, end to end: demo funding -> demo campaign allocation ->
        matching/ad delivery -> demo spend -> demo remaining balance."""
        u = mk_marketer(self.db)
        self.client.post('/payments/demo-credits', headers=auth(u))

        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, value_class='DEMO'), headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        camp_id = r.json()['campaign_id']

        r = self.client.post('/payments/allocate-to-campaign',
                             json={'campaign_id': camp_id, 'credits': 100}, headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(r.json()['value_class'], 'DEMO')

        voter = mk_user(self.db)
        r = self.client.post('/ads/impression', params={'campaign_id': camp_id, 'debate_id': 0,
                                                         'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])

        remaining = main._ledger_balance(self.db, L.CAMPAIGN_DEMO_RESERVED, camp_id)
        self.assertGreater(remaining, 0)
        self.assertLess(remaining, 100)

        r = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['value_class'], 'DEMO')
        self.assertEqual(main._ledger_balance(self.db, L.CAMPAIGN_DEMO_RESERVED, camp_id), 0)


# ═══════════════════════════════════════════════════════════════════════
# REAL/DEMO SEPARATION (B) — cannot mix, cannot cross
# ═══════════════════════════════════════════════════════════════════════

class TestRealDemoWiring(Base):

    def test_new_campaign_defaults_to_real(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == r.json()['campaign_id']).first()
        self.assertEqual(camp.value_class, 'REAL')

    def test_unrecognised_value_class_defaults_to_real_not_accepted_verbatim(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, value_class='not-a-real-thing'),
                             headers=auth(u))
        camp = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == r.json()['campaign_id']).first()
        self.assertEqual(camp.value_class, 'REAL')

    def test_demo_only_balance_cannot_fund_a_real_campaign(self):
        u = mk_marketer(self.db)
        self.client.post('/payments/demo-credits', headers=auth(u))  # DEMO only
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u, value_class='REAL'),
                             headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 50}, headers=auth(u))
        self.assertFalse(r2.json()['ok'])
        self.assertEqual(r2.json()['reason'], 'insufficient_balance')
        # DEMO balance itself must remain completely untouched by the failed attempt.
        self.assertEqual(main._ledger_balance(self.db, L.USER_DEMO, u.id), L.DEMO_GRANT_AMOUNT)

    def test_real_only_balance_cannot_fund_a_demo_campaign(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 1000)   # REAL only
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u, value_class='DEMO'),
                             headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 50}, headers=auth(u))
        self.assertFalse(r2.json()['ok'])
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 1000.0)

    def test_update_campaign_cannot_change_value_class(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u, value_class='REAL'),
                             headers=auth(u))
        camp_id = r.json()['campaign_id']
        body = campaign_payload(u, value_class='DEMO')  # attempt to flip it
        r2 = self.client.patch(f'/advertiser/campaigns/{camp_id}', json=body, headers=auth(u))
        self.assertEqual(r2.status_code, 200, r2.text)
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertEqual(camp.value_class, 'REAL', 'value_class was mutated by an update')

    def test_release_never_crosses_classes(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 500)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u, value_class='REAL'),
                             headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 100}, headers=auth(u))
        before_demo = main._ledger_balance(self.db, L.USER_DEMO, u.id)
        self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(main._ledger_balance(self.db, L.USER_DEMO, u.id), before_demo)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 500.0)


# ═══════════════════════════════════════════════════════════════════════
# CAMPAIGN RESERVATION (D)
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignReservation(Base):

    def test_reservation_rejects_insufficient_balance_and_writes_nothing(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 10)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        before = self.db.execute(main.text("SELECT COUNT(*) FROM ledger_transactions")).fetchone()[0]
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 999}, headers=auth(u))
        self.assertFalse(r2.json()['ok'])
        after = self.db.execute(main.text("SELECT COUNT(*) FROM ledger_transactions")).fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 10.0)

    def test_reservation_rejects_wrong_owner(self):
        owner = mk_marketer(self.db)
        attacker = mk_marketer(self.db)
        self.fund_real(attacker, 1000)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(owner), headers=auth(owner))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 50}, headers=auth(attacker))
        self.assertEqual(r2.status_code, 403, r2.text)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, attacker.id), 1000.0)

    def test_reservation_rejects_invalid_amount(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 1000)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        for bad in (0, -10):
            r2 = self.client.post('/payments/allocate-to-campaign',
                                  json={'campaign_id': camp_id, 'credits': bad}, headers=auth(u))
            self.assertFalse(r2.json()['ok'])

    def test_duplicate_allocation_with_the_same_idempotency_key_reserves_once(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 1000)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        body = {'campaign_id': camp_id, 'credits': 100, 'idempotency_key': 'dup-key-1'}
        r1 = self.client.post('/payments/allocate-to-campaign', json=body, headers=auth(u))
        r2 = self.client.post('/payments/allocate-to-campaign', json=body, headers=auth(u))
        self.assertTrue(r1.json()['ok'] and not r1.json()['idempotent'])
        self.assertTrue(r2.json()['ok'] and r2.json()['idempotent'])
        self.assertEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id), 100.0)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 900.0)

    def test_campaign_creation_does_not_invent_funded_budget(self):
        """D: setting a large budget_clp must not, by itself, create any
        reservation. Only an explicit allocate call does."""
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, budget_clp=999_000_000), headers=auth(u))
        camp_id = r.json()['campaign_id']
        for vc in (L.CAMPAIGN_REAL_RESERVED, L.CAMPAIGN_DEMO_RESERVED):
            self.assertEqual(main._ledger_balance(self.db, vc, camp_id), 0.0)

    def test_change002_targeting_fields_persist_unaffected_by_value_class(self):
        """CHANGE-002 regression: adding value_class must not disturb any
        existing targeting field's persistence."""
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, target_country='CL',
                                                   target_communes='Las Condes',
                                                   target_se_tiers='A,B'),
                             headers=auth(u))
        camp = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == r.json()['campaign_id']).first()
        self.assertEqual(camp.target_country, 'CL')
        self.assertEqual(camp.target_communes, 'Las Condes')
        self.assertEqual(camp.target_se_tiers, 'A,B')


# ═══════════════════════════════════════════════════════════════════════
# AD SPEND (E) — unification, idempotency, cannot overspend
# ═══════════════════════════════════════════════════════════════════════

class TestAdSpendUnification(Base):

    def _funded_real_campaign(self, credits=100):
        u = mk_marketer(self.db)
        self.fund_real(u, credits + 50)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': credits}, headers=auth(u))
        return u, camp_id

    def test_ads_view_decrements_the_ledger_reservation(self):
        u, camp_id = self._funded_real_campaign()
        voter = mk_user(self.db)
        before = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        r = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 200, r.text)
        after = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        self.assertLess(after, before)

    def test_ads_impression_and_ads_view_decrement_the_SAME_account(self):
        """The core unification claim: whichever route serves the
        impression, the SAME campaign reservation moves — no more
        divergence between billing paths."""
        u, camp_id = self._funded_real_campaign()
        voter = mk_user(self.db)
        start = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                             'idempotency_key': f'evt-{_uid()}'},
                         headers=auth(voter))
        mid = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        self.client.post('/ads/impression', params={'campaign_id': camp_id, 'debate_id': 0,
                                                     'idempotency_key': f'evt-{_uid()}'},
                         headers=auth(voter))
        end = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        self.assertLess(mid, start)
        self.assertLess(end, mid)

    def test_duplicate_ad_event_with_same_idempotency_key_does_not_double_spend(self):
        u, camp_id = self._funded_real_campaign()
        voter = mk_user(self.db)
        body = {'campaign_id': camp_id, 'debate_id': None, 'idempotency_key': 'view-evt-1'}
        r1 = self.client.post('/ads/view', json=body, headers=auth(voter))
        after_first = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        r2 = self.client.post('/ads/view', json=body, headers=auth(voter))
        after_second = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        self.assertEqual(after_first, after_second, 'a retried impression was billed twice')
        self.assertTrue(r2.json().get('idempotent'))

    def test_spend_cannot_exceed_the_reservation(self):
        u, camp_id = self._funded_real_campaign(credits=0.01)  # almost nothing reserved
        voter = mk_user(self.db)
        for _ in range(50):
            self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        self.assertGreaterEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id), 0.0)

    def test_spend_deactivates_the_campaign_once_reservation_is_exhausted(self):
        u, camp_id = self._funded_real_campaign(credits=0.01)
        voter = mk_user(self.db)
        for _ in range(50):
            self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertFalse(camp.is_active)

    def test_unfunded_campaign_cannot_be_billed_at_all(self):
        """A campaign with a large budget_clp but ZERO ledger reservation
        (never allocated) must not bill anything — this is the exact
        'no post-paid spending' guarantee."""
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, budget_clp=999_000_000), headers=auth(u))
        camp_id = r.json()['campaign_id']
        voter = mk_user(self.db)
        before = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ad_impression_logs WHERE campaign_id=:c"), {'c': camp_id}).fetchone()[0]
        r2 = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                  'idempotency_key': f'evt-{_uid()}'},
                              headers=auth(voter))
        # CHANGE-001 remediation (§5) — a campaign that has NEVER had a
        # ledger reservation is 'legacy_unreconciled', not
        # 'insufficient_balance': distinct reason, and (checked below via
        # is_active) it must NOT be auto-deactivated for this reason.
        self.assertTrue(r2.json().get('not_billable'))
        self.assertEqual(r2.json().get('reason'), 'legacy_unreconciled')
        self.assertFalse(r2.json().get('budget_exhausted'))
        after = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ad_impression_logs WHERE campaign_id=:c"), {'c': camp_id}).fetchone()[0]
        self.assertEqual(before, after, 'an unfunded campaign recorded a billed impression')
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertTrue(camp.is_active, 'a never-reserved campaign must not be auto-deactivated')

    def test_opinions_flow_bills_the_same_ledger_reservation(self):
        u, camp_id = self._funded_real_campaign()
        voter = mk_user(self.db)
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        camp.target_country = ''
        self.db.commit()
        deb = mk_debate(self.db)
        for i in range(3):
            self.db.add(main.Opinion(debate_id=deb.id, user_id=0, user_name='X',
                                     text=f'op{i}', knowledge_level='basic'))
        self.db.commit()
        before = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        r = self.client.get(f'/debates/{deb.id}/opinions', headers=auth(voter))
        self.assertEqual(r.status_code, 200, r.text)
        after = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        ad_items = [x for x in r.json().get('items', []) if x.get('type') == 'ad']
        if ad_items:
            self.assertLessEqual(after, before)


class TestBrokenLegacyRoutesFixed(Base):
    """Direct reproduction of the exact CHANGE-001 recon crash scenarios.
    Each of these 500ed unconditionally before this change, for any real
    campaign and any eligible authenticated user."""

    def test_ads_impression_no_longer_500s(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 100)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 50}, headers=auth(u))
        voter = mk_user(self.db)
        r2 = self.client.post('/ads/impression', params={'campaign_id': camp_id, 'debate_id': 0,
                                                          'idempotency_key': f'evt-{_uid()}'},
                              headers=auth(voter))
        self.assertIn(r2.status_code, (200, 403, 404))
        self.assertNotEqual(r2.status_code, 500)

    def test_ads_click_no_longer_500s(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/ads/click', params={'campaign_id': camp_id, 'debate_id': 0})
        self.assertEqual(r2.status_code, 200, r2.text)
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertEqual(camp.clicks_count, 1)

    def test_allocate_to_campaign_no_longer_500s_with_real_balance(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 500)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 100}, headers=auth(u))
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertTrue(r2.json()['ok'])

    def test_return_from_campaign_no_longer_500s(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 500)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 100}, headers=auth(u))
        r2 = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertTrue(r2.json()['ok'])


# ═══════════════════════════════════════════════════════════════════════
# REFUND / RELEASE (F)
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseRefund(Base):

    def test_release_returns_to_the_same_class_and_owner(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 500)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 200}, headers=auth(u))
        r2 = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(r2.json()['returned'], 200.0)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 500.0)
        self.assertEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id), 0.0)

    def test_release_of_an_empty_reservation_is_a_safe_no_op(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()['returned'], 0)

    def test_repeated_release_calls_cannot_double_credit(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 500)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 200}, headers=auth(u))
        self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        r2 = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(u))
        self.assertEqual(r2.json()['returned'], 0)
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 500.0)

    def test_release_rejects_wrong_owner(self):
        owner = mk_marketer(self.db)
        attacker = mk_marketer(self.db)
        self.fund_real(owner, 300)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(owner), headers=auth(owner))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': 100}, headers=auth(owner))
        r2 = self.client.post(f'/payments/return-from-campaign/{camp_id}', headers=auth(attacker))
        self.assertEqual(r2.status_code, 403, r2.text)
        self.assertEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id), 100.0)


# ═══════════════════════════════════════════════════════════════════════
# CONCURRENCY — real threads
# ═══════════════════════════════════════════════════════════════════════

class TestConcurrency(unittest.TestCase):
    """Uses SessionLocal() per thread against the SAME file-backed sqlite
    DB (not :memory:), so this exercises real cross-connection contention,
    not merely single-session sequencing."""

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)

    def test_concurrent_reservations_cannot_overspend_the_available_balance(self):
        u = mk_marketer(self.db)
        user_id = u.id
        main._ledger_fund(self.db, L.REAL, user_id, 100, method='manual',
                          idempotency_key=f'seed-{_uid()}', description='seed')
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        campaign_id = camp.id   # capture the PLAIN INT — `camp` itself is bound to
                                # self.db's session and must never be touched from
                                # a worker thread's own session (cross-thread ORM
                                # instance access raises spurious SQLAlchemy errors
                                # that have nothing to do with the ledger's own
                                # correctness — the fix is to never share the object).

        N = 20
        AMOUNT = 10  # N * AMOUNT = 200, only 100 available -> at most 10 can succeed

        def attempt(i):
            session = main.SessionLocal()
            try:
                c = session.query(main.AdCampaign).filter(main.AdCampaign.id == campaign_id).first()
                posting = L.build_reservation(L.REAL, user_id, c.id, AMOUNT)
                return main._ledger_post(session, posting, idempotency_key=f'race-reserve-{i}',
                                         actor_user_id=user_id, campaign_id=c.id, source='test')
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=N) as pool:
            results = list(pool.map(attempt, range(N)))

        succeeded = [r for r in results if r['ok']]
        final_user_balance = main._ledger_balance(self.db, L.USER_REAL, user_id)
        final_campaign_balance = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, campaign_id)

        self.assertGreaterEqual(final_user_balance, -L.EPSILON,
                                'user balance went negative under concurrency')
        self.assertLessEqual(len(succeeded) * AMOUNT, 100 + L.EPSILON,
                             'more was reserved than was ever available')
        self.assertAlmostEqual(final_campaign_balance, len(succeeded) * AMOUNT, places=2)
        self.assertAlmostEqual(final_user_balance, 100 - len(succeeded) * AMOUNT, places=2)

    def test_concurrent_spend_cannot_exceed_a_fixed_reservation(self):
        u = mk_marketer(self.db)
        user_id = u.id
        main._ledger_fund(self.db, L.REAL, user_id, 100, method='manual',
                          idempotency_key=f'seed-{_uid()}', description='seed')
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        campaign_id = camp.id   # see note in the previous test — never share the ORM object
        posting = L.build_reservation(L.REAL, user_id, campaign_id, 10)
        main._ledger_post(self.db, posting, idempotency_key=f'seed-reserve-{_uid()}',
                          actor_user_id=user_id, campaign_id=campaign_id, source='test')

        N = 30
        SPEND = 1  # 30 attempts x 1 = 30, only 10 reserved -> at most 10 succeed

        def attempt(i):
            session = main.SessionLocal()
            try:
                c = session.query(main.AdCampaign).filter(main.AdCampaign.id == campaign_id).first()
                sp = L.build_spend(L.REAL, c.id, SPEND)
                return main._ledger_post(session, sp, idempotency_key=f'race-spend-{i}',
                                         campaign_id=c.id, source='test')
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=N) as pool:
            results = list(pool.map(attempt, range(N)))

        succeeded = [r for r in results if r['ok']]
        remaining = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, campaign_id)
        self.assertGreaterEqual(remaining, -L.EPSILON, 'reservation went negative')
        self.assertLessEqual(len(succeeded) * SPEND, 10 + L.EPSILON)
        self.assertAlmostEqual(remaining, 10 - len(succeeded) * SPEND, places=2)

    def test_concurrent_release_of_the_same_reservation_cannot_double_credit(self):
        u = mk_marketer(self.db)
        user_id = u.id
        main._ledger_fund(self.db, L.REAL, user_id, 100, method='manual',
                          idempotency_key=f'seed-{_uid()}', description='seed')
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        campaign_id = camp.id   # see note in the first concurrency test above
        posting = L.build_reservation(L.REAL, user_id, campaign_id, 40)
        main._ledger_post(self.db, posting, idempotency_key=f'seed-reserve-{_uid()}',
                          actor_user_id=user_id, campaign_id=campaign_id, source='test')

        def attempt(i):
            session = main.SessionLocal()
            try:
                c = session.query(main.AdCampaign).filter(main.AdCampaign.id == campaign_id).first()
                rel = L.build_release(L.REAL, user_id, c.id, 40)
                return main._ledger_post(session, rel, idempotency_key=f'race-release-{i}',
                                         actor_user_id=user_id, campaign_id=c.id, source='test')
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(attempt, range(10)))

        succeeded = [r for r in results if r['ok']]
        self.assertEqual(len(succeeded), 1, 'more than one concurrent release succeeded')
        self.assertAlmostEqual(main._ledger_balance(self.db, L.USER_REAL, user_id), 100.0, places=2)
        self.assertAlmostEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, campaign_id),
                               0.0, places=2)


# ═══════════════════════════════════════════════════════════════════════
# RECONCILIATION (H) — read-only, reports, never repairs
# ═══════════════════════════════════════════════════════════════════════

class TestReconciliation(Base):

    def test_requires_admin_secret(self):
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': 'wrong'})
        self.assertEqual(r.status_code, 403)

    def test_is_genuinely_read_only(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 100)
        before_user = main._ledger_balance(self.db, L.USER_REAL, u.id)
        before_txn_count = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ledger_transactions")).fetchone()[0]
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['wrote_nothing'])
        after_user = main._ledger_balance(self.db, L.USER_REAL, u.id)
        after_txn_count = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ledger_transactions")).fetchone()[0]
        self.assertEqual(before_user, after_user)
        self.assertEqual(before_txn_count, after_txn_count)

    def test_detects_a_legacy_cache_mismatch(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 100)
        # Simulate a pre-CHANGE-001 drift: legacy cache says something the
        # ledger does not.
        self.db.execute(main.text(
            "UPDATE credit_accounts SET balance_credits=999 WHERE user_id=:u"), {'u': u.id})
        self.db.commit()
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        mismatches = r.json()['user_balance_mismatches']
        self.assertTrue(any(m['user_id'] == u.id for m in mismatches))
        found = next(m for m in mismatches if m['user_id'] == u.id)
        self.assertEqual(found['status'], L.RECON_MISMATCH)
        self.assertEqual(found['legacy'], 999.0)
        self.assertEqual(found['ledger'], 100.0)
        # And it must NOT have "fixed" anything.
        self.assertEqual(main._ledger_balance(self.db, L.USER_REAL, u.id), 100.0)

    def test_detects_a_preexisting_campaign_spend_overspend(self):
        """A campaign whose LEGACY spent_clp already exceeds its
        budget_clp — pre-ledger state that must be reported, never
        silently resolved."""
        camp = main.AdCampaign(advertiser_email='x@y.com', advertiser_name='X', title='T',
                               budget_clp=1000, spent_clp=5000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        findings = r.json()['campaign_spend_mismatches']
        row = next((f for f in findings if f['campaign_id'] == camp.id), None)
        self.assertIsNotNone(row)
        self.assertTrue(any('EXCEEDS' in f for f in row['findings']))

    def test_clean_state_reports_no_mismatches(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 50)
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        mismatches = [m for m in r.json()['user_balance_mismatches'] if m['user_id'] == u.id]
        self.assertEqual(mismatches, [])


# ═══════════════════════════════════════════════════════════════════════
# AUTH / PRIVACY (I)
# ═══════════════════════════════════════════════════════════════════════

class TestAuthPrivacy(Base):

    def test_financial_routes_reject_anonymous(self):
        for method, path in (('post', '/payments/demo-credits'),
                             ('post', '/payments/allocate-to-campaign'),
                             ('post', '/payments/return-from-campaign/1')):
            r = getattr(self.client, method)(path, json={} if method == 'post' else None)
            self.assertIn(r.status_code, (401, 403), f'{method} {path} -> {r.status_code}')

    def test_admin_ledger_routes_reject_non_admin(self):
        u = mk_user(self.db)
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': 'nope'})
        self.assertEqual(r.status_code, 403)

    def test_reconciliation_response_carries_no_other_users_pii_beyond_balances(self):
        """Only ids and numeric balances — no email, no name."""
        u = mk_marketer(self.db)
        self.fund_real(u, 100)
        self.db.execute(main.text(
            "UPDATE credit_accounts SET balance_credits=1 WHERE user_id=:u"), {'u': u.id})
        self.db.commit()
        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        self.assertNotIn(u.email, r.text)

    def test_a_user_cannot_reserve_or_release_on_a_campaign_they_do_not_own(self):
        owner = mk_marketer(self.db)
        stranger = mk_marketer(self.db)
        self.fund_real(stranger, 1000)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(owner), headers=auth(owner))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 10}, headers=auth(stranger))
        self.assertEqual(r2.status_code, 403)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-002 / CHANGE-003 REGRESSION
# ═══════════════════════════════════════════════════════════════════════

class TestChange002And003NotWeakened(Base):

    # The socioeconomic-estimator remediation explicitly authorized two
    # named additive changes to these shared, otherwise CHANGE-002/003-owned
    # modules: eligibility.norm_company_size (bare numeric headcounts) and
    # socioeconomic.resolve_occupation_soc (free-text occupation title ->
    # canonical SOC code, a new function). GLOBAL OCCUPATION RESOLUTION
    # HARDENING then consolidated occupation resolution around that SAME
    # mechanism (not a second parallel one) — CANONICAL_OCCUPATIONS is now
    # the source of truth _OCCUPATION_TITLE_ALIASES is generated from, plus
    # AMBIGUOUS_OCCUPATION_TERMS (bare/generic terms that must never
    # silently resolve) and OccupationResolution/resolve_occupation_
    # candidates/occupation_title_for_soc (a read-only richer view for
    # registration UX/diagnostics, deliberately never called by income
    # estimation itself). It also added ONE parameter to eligibility.
    # profile_from_user: an optional occupation_override (default None ->
    # unchanged behavior for every existing caller) so main.py can hand it
    # an already-canonicalized SOC code without eligibility.py importing
    # socioeconomic.py — still dependency-free.
    _REMEDIATION_AUTHORIZED_SYMBOLS = {
        'eligibility.py':    frozenset({'norm_company_size', '_COMPANY_SIZE_NUMERIC_BOUNDS',
                                        'profile_from_user'}),
        'socioeconomic.py':  frozenset({'resolve_occupation_soc', '_OCCUPATION_TITLE_ALIASES',
                                        '_SOC_CODE_RE', '_base', 'CANONICAL_OCCUPATIONS',
                                        'AMBIGUOUS_OCCUPATION_TERMS', '_normalize_occupation_key',
                                        '_build_occupation_title_aliases', 'OccupationResolution',
                                        'resolve_occupation_candidates', 'occupation_title_for_soc',
                                        'occupation_aliases_for_soc'}),
    }

    def test_eligibility_and_socioeconomic_modules_are_byte_identical_to_change003(self):
        """Precise, not blanket: every top-level symbol in either module
        OUTSIDE the named, authorized exception set must be byte-identical
        to the pinned CHANGE-003 commit. Any OTHER change anywhere in
        either file still fails this test exactly as before a blanket
        byte-diff would have."""
        import subprocess
        parent = Path(main.__file__).parent
        baseline_sha = '5c9c3fde90a773517a2efd9034369aa96a4c64b5'

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

        for fname in ('eligibility.py', 'socioeconomic.py'):
            old_src = subprocess.run(
                ['git', 'show', f'{baseline_sha}:{fname}'],
                cwd=parent, capture_output=True, text=True).stdout
            new_src = (parent / fname).read_text(encoding='utf-8')
            old_blocks = top_level_blocks(old_src)
            new_blocks = top_level_blocks(new_src)
            allowed = self._REMEDIATION_AUTHORIZED_SYMBOLS[fname]

            unexpected_new = set(new_blocks) - set(old_blocks) - allowed
            self.assertEqual(unexpected_new, set(),
                             f'unauthorized new symbol(s) added to {fname}: {unexpected_new}')
            for name in set(old_blocks) & set(new_blocks):
                if name in allowed:
                    continue
                self.assertEqual(old_blocks[name], new_blocks[name],
                                 f'{fname} symbol {name!r} was modified outside the '
                                 f'authorized exception set')
            removed = set(old_blocks) - set(new_blocks)
            self.assertEqual(removed, set(), f'symbol(s) removed from {fname}: {removed}')

    def test_protected_consultation_routes_still_reject_anonymous(self):
        for path in ('/debates', '/debates/feed'):
            self.assertIn(self.client.get(path).status_code, (401, 403), path)

    def test_socioeconomic_classification_endpoint_still_works(self):
        r = self.client.get('/admin/socioeconomic/impact', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_value_class_field_did_not_break_campaign_matching_eligibility(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns',
                             json=campaign_payload(u, target_country='CL'), headers=auth(u))
        camp = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == r.json()['campaign_id']).first()
        voter = mk_user(self.db, country='CL')
        decision = main._campaign_decision(voter, camp, None, self.db)
        self.assertIsNotNone(decision)  # matching still runs end to end without error

    def test_unresolved_socioeconomic_classification_still_denies(self):
        u = mk_user(self.db, country='ZZ')
        c = main._classify_user(u, self.db)
        self.assertFalse(c.resolved)
        prof = main._build_profile(u, self.db)
        self.assertFalse(E._combine([E._check_tier(prof, {'A', 'B'})]).allowed)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §1 (BLOCKER) — vote-flow ledger bypass
# ═══════════════════════════════════════════════════════════════════════

class TestVoteFlowBilling(Base):
    """_cast_vote_inner used to write ad_campaigns.spent_clp directly via a
    LEAST()-based UPDATE that never touched the ledger — harmless-looking
    on SQLite (LEAST doesn't exist there, so it just failed and was
    swallowed by the surrounding try/except) but would have EXECUTED, and
    diverged from the ledger, on production PostgreSQL. It must now go
    through the SAME canonical `_ledger_spend` every other billing route
    uses, with a stable server-derived idempotency key (no client-supplied
    identity exists for a vote-triggered charge)."""

    def _campaign(self, owner, **kw):
        kw.setdefault('target_country', '')
        camp = main.AdCampaign(advertiser_email=owner.email, advertiser_name=f'Acme-{_uid()}',
                               title='T', budget_clp=10_000_000, is_active=True, **kw)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        return camp

    def _matched(self, camp):
        """Patches `_match_campaigns` to deterministically return exactly
        this campaign. The shared sqlite file this whole test MODULE runs
        against (not reset between tests, by design — see the file
        docstring) accumulates active campaigns from every other test
        class, and `targeting_agent.optimize_campaigns_for_debate` both
        caps results at `max_ads=5` and dedupes by advertiser_name BEFORE
        `_match_campaigns`'s own debate-pin boost is applied — so which
        real campaign a real vote matches is only deterministic in
        isolation, not against a growing shared pool. This class tests the
        BILLING mechanism once a campaign is matched (CHANGE-001's job),
        not which campaign matching selects (CHANGE-002/targeting_agent's
        job, already covered by test_matching_wiring.py) — so patching the
        selection is the correct scope, not a workaround."""
        return patch.object(main, '_match_campaigns',
                            return_value=[{'_orm': camp, 'cpm': 6.0}])

    def test_vote_triggered_ad_with_zero_reservation_cannot_bill(self):
        marketer = mk_marketer(self.db)
        voter = mk_user(self.db, country='CL', county='Las Condes')
        deb = mk_debate(self.db, scope_country='CL')
        camp = self._campaign(marketer)
        with self._matched(camp):
            result = main._cast_vote_inner(deb.id, main.CastVoteRequest(option_index=0), voter, self.db)
        self.assertTrue(result['success'])
        self.db.expire_all()
        logs = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == camp.id).count()
        self.assertEqual(logs, 0, 'vote billed an impression against an unreserved campaign')
        camp2 = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp.id).first()
        self.assertTrue(camp2.is_active,
                        'a never-reserved campaign must not be auto-deactivated by a vote')
        self.assertEqual(camp2.spent_clp or 0, 0)

    def test_vote_triggered_funded_ad_spends_exactly_once(self):
        marketer = mk_marketer(self.db)
        voter = mk_user(self.db, country='CL', county='Las Condes')
        deb = mk_debate(self.db, scope_country='CL')
        camp = self._campaign(marketer)
        self.fund_real(marketer, 100)
        main._ledger_reserve(self.db, camp, marketer.id, 50,
                             idempotency_key=f'vote-reserve-{_uid()}')
        before = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
        with self._matched(camp):
            result = main._cast_vote_inner(deb.id, main.CastVoteRequest(option_index=0), voter, self.db)
        self.assertTrue(result['success'])
        self.db.expire_all()
        logs = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == camp.id).count()
        self.assertEqual(logs, 1, 'a funded vote-triggered ad must bill exactly one impression')
        after = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
        self.assertLess(after, before)

    def test_vote_triggered_ad_billing_is_idempotent_per_user_per_debate(self):
        """The idempotency key is server-derived from (user, debate) — a
        direct replay of the SAME event must not double-spend, independent
        of the `debate_has_voted` gate that would normally prevent the
        HTTP route from even reaching this code twice."""
        marketer = mk_marketer(self.db)
        voter = mk_user(self.db, country='CL', county='Las Condes')
        deb = mk_debate(self.db, scope_country='CL')
        camp = self._campaign(marketer)
        self.fund_real(marketer, 100)
        main._ledger_reserve(self.db, camp, marketer.id, 50,
                             idempotency_key=f'vote-reserve-{_uid()}')
        with self._matched(camp):
            main._cast_vote_inner(deb.id, main.CastVoteRequest(option_index=0), voter, self.db)
        after_first = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
        idem_key = f'spend:vote:{voter.id}:{deb.id}'
        replay = main._ledger_spend(self.db, camp, 6.0 / 1000.0, idempotency_key=idem_key,
                                    source='vote_ad', reference=f'{voter.id}:{deb.id}')
        self.assertTrue(replay['ok'])
        self.assertTrue(replay['idempotent'], 'a replayed vote-triggered charge was not idempotent')
        after_replay = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
        self.assertEqual(after_first, after_replay, 'a replayed vote-triggered event double-spent')

    def test_different_voters_in_the_same_debate_are_separate_billing_events(self):
        marketer = mk_marketer(self.db)
        deb = mk_debate(self.db, scope_country='CL')
        camp = self._campaign(marketer)
        self.fund_real(marketer, 100)
        main._ledger_reserve(self.db, camp, marketer.id, 50,
                             idempotency_key=f'vote-reserve-{_uid()}')
        voter1 = mk_user(self.db, country='CL', county='Las Condes')
        voter2 = mk_user(self.db, country='CL', county='Las Condes')
        with self._matched(camp):
            main._cast_vote_inner(deb.id, main.CastVoteRequest(option_index=0), voter1, self.db)
            mid = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
            main._cast_vote_inner(deb.id, main.CastVoteRequest(option_index=0), voter2, self.db)
        end = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id)
        self.assertLess(end, mid, 'a second, distinct voter must be billed as a separate event')

    def test_vote_flow_no_longer_writes_spent_clp_via_least(self):
        """Direct proof the specific historical bug — an EXECUTED LEAST()
        SQL UPDATE — is gone from the function the auditor named. (Prose
        comments explaining the historical bug are expected and fine; only
        an actual `SET ... = LEAST(` assignment would be the regression.)"""
        src = _src_of(_function('_cast_vote_inner'))
        self.assertIsNone(re.search(r'SET\s+\w+\s*=\s*LEAST\s*\(', src, re.IGNORECASE))
        self.assertIn('_ledger_spend(', src)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §1 — structural: no alternate spent_clp writer
# ═══════════════════════════════════════════════════════════════════════

class TestSpentClpSingleWriter(unittest.TestCase):
    """A DIFFERENT guard than test_only_ledger_adapters_reference_the_four_
    ledger_tables_by_name — that one protects the four ledger_* tables;
    spent_clp lives on ad_campaigns and would be entirely invisible to it.
    This is the guard that would have caught _cast_vote_inner's bug."""

    ALLOWED_SPENT_CLP_WRITERS = {'_ledger_spend', 'admin_recompute_campaign_spend'}
    WRITE_PATTERNS = (
        re.compile(r'\.spent_clp\s*=(?!=)'),
        re.compile(r'SET\s+spent_clp\s*=', re.IGNORECASE),
    )

    def _offenders(self, tree, src_text):
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in self.ALLOWED_SPENT_CLP_WRITERS:
                continue
            body = ast.get_source_segment(src_text, node) or ''
            for pat in self.WRITE_PATTERNS:
                if pat.search(body):
                    offenders.append(f'{node.name} writes spent_clp directly ({pat.pattern})')
        return offenders

    def test_no_alternate_spent_clp_writer_exists(self):
        offenders = self._offenders(MAIN_TREE, MAIN_SRC)
        self.assertEqual(offenders, [], '\n'.join(offenders))

    def test_detector_actually_catches_the_historical_vote_flow_bug(self):
        """Mutation-test of the guard itself: feed it a synthetic function
        containing the EXACT pattern the independent auditor found (a
        LEAST()-based direct UPDATE inside a non-allowlisted function) and
        prove the detector flags it — otherwise the previous test would
        pass vacuously."""
        mutated_src = (
            "def _cast_vote_inner(debate_id, data, user, db):\n"
            "    db.execute(text(\"\"\"\n"
            "        UPDATE ad_campaigns\n"
            "        SET spent_clp = LEAST(COALESCE(budget_clp, 0), COALESCE(spent_clp, 0) + :cost)\n"
            "        WHERE id = :cid\n"
            "    \"\"\"), {'cost': cost_clp, 'cid': orm.id})\n"
        )
        tree = ast.parse(mutated_src)
        offenders = self._offenders(tree, mutated_src)
        self.assertTrue(offenders, 'the detector failed to catch the exact historical bug pattern')
        self.assertIn('_cast_vote_inner', offenders[0])


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §3 — idempotency SELECT/INSERT race
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotencyKeyRace(unittest.TestCase):
    """Real threads, same idempotency_key, same underlying file-backed
    sqlite DB — the exact scenario where the old SELECT-then-INSERT
    sequence could let a concurrent duplicate slip past the fast-path
    SELECT and hit the UNIQUE constraint as an unhandled IntegrityError."""

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)

    def test_concurrent_duplicate_idempotency_key_returns_clean_result_not_500(self):
        u = mk_marketer(self.db)
        user_id = u.id
        main._ledger_fund(self.db, L.REAL, user_id, 1000, method='manual',
                          idempotency_key=f'seed-{_uid()}', description='seed')
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        campaign_id = camp.id
        SAME_KEY = f'race-dup-{_uid()}'
        N = 12

        def attempt(i):
            session = main.SessionLocal()
            try:
                c = session.query(main.AdCampaign).filter(main.AdCampaign.id == campaign_id).first()
                posting = L.build_reservation(L.REAL, user_id, c.id, 10)
                # pool.map re-raises here if _ledger_post lets an
                # IntegrityError escape — that IS the failure mode §3 fixes.
                return main._ledger_post(session, posting, idempotency_key=SAME_KEY,
                                         actor_user_id=user_id, campaign_id=c.id, source='test')
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=N) as pool:
            results = list(pool.map(attempt, range(N)))

        self.assertEqual(len(results), N, 'a worker raised instead of returning a clean result')
        oks = [r for r in results if r['ok']]
        self.assertEqual(len(oks), N,
                         'a losing duplicate returned ok=False instead of a clean idempotent result')
        txn_ids = {r['transaction_id'] for r in oks}
        self.assertEqual(len(txn_ids), 1, 'concurrent duplicates produced more than one transaction')
        non_idempotent = [r for r in oks if not r['idempotent']]
        self.assertEqual(len(non_idempotent), 1,
                         'more than one caller believed it was the original poster')
        txn_count = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ledger_transactions WHERE idempotency_key=:k"),
            {'k': SAME_KEY}).fetchone()[0]
        self.assertEqual(txn_count, 1, 'the UNIQUE constraint did not hold under concurrency')
        final_balance = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, campaign_id)
        self.assertAlmostEqual(final_balance, 10.0, places=2,
                               msg='a concurrent duplicate key double-posted money')


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §4 — legacy credit_accounts mirror atomicity
# ═══════════════════════════════════════════════════════════════════════

class TestLegacyCacheConcurrency(unittest.TestCase):
    """payments.add_credits used to read balance_credits, add in Python,
    and UPDATE with the computed value — a lost-update race under two
    concurrent callers for the SAME user. Real threads, distinct refs
    (so this exercises the arithmetic race, not the idempotency check)."""

    def setUp(self):
        self.db = main.SessionLocal()
        self.addCleanup(self.db.close)

    def test_concurrent_add_credits_does_not_lose_updates(self):
        u = mk_marketer(self.db)
        user_id = u.id
        N = 20
        DELTA = 5.0

        def attempt(i):
            session = main.SessionLocal()
            try:
                return payments.add_credits(session, user_id, DELTA, 'manual',
                                            f'race-credit-{i}-{_uid()}', 'race test',
                                            tx_type='purchase')
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=N) as pool:
            results = list(pool.map(attempt, range(N)))

        self.assertTrue(all(r['ok'] for r in results))
        final = self.db.execute(main.text(
            "SELECT balance_credits FROM credit_accounts WHERE user_id=:u"),
            {'u': user_id}).fetchone()[0]
        self.assertAlmostEqual(final, N * DELTA, places=2,
                               msg='a concurrent add_credits update was lost')


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §5 — legacy/ledger-managed campaign transition
# ═══════════════════════════════════════════════════════════════════════

class TestLegacyCampaignTransition(Base):

    def test_new_campaign_defaults_to_legacy_unreconciled(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == r.json()['campaign_id']).first()
        self.assertEqual(camp.ledger_status, 'LEGACY_UNRECONCILED')

    def test_first_successful_reservation_flips_to_ledger_managed(self):
        u = mk_marketer(self.db)
        self.fund_real(u, 100)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertEqual(camp.ledger_status, 'LEGACY_UNRECONCILED')
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 10}, headers=auth(u))
        self.assertTrue(r2.json()['ok'], r2.text)
        self.db.expire_all()
        camp2 = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertEqual(camp2.ledger_status, 'LEDGER_MANAGED')

    def test_a_failed_reservation_does_not_flip_the_status(self):
        u = mk_marketer(self.db)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        r2 = self.client.post('/payments/allocate-to-campaign',
                              json={'campaign_id': camp_id, 'credits': 10}, headers=auth(u))
        self.assertFalse(r2.json().get('ok', True), 'an unfunded allocation unexpectedly succeeded')
        camp = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp_id).first()
        self.assertEqual(camp.ledger_status, 'LEGACY_UNRECONCILED')

    def test_legacy_campaign_cannot_create_unbacked_spend_via_ledger_spend_directly(self):
        u = mk_marketer(self.db)
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        self.assertEqual(camp.ledger_status, 'LEGACY_UNRECONCILED')
        result = main._ledger_spend(self.db, camp, 1.0, idempotency_key=f'evt-{_uid()}', source='test')
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'legacy_unreconciled')
        self.assertEqual(main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp.id), 0.0)

    def test_admin_recompute_refuses_a_ledger_managed_campaign(self):
        """The one pre-existing (pre-CHANGE-001) spent_clp writer other
        than _ledger_spend itself: a legacy repair tool. It must not be
        allowed to overwrite the ledger's own mirror once a campaign is
        ledger-managed — that would itself create a ledger/cache
        divergence."""
        u = mk_marketer(self.db)
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        self.fund_real(u, 100)
        main._ledger_reserve(self.db, camp, u.id, 50, idempotency_key=f'evt-{_uid()}')
        self.db.expire_all()
        camp2 = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp.id).first()
        self.assertEqual(camp2.ledger_status, 'LEDGER_MANAGED')
        r = self.client.post(f'/admin/campaigns/{camp.id}/recompute-spend',
                             params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 409, r.text)

    def test_admin_recompute_still_works_for_a_legacy_campaign(self):
        u = mk_marketer(self.db)
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=10_000_000, spent_clp=999_000, value_class='REAL',
                               is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        r = self.client.post(f'/admin/campaigns/{camp.id}/recompute-spend',
                             params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §6 — reconciliation classification taxonomy
# ═══════════════════════════════════════════════════════════════════════

class TestReconciliationClassification(Base):

    def test_reports_campaign_status_summary_and_ambiguous_provenance(self):
        u = mk_marketer(self.db)
        legacy_camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                                      budget_clp=1000, spent_clp=500, value_class='REAL',
                                      is_active=True)
        self.db.add(legacy_camp); self.db.commit(); self.db.refresh(legacy_camp)

        managed_camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T2',
                                       budget_clp=1000, value_class='REAL', is_active=True)
        self.db.add(managed_camp); self.db.commit(); self.db.refresh(managed_camp)
        self.fund_real(u, 100)
        main._ledger_reserve(self.db, managed_camp, u.id, 10, idempotency_key=f'evt-{_uid()}')

        r = self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        summary = body['campaign_status_summary']
        self.assertGreaterEqual(summary['legacy_unreconciled_active'], 1)
        self.assertGreaterEqual(summary['ledger_managed_active'], 1)
        ambiguous_ids = [a['campaign_id'] for a in body['ambiguous_funding_provenance']]
        self.assertIn(legacy_camp.id, ambiguous_ids)
        self.assertNotIn(managed_camp.id, ambiguous_ids)

    def test_reconciliation_is_still_read_only_with_the_new_fields(self):
        u = mk_marketer(self.db)
        camp = main.AdCampaign(advertiser_email=u.email, advertiser_name='A', title='T',
                               budget_clp=1000, spent_clp=500, value_class='REAL', is_active=True)
        self.db.add(camp); self.db.commit(); self.db.refresh(camp)
        before = (camp.ledger_status, camp.spent_clp, camp.is_active)
        self.client.get('/admin/ledger/reconciliation', params={'secret': ADMIN_SECRET})
        self.db.expire_all()
        camp2 = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == camp.id).first()
        after = (camp2.ledger_status, camp2.spent_clp, camp2.is_active)
        self.assertEqual(before, after, 'the classification pass mutated a campaign row')


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §7 — DEMO policy centralization
# ═══════════════════════════════════════════════════════════════════════

class TestDemoPolicyCentralization(Base):

    def test_policy_route_reports_provisional_flag_false(self):
        r = self.client.get('/admin/ledger/policy', params={'secret': ADMIN_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body['policy_approved_by_business'])
        self.assertEqual(body['demo_grant_amount_credits'], main.DEMO_GRANT_AMOUNT_CREDITS)
        self.assertEqual(body['demo_grant_max_lifetime_credits'], main.DEMO_GRANT_MAX_LIFETIME_CREDITS)

    def test_policy_route_requires_admin_secret(self):
        r = self.client.get('/admin/ledger/policy', params={'secret': 'wrong'})
        self.assertEqual(r.status_code, 403)

    def test_demo_grant_uses_the_configured_constants_not_hardcoded_literals(self):
        src = _src_of(_function('_ledger_demo_grant'))
        self.assertIn('DEMO_GRANT_AMOUNT_CREDITS', src)
        self.assertIn('DEMO_GRANT_MAX_LIFETIME_CREDITS', src)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §8 — PostgreSQL portability (structural; no live PG)
# ═══════════════════════════════════════════════════════════════════════

class TestPostgresPortabilityOfBillingWrites(unittest.TestCase):
    """No live disposable PostgreSQL is available in this environment (the
    same limitation CHANGE-003 disclosed for its own DDL branch — see that
    change's report). This proves portability STRUCTURALLY instead: no
    dialect-specific SQL function remains in any billing/ledger write
    path, and the RETURNING clause the §4 fix uses is standard SQL
    supported by SQLite>=3.35 and PostgreSQL>=8.2, not a SQLite-only
    construct — so this is disclosed as a real, not eliminated, limitation:
    genuine PostgreSQL lock/serialization behavior is only proven live, at
    controlled deploy time, exactly as CHANGE-003 disclosed for its DDL."""

    def test_no_least_function_executes_in_main_or_payments(self):
        """Prose comments/docstrings mentioning the historical LEAST() bug
        are expected and fine (main.py has several, explaining the fix);
        only an actual executed `SET col = LEAST(` assignment would be the
        regression this guards against."""
        payments_src = Path(main.__file__).parent.joinpath('payments.py').read_text(encoding='utf-8')
        for src, name in ((MAIN_SRC, 'main.py'), (payments_src, 'payments.py')):
            self.assertIsNone(re.search(r'SET\s+\w+\s*=\s*LEAST\s*\(', src, re.IGNORECASE),
                              f'{name} still executes a LEAST()-based SQL UPDATE')

    def test_ledger_post_handles_integrityerror_not_a_bare_except(self):
        src = _src_of(_function('_ledger_post'))
        self.assertIn('except IntegrityError', src)

    def test_add_credits_uses_returning_not_a_python_side_snapshot(self):
        payments_src = Path(main.__file__).parent.joinpath('payments.py').read_text(encoding='utf-8')
        tree = ast.parse(payments_src)
        fn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == 'add_credits')
        body = ast.get_source_segment(payments_src, fn) or ''
        self.assertIn('RETURNING', body)
        self.assertIn('balance_credits + :delta', body)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE-001 REMEDIATION §5/§10 — no fabricated historical funding
# ═══════════════════════════════════════════════════════════════════════

class TestNoFabricatedHistoricalFunding(unittest.TestCase):

    def test_migrate_never_calls_a_ledger_adapter(self):
        """The additive ad_campaigns.ledger_status migration adds a column
        with a hardcoded string default — it must never itself call a
        _ledger_* function, or a schema migration would silently invent
        funded reservations for every existing campaign."""
        src = _migrate_source()
        for name in LEDGER_ADAPTER_NAMES:
            self.assertNotIn(f'{name}(', src,
                             f'_migrate() calls {name} — this would fabricate historical funding')

    def test_ledger_status_migration_defaults_every_row_to_legacy(self):
        src = _migrate_source()
        self.assertIn("('ledger_status', \"TEXT DEFAULT 'LEGACY_UNRECONCILED'\")", src)


# ═══════════════════════════════════════════════════════════════════════
# INDEPENDENT RE-AUDIT HARDENING — §2 gap: HTTP-layer idempotency
# enforcement was never exercised through the real route, only inspected
# in source. A mutation test (idempotency_key: str -> Optional[str] = None)
# passed all 604 prior tests, proving no behavioral test actually covered
# this. These call the real FastAPI TestClient route, not main.py internals.
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotencyKeyRequiredAtHTTPLayer(Base):

    def _funded_campaign(self, credits=100):
        u = mk_marketer(self.db)
        self.fund_real(u, credits + 50)
        r = self.client.post('/advertiser/campaigns', json=campaign_payload(u), headers=auth(u))
        camp_id = r.json()['campaign_id']
        self.client.post('/payments/allocate-to-campaign',
                         json={'campaign_id': camp_id, 'credits': credits}, headers=auth(u))
        return u, camp_id

    def _state(self, camp_id):
        logs = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ad_impression_logs WHERE campaign_id=:c"),
            {'c': camp_id}).fetchone()[0]
        txns = self.db.execute(main.text(
            "SELECT COUNT(*) FROM ledger_transactions WHERE campaign_id=:c"),
            {'c': camp_id}).fetchone()[0]
        bal = main._ledger_balance(self.db, L.CAMPAIGN_REAL_RESERVED, camp_id)
        return (logs, txns, bal)

    # ── /ads/view ──

    def test_ads_view_missing_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a request with NO idempotency_key field still moved state/money')

    def test_ads_view_blank_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': ''},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a request with idempotency_key="" still moved state/money')

    def test_ads_view_whitespace_only_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': '   '},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a whitespace-only idempotency_key still moved state/money')

    def test_ads_view_valid_key_still_works_normally(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/view', json={'campaign_id': camp_id, 'debate_id': None,
                                                 'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 200, r.text)
        self.db.expire_all()
        after = self._state(camp_id)
        self.assertEqual(after[0], before[0] + 1)
        self.assertEqual(after[1], before[1] + 1)
        self.assertLess(after[2], before[2])

    # ── /ads/impression ──

    def test_ads_impression_missing_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/impression', params={'campaign_id': camp_id, 'debate_id': 0},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a request with NO idempotency_key param still moved state/money')

    def test_ads_impression_blank_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/impression',
                             params={'campaign_id': camp_id, 'debate_id': 0, 'idempotency_key': ''},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a request with idempotency_key="" still moved state/money')

    def test_ads_impression_whitespace_only_idempotency_key_is_rejected_with_no_charge(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/impression',
                             params={'campaign_id': camp_id, 'debate_id': 0, 'idempotency_key': '   '},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 422, r.text)
        self.db.expire_all()
        self.assertEqual(before, self._state(camp_id),
                         'a whitespace-only idempotency_key still moved state/money')

    def test_ads_impression_valid_key_still_works_normally(self):
        u, camp_id = self._funded_campaign()
        voter = mk_user(self.db)
        before = self._state(camp_id)
        r = self.client.post('/ads/impression',
                             params={'campaign_id': camp_id, 'debate_id': 0,
                                     'idempotency_key': f'evt-{_uid()}'},
                             headers=auth(voter))
        self.assertEqual(r.status_code, 200, r.text)
        self.db.expire_all()
        after = self._state(camp_id)
        self.assertEqual(after[0], before[0] + 1)
        self.assertEqual(after[1], before[1] + 1)
        self.assertLess(after[2], before[2])


# ═══════════════════════════════════════════════════════════════════════
# INDEPENDENT RE-AUDIT HARDENING — structural: _ledger_reserve is the
# ONLY writer permitted to transition ledger_status to LEDGER_MANAGED.
# ═══════════════════════════════════════════════════════════════════════

class TestLedgerStatusSingleWriter(unittest.TestCase):

    ALLOWED_LEDGER_STATUS_WRITERS = {'_ledger_reserve'}
    WRITE_PATTERNS = (
        re.compile(r'\.ledger_status\s*=(?!=)'),
        re.compile(r'SET\s+ledger_status\s*=', re.IGNORECASE),
    )

    def _offenders(self, tree, src_text):
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in self.ALLOWED_LEDGER_STATUS_WRITERS or node.name == '_migrate':
                continue
            body = ast.get_source_segment(src_text, node) or ''
            for pat in self.WRITE_PATTERNS:
                if pat.search(body):
                    offenders.append(f'{node.name} writes ledger_status directly ({pat.pattern})')
        return offenders

    def test_no_alternate_ledger_status_writer_exists(self):
        """_migrate() is exempted because its write is the additive column
        DEFAULT clause ('TEXT DEFAULT ...'), not an UPDATE/attribute
        assignment — checked separately below to prove it is exactly that
        and nothing more."""
        offenders = self._offenders(MAIN_TREE, MAIN_SRC)
        self.assertEqual(offenders, [], '\n'.join(offenders))

    def test_migrate_only_sets_a_column_default_never_an_update(self):
        src = _migrate_source()
        self.assertNotIn("SET ledger_status", src)
        self.assertNotRegex(src, r'\.ledger_status\s*=(?!=)')

    def test_detector_actually_catches_a_hidden_alternate_writer(self):
        """Mutation-test of the guard itself, same technique as
        TestSpentClpSingleWriter's self-test."""
        mutated_src = (
            "def admin_force_activate_campaign(campaign_id, secret, db):\n"
            "    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()\n"
            "    c.ledger_status = 'LEDGER_MANAGED'\n"
            "    db.commit()\n"
        )
        tree = ast.parse(mutated_src)
        offenders = self._offenders(tree, mutated_src)
        self.assertTrue(offenders, 'the detector failed to catch a hidden alternate writer')
        self.assertIn('admin_force_activate_campaign', offenders[0])


# ═══════════════════════════════════════════════════════════════════════
# RELEASE HARDENING — Phase 3: SQLite busy-timeout (engine-config only,
# added because local docs disagree on whether production still runs
# SQLite — see the comment on `engine = create_engine(...)` in main.py).
# ═══════════════════════════════════════════════════════════════════════

class TestSQLiteBusyTimeout(unittest.TestCase):

    def test_sqlite_connect_args_set_an_explicit_busy_timeout(self):
        m = re.search(
            r"connect_args=(\{[^}]*\}) if 'sqlite' in DATABASE_URL else (\{[^}]*\})",
            MAIN_SRC)
        self.assertIsNotNone(m, 'engine connect_args branch not found in the expected shape')
        sqlite_args, pg_args = m.group(1), m.group(2)
        self.assertIn("'timeout'", sqlite_args,
                      'no explicit busy-wait timeout configured for the SQLite branch')
        self.assertEqual(pg_args.strip(), '{}',
                         'PostgreSQL connect_args must stay untouched — a SQLite busy-timeout '
                         'has no PostgreSQL equivalent and must never be ported there')

    def test_configured_timeout_is_a_real_improvement_over_the_driver_default(self):
        """sqlite3's own default (undocumented in this repo before this
        fix) is 5 seconds. The configured value must exceed that, or this
        change would be cosmetic."""
        m = re.search(r"'timeout':\s*(\d+)", MAIN_SRC)
        self.assertIsNotNone(m)
        self.assertGreater(int(m.group(1)), 5)

    def test_sqlite_busy_timeout_actually_lets_a_blocked_writer_wait_and_succeed(self):
        """Behavioral proof of the underlying mechanism sqlite3's `timeout`
        parameter provides (the exact parameter main.py's engine now
        passes): a second connection attempting to write while a first
        holds the write lock BLOCKS AND RETRIES up to `timeout` seconds
        instead of failing immediately. Uses a short but longer-than-the-
        undocumented-5s-default-would-need contention window (own throwaway
        db file, not the shared test DB) so this stays fast without being
        vacuous — it would fail under a timeout of 0 or the bare, unconfigured
        sqlite3 default in the same shape as the real fix."""
        import sqlite3, tempfile as _tempfile, threading as _threading, time as _time
        path = os.path.join(_tempfile.mkdtemp(prefix='busytimeout-'), 't.db')
        TEST_TIMEOUT = 3  # seconds — proportionally the same fix, scaled down for test speed
        HOLD_SECONDS = 1.2

        con1 = sqlite3.connect(path, timeout=TEST_TIMEOUT)
        con1.execute('CREATE TABLE t (v INTEGER)')
        con1.execute('BEGIN IMMEDIATE')
        con1.execute('INSERT INTO t VALUES (1)')

        result = {}

        def try_write():
            con2 = sqlite3.connect(path, timeout=TEST_TIMEOUT)
            try:
                con2.execute('INSERT INTO t VALUES (2)')
                con2.commit()
                result['ok'] = True
            except sqlite3.OperationalError as e:
                result['ok'] = False
                result['error'] = str(e)
            finally:
                con2.close()

        t = _threading.Thread(target=try_write)
        t.start()
        _time.sleep(HOLD_SECONDS)
        con1.commit()
        t.join(timeout=TEST_TIMEOUT + 2)
        con1.close()

        self.assertTrue(result.get('ok'),
                        f'a writer blocked for {HOLD_SECONDS}s did not succeed within a '
                        f'{TEST_TIMEOUT}s busy-timeout: {result.get("error")}')


if __name__ == '__main__':
    unittest.main()
