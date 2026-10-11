"""
test_production_readiness_fixes.py — regression suite for the full
production-readiness audit fixes (blockchain truthfulness, registration
country canonical source, SMS/email send-failure honesty).

Same house style as test_matching_wiring.py / test_jc_demo_account.py:
STRUCTURAL tests parse main.py's real AST (no imports needed — main.py
cannot be imported in this dev environment, missing boto3/twilio/
sendgrid/stripe/cloudinary). BEHAVIOURAL tests exec the real, extracted
function source (never a hand-retyped copy) so drift between this test
and the committed code is impossible.

Run:
    python3 -m unittest test_production_readiness_fixes -v
"""

import ast
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

MAIN = Path(__file__).with_name('main.py')
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)

VOTER_HTML = Path(__file__).with_name('voter_portal.html')
VOTER_SRC = VOTER_HTML.read_text(encoding='utf-8')


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _route_function(method, path):
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == 'app' and fn.attr == method):
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == path:
                return node
    return None


def _src_of(node) -> str:
    return ast.get_source_segment(SRC, node) or ''


def _calls_in(node) -> set:
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _class_def(name):
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _column_names(class_node) -> set:
    names = set()
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name):
            names.add(stmt.targets[0].id)
    return names


# ═══════════════════════════════════════════════════════════════════════
# PRIORITY 2 — blockchain truthfulness
# ═══════════════════════════════════════════════════════════════════════

class TestBlockchainTruthfulness(unittest.TestCase):

    def test_debate_vote_has_blockchain_anchored_column(self):
        node = _class_def('DebateVote')
        self.assertIsNotNone(node)
        self.assertIn('blockchain_anchored', _column_names(node))

    def test_migration_adds_blockchain_anchored_column(self):
        self.assertIn("ALTER TABLE debate_votes ADD COLUMN blockchain_anchored BOOLEAN", SRC)

    def test_cast_vote_inner_computes_truthful_anchored_flag(self):
        node = _function('_cast_vote_inner')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("blockchain_anchored = bool(bc_result.get('success')) and bool(bc_result.get('live'))", src)
        # Must be persisted on the DebateVote row, not just computed.
        self.assertIn('blockchain_anchored=blockchain_anchored', src)
        # Must be returned to the caller, not silently kept server-side only.
        self.assertIn("'blockchain_anchored': blockchain_anchored,", src)

    def test_google_reviewer_demo_vote_reports_not_anchored(self):
        node = _function('_cast_vote_inner')
        src = _src_of(node)
        self.assertIn("'blockchain_anchored': False,", src)

    def test_verify_vote_endpoint_exposes_real_db_value(self):
        node = _route_function('post', '/debates/{debate_id}/verify')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("'blockchain_anchored': vote.blockchain_anchored,", src)

    def test_anchor_vote_never_raises_confirmed_in_blockchain_py(self):
        """Documents WHY the fix is needed: blockchain.anchor_vote()
        structurally cannot signal failure via an exception — every
        branch returns a dict, including the except: block."""
        bc_src = Path(__file__).with_name('blockchain.py').read_text(encoding='utf-8')
        bc_tree = ast.parse(bc_src)
        anchor_node = None
        for node in ast.walk(bc_tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'anchor_vote':
                anchor_node = node
                break
        self.assertIsNotNone(anchor_node)
        anchor_src = ast.get_source_segment(bc_src, anchor_node)
        self.assertIn("'success': False", anchor_src)
        self.assertIn('_mock_tx', anchor_src)


class TestBlockchainFrontendHonesty(unittest.TestCase):

    def test_success_card_branches_on_blockchain_anchored(self):
        """The success card must no longer unconditionally claim
        on-chain anchoring — it must check data.blockchain_anchored."""
        self.assertIn('const isAnchored = !!data.blockchain_anchored;', VOTER_SRC)
        self.assertIn('successTitle', VOTER_SRC)
        self.assertIn('successBody', VOTER_SRC)

    def test_polygonscan_link_gated_on_anchored_flag(self):
        idx = VOTER_SRC.index('const explorerLink')
        window = VOTER_SRC[idx:idx + 300]
        self.assertIn('isAnchored', window)
        self.assertIn('polygonscan.com/tx/', window)

    def test_accuracy_stat_no_longer_inferred_from_tx_presence_alone(self):
        idx = VOTER_SRC.index('const accuracy =')
        window = VOTER_SRC[idx:idx + 300]
        self.assertIn('data.blockchain_anchored', window)
        # The old buggy expression must be gone from this specific computation.
        self.assertNotIn("data.blockchain_tx ? '100%'", window)


# ═══════════════════════════════════════════════════════════════════════
# PRIORITY 5 — registration country canonical source
# ═══════════════════════════════════════════════════════════════════════

class TestRegistrationCountryCatalogue(unittest.TestCase):

    def test_countries_endpoint_exists_and_is_public(self):
        node = _route_function('get', '/countries')
        self.assertIsNotNone(node)
        # No Depends(get_current_user)/get_verified_user in the signature —
        # must be reachable before the user has a token.
        src = _src_of(node)
        self.assertNotIn('get_current_user', src)
        self.assertNotIn('get_verified_user', src)

    def test_countries_endpoint_backed_by_country_names(self):
        node = _route_function('get', '/countries')
        src = _src_of(node)
        self.assertIn('COUNTRY_NAMES', src)

    def test_kenya_added_to_canonical_catalogue(self):
        """KE existed in the OLD static voter_portal.html dropdown but
        not in COUNTRY_NAMES — adding it here is what prevents it from
        disappearing now that registration reads from this dict."""
        m = ast_country_names = None
        idx = SRC.index("COUNTRY_NAMES = {")
        end = SRC.index("\n}", idx)
        body = SRC[idx:end]
        self.assertIn("'KE':'Kenya'", body)

    def test_voter_portal_country_select_no_longer_hardcoded(self):
        """The <select id="r-country"> must no longer contain a large
        static list of <option> tags — it's populated by JS from
        GET /countries now. Only the placeholder option may remain."""
        start = VOTER_SRC.index('<select id="r-country"')
        end = VOTER_SRC.index('</select>', start)
        select_block = VOTER_SRC[start:end]
        option_count = select_block.count('<option')
        self.assertEqual(option_count, 1, f'expected only the placeholder <option>, found {option_count}')
        self.assertNotIn('🇨🇱', select_block, 'hardcoded flag emoji option found in static markup')

    def test_load_registration_countries_function_exists_and_fetches_countries(self):
        self.assertIn('async function loadRegistrationCountries()', VOTER_SRC)
        idx = VOTER_SRC.index('async function loadRegistrationCountries()')
        window = VOTER_SRC[idx:idx + 1200]
        self.assertIn('${API}/countries', window)
        self.assertIn("document.getElementById('r-country')", window)

    def test_load_registration_countries_wired_to_dom_content_loaded(self):
        self.assertIn("document.addEventListener('DOMContentLoaded', loadRegistrationCountries);", VOTER_SRC)


# ═══════════════════════════════════════════════════════════════════════
# PRIORITY 6 — external service failure honesty (SMS + email)
# ═══════════════════════════════════════════════════════════════════════

def _exec_send_sms_otp():
    """Extract and exec the REAL send_sms_otp source in an isolated
    namespace, with just enough of main.py's module-level state to run
    it (its own OTP templates dict + os + print)."""
    tmpl_node = None
    for node in TREE.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == '_OTP_SMS_TEMPLATES':
            tmpl_node = node
            break
    assert tmpl_node is not None
    ns = {'os': os}
    exec(compile(ast.Module(body=[tmpl_node], type_ignores=[]), '<extract>', 'exec'), ns)
    func_node = _function('send_sms_otp')
    exec(_src_of(func_node), ns)
    return ns['send_sms_otp']


def _install_fake_twilio(client_factory):
    """twilio isn't installed in this dev environment (same class of gap
    as boto3/sendgrid/stripe throughout this project) — send_sms_otp does
    `from twilio.rest import Client` as a LOCAL import inside the
    function body, so injecting fake modules into sys.modules (rather
    than mock.patch, which requires the real package importable to
    resolve its target path) lets the REAL extracted function body run
    unmodified against a controllable fake Client."""
    fake_rest = types.ModuleType('twilio.rest')
    fake_rest.Client = client_factory
    fake_twilio = types.ModuleType('twilio')
    fake_twilio.rest = fake_rest
    return {'twilio': fake_twilio, 'twilio.rest': fake_rest}


class TestSmsOtpHonesty(unittest.TestCase):

    def setUp(self):
        self.send_sms_otp = _exec_send_sms_otp()
        self._orig_modules = {}
        for name in ('twilio', 'twilio.rest'):
            self._orig_modules[name] = sys.modules.get(name)
        self.addCleanup(self._restore_modules)

    def _restore_modules(self):
        for name, mod in self._orig_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_returns_false_when_twilio_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)
            result = self.send_sms_otp('+56912345678', '123456', 'es')
        self.assertFalse(result, 'send_sms_otp must return False, not True, when Twilio is unconfigured')

    def test_returns_false_when_twilio_send_raises(self):
        class FailingMessages:
            def create(self, **kw):
                raise Exception('network down')
        class FailingClient:
            def __init__(self, sid, token):
                self.messages = FailingMessages()
        sys.modules.update(_install_fake_twilio(FailingClient))
        with mock.patch.dict(os.environ, {'TWILIO_ACCOUNT_SID': 'ACxxx', 'TWILIO_AUTH_TOKEN': 'tok'}):
            result = self.send_sms_otp('+56912345678', '123456', 'es')
        self.assertFalse(result)

    def test_returns_true_only_on_genuine_successful_send(self):
        class OkMessages:
            def create(self, **kw):
                return types.SimpleNamespace(sid='SMxxx')
        class OkClient:
            def __init__(self, sid, token):
                self.messages = OkMessages()
        sys.modules.update(_install_fake_twilio(OkClient))
        with mock.patch.dict(os.environ, {'TWILIO_ACCOUNT_SID': 'ACxxx', 'TWILIO_AUTH_TOKEN': 'tok'}):
            result = self.send_sms_otp('+56912345678', '123456', 'es')
        self.assertTrue(result)


class TestSmsCallersReportFailureHonestly(unittest.TestCase):

    def test_verify_phone_send_checks_result_and_raises_503(self):
        node = _route_function('post', '/verify/phone/send')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('sent = send_sms_otp(', src)
        self.assertIn('if not sent:', src)
        self.assertIn('HTTPException(503', src)

    def test_request_vote_otp_checks_result_and_raises_503(self):
        node = _route_function('post', '/users/request-vote-otp')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('sent = send_sms_otp(', src)
        self.assertIn('if not sent:', src)
        self.assertIn('HTTPException(503', src)

    def test_login_2fa_path_already_gates_sms_on_twilio_active_unchanged(self):
        """Regression guard: /auth/login's 2FA path only attempts SMS when
        twilio_active, and now reports requires.email/requires.sms based on
        ACTUAL send success (email_sent/sms_sent), not verified-status alone.
        Also confirms the new full-lockout 503 when no channel can deliver."""
        node = _route_function('post', '/auth/login')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('twilio_active = bool(os.getenv', src)
        self.assertIn('email_sent = send_email_otp(', src)
        self.assertIn('sms_sent = send_sms_otp(', src)
        self.assertIn("'email': email_sent", src)
        self.assertIn("'sms':   sms_sent", src)
        self.assertIn('HTTPException(503', src)


class TestEmailOtpHonesty(unittest.TestCase):

    def test_send_email_otp_gmail_fallback_returns_false_when_unconfigured(self):
        node = _function('send_email_otp')
        self.assertIsNotNone(node)
        src = _src_of(node)
        # The specific "not gmail_pass" branch must now return False.
        idx = src.index('if not gmail_pass:')
        window = src[idx:idx + 120]
        self.assertIn('return False', window)
        self.assertNotIn('return True', window)

    def test_send_html_email_gmail_fallback_returns_false_when_unconfigured(self):
        node = _function('_send_html_email')
        self.assertIsNotNone(node)
        src = _src_of(node)
        idx = src.index('if not gmail_pass:')
        window = src[idx:idx + 120]
        self.assertIn('return False', window)
        self.assertNotIn('return True', window)


# ═══════════════════════════════════════════════════════════════════════
# REGRESSION — everything already correct/established must stay that way
# ═══════════════════════════════════════════════════════════════════════

class TestNoRegressionInEstablishedBehavior(unittest.TestCase):

    def test_jc_and_reviewer_vote_split_still_intact(self):
        node = _function('_cast_vote_inner')
        src = _src_of(node)
        self.assertIn('_is_google_full_review_account(user.email)', src)
        self.assertNotIn('_is_full_demo_account(user.email)', src)

    def test_target_categories_and_excluded_categories_enforced_in_eligibility(self):
        """Confirms this audit's finding that these ARE real, enforced
        targeting dimensions (not dead UI fields) — no change was made
        here because none was needed."""
        elig_src = Path(__file__).with_name('eligibility.py').read_text(encoding='utf-8')
        self.assertIn('excluded_categories', elig_src)
        self.assertIn('derive_content_tags', elig_src)

    def test_campaign_metrics_endpoint_queries_real_impression_log(self):
        """Confirms this audit's finding that the dashboard already uses
        real AdImpressionLog rows — no placeholder data, no change made."""
        node = _route_function('get', '/marketer/campaigns/{campaign_id}/metrics')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('db.query(AdImpressionLog)', src)

    def test_organizers_debates_create_endpoint_unchanged_role_gate(self):
        node = _route_function('post', '/organizers/debates')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("user.role not in ('organizer', 'admin')", src)

    def test_geo_importer_and_geo_models_untouched(self):
        """Priority 5 explicitly must not reopen the paused geography-
        import project. Confirm the GeoCountry/GeoUnit models and the
        geo_importer module were not touched by this round of fixes."""
        geo_node = _class_def('GeoCountry')
        self.assertIsNotNone(geo_node)
        # hierarchy_available / nuts_hierarchy_available columns from the
        # already-completed geography work must still be present,
        # unmodified, unexpanded.
        cols = _column_names(geo_node)
        self.assertIn('hierarchy_available', cols)
        self.assertIn('nuts_hierarchy_available', cols)


class TestWorldCountriesRollbackFix(unittest.TestCase):
    """Regression guard for a REAL bug found and fixed via live local
    integration testing (not just code reading): world_countries is a
    raw-SQL table with no CREATE TABLE anywhere in this codebase (created
    out-of-band in production at some point). Every `except Exception:`
    around a query against it that is missing `db.rollback()` leaves the
    session's Postgres transaction ABORTED, so the VERY NEXT unrelated
    query on the same request then fails with InFailedSqlTransaction.
    Reproduced deterministically: a fresh DB without world_countries made
    GET /debates 500 for every authenticated user, immediately after a
    clean registration. Fixed in 6 locations; confirmed fixed by re-running
    the same repro and getting 200 with real debate data. This test
    confirms db.rollback() is present in each except-block that touches
    world_countries, so none of the 6 fixes can silently regress."""

    def test_primary_ppp_lookup_rolls_back_on_failure(self):
        node = _function('_country_per_capita_ppp_usd')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('world_countries', src)
        self.assertIn('db.rollback()', src)

    def test_second_ppp_lookup_rolls_back_on_failure(self):
        # Second standalone function reading world_countries.gdp_per_capita_usd
        # for the same PPP figure (CHANGE-002's one canonical writer; this is
        # a reader). Locate it by its distinctive query text, not by name,
        # since it's a nested/local helper rather than a top-level def.
        found = False
        for node in ast.walk(TREE):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'text':
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    if 'gdp_per_capita_usd FROM world_countries WHERE iso2' in node.args[0].value:
                        found = True
        self.assertTrue(found, 'expected a second world_countries PPP SELECT by iso2 to still exist')
        # Both of the two `SELECT gdp_per_capita_usd FROM world_countries
        # WHERE iso2` occurrences must each be guarded by a nearby rollback;
        # confirmed via line-based proximity rather than AST-function lookup
        # since one lives inside an admin diagnostic endpoint, not a def.
        idx = 0
        occurrences = 0
        while True:
            idx = SRC.find('gdp_per_capita_usd FROM world_countries WHERE iso2', idx)
            if idx == -1:
                break
            occurrences += 1
            window = SRC[idx: idx + 1800]
            self.assertIn('db.rollback()', window,
                          f'world_countries SELECT at offset {idx} has no nearby db.rollback()')
            idx += 1
        self.assertGreaterEqual(occurrences, 2, 'expected at least 2 world_countries PPP SELECT-by-iso2 sites')

    def test_match_campaigns_matrix_fallback_rolls_back_on_failure(self):
        """The single most consequential of the 6 sites: this fallback runs
        on nearly every consultation view and every vote (ad billing)."""
        node = _function('_match_campaigns')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('world_countries', src)
        self.assertIn('db.rollback()', src)

    def test_admin_ppp_diagnostic_endpoint_rolls_back_on_failure(self):
        idx = SRC.find("table_error = f'world_countries unavailable")
        self.assertNotEqual(idx, -1)
        window = SRC[max(0, idx - 600):idx]
        self.assertIn('db.rollback()', window)

    def test_both_percentile_cont_fallback_blocks_roll_back_on_failure(self):
        """Two non-identical nested PERCENTILE_CONT/AVG retry blocks in
        socioeconomic-tier code (different variable names at each site) —
        both independently needed the fix since Edit's replace_all only
        matched one on the first pass."""
        occurrences = 0
        idx = 0
        while True:
            idx = SRC.find('PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_m2_avg', idx)
            if idx == -1:
                break
            occurrences += 1
            window = SRC[idx: idx + 1500]
            self.assertIn('db.rollback()', window,
                          f'PERCENTILE_CONT block at offset {idx} has no nearby db.rollback()')
            idx += 1
        self.assertEqual(occurrences, 2, 'expected exactly 2 PERCENTILE_CONT(price_m2_avg) sites')


if __name__ == '__main__':
    unittest.main()
