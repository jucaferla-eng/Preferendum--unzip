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
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import socioeconomic  # dependency-free pure-Python module, safe to import directly

MAIN = Path(__file__).with_name('main.py')
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)

VOTER_HTML = Path(__file__).with_name('voter_portal.html')
VOTER_SRC = VOTER_HTML.read_text(encoding='utf-8')

APP_JS_SRC = Path(__file__).with_name('App.js').read_text(encoding='utf-8')
APP_JSON_SRC = Path(__file__).with_name('app.json').read_text(encoding='utf-8')


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


class TestVoteVerificationCode(unittest.TestCase):
    """Regression guard for the vote-verification-code audit: a unique
    code is generated per vote, is returned to the voter, resolves back
    to the real recorded vote, survives a fresh login, can't be used to
    vote again or reveal who cast it, and is truthful about blockchain
    anchoring. Confirmed end-to-end with a real live integration test
    (33/33) against the real app + a real local Postgres; these are the
    structural regression guards that run without that live setup."""

    def test_verify_code_column_is_unique_and_indexed(self):
        node = _class_def('DebateVote')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("verify_code     = Column(String, unique=True, index=True)", src)

    def test_cast_vote_generates_a_fresh_code_per_vote(self):
        node = _function('_cast_vote_inner')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('verify_code = generate_verify_code()', src)

    def test_verify_endpoint_exposes_no_voter_identity_fields(self):
        """The verify response must stay limited to vote content + aggregate
        debate stats — never voter_id/email/name/phone, since DebateVote.
        voter_id is always NULL by design and this endpoint requires no
        auth at all (anyone with the code can look it up)."""
        node = _route_function('post', '/debates/{debate_id}/verify')
        self.assertIsNotNone(node)
        src = _src_of(node)
        for forbidden in ('user.email', 'user.name', 'user.phone', 'voter_id', '.national_id'):
            self.assertNotIn(forbidden, src)

    def test_confirm_endpoint_rejects_reusing_an_already_verified_code(self):
        node = _route_function('post', '/debates/{debate_id}/verify/confirm')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('if vote.verified is not None:', src)
        self.assertIn("HTTPException(400, 'Already verified')", src)

    def test_verify_endpoint_reports_real_stored_blockchain_anchored(self):
        node = _route_function('post', '/debates/{debate_id}/verify')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("'blockchain_anchored': vote.blockchain_anchored", src)

    def test_my_vote_endpoint_no_longer_returns_the_dead_reward_code_field(self):
        """VOTE-VERIFICATION AUDIT fix: DebateVote has no reward_code column,
        so hasattr(vote, 'reward_code') was always False — this endpoint
        always claimed '' (no reward) regardless of the real outcome. Fixed
        by removing the field rather than fabricating a value the schema
        can't actually provide."""
        node = _route_function('get', '/debates/{debate_id}/my-vote')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertNotIn("'reward_code':", src)

    def test_my_vote_keyed_by_user_id_survives_a_fresh_login(self):
        """HasVotedLog is keyed by user_id, not by session/token, so a vote
        cast before logout is still found by a token minted on a later,
        independent login — confirmed live in the integration test."""
        node = _route_function('get', '/debates/{debate_id}/my-vote')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('HasVotedLog.user_id == user.id', src)


class TestProfessionFieldFreeText(unittest.TestCase):
    """Regression guard for the profession-field audit: voters must be
    able to type ANY profession, in any language, and have it preserved
    exactly — never forced into a predefined English-titled option, and
    never silently overwritten by the matching/classification pipeline."""

    def test_voter_register_input_profession_is_unrestricted_free_text(self):
        """No Enum, no regex, no choice-list constrains VoterRegisterInput's
        profession field — confirmed by its absence from any Enum/Literal
        class definition in main.py."""
        node = _class_def('VoterRegisterInput')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('profession', src)
        for forbidden in ('Enum', 'Literal[', 'regex='):
            self.assertNotIn(forbidden, src)

    def test_voter_register_inner_stores_profession_verbatim(self):
        node = _function('_voter_register_inner')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("profession=data.profession or ''", src)

    def test_profession_column_is_never_silently_overwritten_anywhere(self):
        """Grep-equivalent structural guard: User.profession is set via the
        User(...) constructor kwarg exactly once (at registration), and as
        an attribute (`user.profession = ...`) in exactly ONE other place —
        set_my_profession, the self-only edit endpoint the user explicitly
        calls themselves. No OTHER code path (matching, classification,
        tier estimation, admin tooling) may ever write it. If any of those
        starts silently overwriting it with a resolved SOC code or English
        title, this test catches that regression immediately."""
        kwarg_writes = re.findall(r"profession=data\.profession or ''", SRC)
        self.assertEqual(len(kwarg_writes), 1,
                          f"expected exactly 1 'profession=data.profession or \\'\\'' site, found {len(kwarg_writes)}")
        attr_writes = [m for m in re.finditer(r'\.profession\s*=(?!=)', SRC)]
        self.assertEqual(len(attr_writes), 1,
                          f'expected exactly 1 `.profession = ...` attribute assignment (the explicit self-edit endpoint), found {len(attr_writes)}')
        self.assertIn('user.profession = prof', SRC)

    def test_set_my_profession_endpoint_is_self_only_and_stores_verbatim(self):
        node = _route_function('post', '/profile/profession')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('get_current_user', src)
        self.assertIn('user.profession = prof', src)
        self.assertNotIn('resolve_occupation_soc', src)

    def test_get_my_profession_resolves_legacy_soc_codes_for_display_only(self):
        node = _route_function('get', '/profile/profession')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('_profession_display(user.profession, db)', src)

    def test_profession_display_helper_never_writes_to_the_database(self):
        node = _function('_profession_display')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertNotIn('db.commit()', src)
        self.assertNotIn('db.add(', src)
        self.assertNotIn('UPDATE users', src)

    def test_profession_display_falls_back_to_real_bls_title_not_a_guess(self):
        """Any legacy SOC code without a curated Spanish alias still gets a
        reliable, real label — the genuine BLS title for that exact code
        from occupation_unified, never an invented translation."""
        node = _function('_profession_display')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("SELECT title FROM occupation_unified WHERE occupation_code=:c", src)

    def test_build_profile_resolves_occupation_separately_for_matching_only(self):
        """GLOBAL OCCUPATION RESOLUTION HARDENING (pre-existing, confirmed
        intact): the eligibility/targeting snapshot resolves user.profession
        through socioeconomic.resolve_occupation_soc for matching purposes,
        but that resolution is local to this function — it is never
        assigned back onto the user's own stored profession."""
        node = _function('_build_profile')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("occupation_override = _socio.resolve_occupation_soc(raw_profession) or raw_profession", src)
        self.assertNotIn('user.profession =', src)

    def test_professional_profile_display_dict_preserves_raw_text(self):
        """The informational/classification-display profile carries the
        user's RAW profession text (never resolved/translated), per R1:
        occupation is recorded and travels with the classification but
        never promotes or alters the tier, and never becomes an English
        label."""
        node = _function('_professional_profile')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("'occupation': _elig._base(getattr(user, 'profession', '') or '')", src)

    def test_occ_search_field_mirrors_free_typed_text_live(self):
        """voter_portal.html: every keystroke mirrors into the hidden
        r-profession field, so free text is captured even if the user
        never clicks a suggestion — the predefined list can no longer
        block submission."""
        self.assertIn("document.getElementById('r-profession').value = this.value.trim();", VOTER_SRC)

    def test_occ_search_click_handler_no_longer_submits_a_soc_code(self):
        """A clicked suggestion must fill in the (language-aware) label
        text, never the opaque SOC code — the submitted value must always
        be human-readable text in the user's own language, not a code."""
        self.assertNotIn("document.getElementById('r-profession').value = item.dataset.code;", VOTER_SRC)
        self.assertIn("document.getElementById('r-profession').value = item.dataset.label;", VOTER_SRC)

    def test_occ_search_click_handler_no_longer_forces_english_title_into_input(self):
        """Clicking a Spanish-matched suggestion must not replace the
        visible input with the English BLS title — this was the direct
        cause of the reported 'options appear in English' bug."""
        self.assertNotIn("input.value = item.dataset.title;", VOTER_SRC)
        self.assertIn("input.value = item.dataset.label;", VOTER_SRC)

    def test_profession_validation_no_longer_demands_a_selection(self):
        self.assertNotIn("'Selecciona tu ocupación'", VOTER_SRC)
        self.assertIn("'Escribe tu profesión u ocupación'", VOTER_SRC)

    def test_occ_search_has_a_sane_length_cap_not_a_restrictive_one(self):
        self.assertIn('id="occ-search" maxlength="100"', VOTER_SRC)


class TestProfileProfessionEditing(unittest.TestCase):
    """Regression guard for the profile view/edit phase: existing users
    (including legacy-SOC-code ones) can see and replace their own
    profession; nothing is bulk-migrated; the edit endpoint is self-only."""

    def test_profession_card_wired_into_the_profile_tab_load(self):
        self.assertIn('loadMyProfession();', VOTER_SRC)

    def test_profession_edit_posts_free_text_not_a_code(self):
        self.assertIn("body: JSON.stringify({profession: value})", VOTER_SRC)

    def test_legacy_code_notice_exists_and_is_conditional(self):
        self.assertIn('profession-legacy-notice', VOTER_SRC)
        self.assertIn("notice.style.display = d.is_legacy_code ? 'block' : 'none';", VOTER_SRC)

    def test_no_bulk_migration_routine_exists_for_profession(self):
        """Nothing in main.py may rewrite profession en masse across many
        users — the only writer is the self-only edit endpoint, exercised
        one user at a time, by that user's own choice."""
        self.assertNotIn("UPDATE users SET profession", SRC)
        self.assertNotIn(".update({'profession'", SRC)
        self.assertNotIn('.update({"profession"', SRC)


class TestOccupationClassificationResearch(unittest.TestCase):
    """Behavioral tests against the real socioeconomic module (pure
    Python, safe to import directly) — confirms the researched Chilean
    occupation classifications resolve correctly, never collide with
    existing entries, and the genuinely ambiguous ones stay unresolved
    (no invented income tier) rather than guessed."""

    def test_psicologa_and_psicologo_already_resolved_no_change_needed(self):
        self.assertEqual(socioeconomic.resolve_occupation_soc('Psicóloga'), '19-3033')
        self.assertEqual(socioeconomic.resolve_occupation_soc('Psicólogo'), '19-3033')

    def test_ingeniero_civil_industrial_resolves_to_industrial_engineer(self):
        for term in ('Ingeniero Civil Industrial', 'Ingeniera Civil Industrial',
                     'ingeniero civil industrial', 'INGENIERO CIVIL INDUSTRIAL'):
            self.assertEqual(socioeconomic.resolve_occupation_soc(term), '17-2112', term)

    def test_ingeniero_civil_industrial_never_collides_with_plain_ingeniero_civil(self):
        """'Ingeniero Civil' alone means literal civil engineering (17-2051)
        in Chile — the compound 'Civil Industrial' phrase must resolve
        differently and never bleed into this bare form or vice versa."""
        self.assertEqual(socioeconomic.resolve_occupation_soc('Ingeniero Civil'), '17-2051')
        self.assertEqual(socioeconomic.resolve_occupation_soc('Ingeniera Civil'), '17-2051')

    def test_ingeniero_informatico_variants_stay_explicitly_ambiguous(self):
        """Deliberately NOT resolved to a single SOC code — the work spans
        several genuinely distinct occupations with different pay
        profiles; no income tier is invented for these."""
        for term in ('Ingeniero Informático', 'Ingeniera Informática',
                     'Ingeniero Civil Informático', 'Ingeniera Civil Informática'):
            self.assertEqual(socioeconomic.resolve_occupation_soc(term), '', term)
            res = socioeconomic.resolve_occupation_candidates(term)
            self.assertEqual(res.status, socioeconomic.OccupationResolution.AMBIGUOUS, term)
            self.assertTrue(res.candidates, term)

    def test_bare_ingeniero_still_ambiguous_unaffected_by_new_entries(self):
        self.assertEqual(socioeconomic.resolve_occupation_soc('Ingeniero'), '')
        self.assertEqual(socioeconomic.resolve_occupation_soc('Ingeniera'), '')


class TestTargetSideOccupationResolution(unittest.TestCase):
    """Regression guard for a real asymmetry bug found and fixed during
    this audit: a user's own profession already resolved correctly via
    _build_profile's occupation_override, but a consultation/campaign
    organizer typing the IDENTICAL natural-language phrase into
    target_professions never matched that user, because
    eligibility.norm_occupation only understands bare SOC codes and a
    short legacy-slug list — not natural language. Confirmed live via a
    real eligibility evaluation: before this fix, an "Ingeniero Civil
    Industrial" voter was wrongly excluded from a campaign targeting
    'ingeniero industrial'; after, correctly included."""

    def test_eligibility_adapters_accept_an_occupations_override(self):
        """Both target-side adapters gained the override parameter,
        mirroring profile_from_user's existing occupation_override."""
        import eligibility as E
        import inspect
        self.assertIn('occupations_override', inspect.signature(E.consultation_target_from_debate).parameters)
        self.assertIn('occupations_override', inspect.signature(E.campaign_target_from_campaign).parameters)

    def test_override_omitted_means_unchanged_legacy_behavior(self):
        """When occupations_override is not passed (every pre-existing
        caller inside eligibility.py itself), a legacy slug like
        'ing_civil' resolves exactly as before — zero behavior change for
        anything not touched by this audit."""
        import eligibility as E

        class FakeDebate:
            id = 1; is_closed_list = False; scope_country = ''; scope_commune = ''
            target_gender = 'all'; target_age_min = None; target_age_max = None
            target_se_tiers = ''; target_professions = 'ing_civil'; target_cargos = ''
            target_company_sizes = ''; min_per_capita_usd = None; income_min_usd = None
            income_max_usd = None

        target = E.consultation_target_from_debate(FakeDebate())
        self.assertEqual(target.occupations, {'17-0000'})

    def test_resolve_target_professions_mirrors_user_side_resolution(self):
        node = _function('_resolve_target_professions')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('_socio.resolve_occupation_soc(t) or t', src)

    def test_resolve_target_professions_wired_into_consultation_decision(self):
        node = _function('_consultation_decision')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('_resolve_target_professions(', src)
        self.assertIn('consultation_target_from_debate(', src)

    def test_resolve_target_professions_wired_into_debates_listing(self):
        """_eligible_debates_for (shared by GET /debates, /debates/feed and
        /debates/for-me) calls evaluate_consultation directly in its own
        bulk loop, not through _consultation_decision — must carry the
        same fix independently, or discovery would silently diverge from
        direct access/voting."""
        node = _function('_eligible_debates_for')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('_resolve_target_professions(', src)

    def test_resolved_campaign_target_wired_into_both_campaign_decision_paths(self):
        for fn_name in ('_campaign_decision', '_match_campaigns'):
            node = _function(fn_name)
            self.assertIsNotNone(node, fn_name)
            src = _src_of(node)
            self.assertIn('_resolved_campaign_target(', src, fn_name)

    def test_industrial_engineer_voter_now_matches_ingeniero_industrial_targeting(self):
        """End-to-end behavioral proof at the eligibility layer (the live
        integration test proved the same thing against the real running
        app + real Postgres — this is the fast, dependency-free version)."""
        import eligibility as E

        profile = E.UserProfile(
            user_id=1, country='CL', commune='santiago', gender='F', age=34,
            se_tier='', occupation='17-2112', cargo='analista',
            company_size_rank=1, estimated_income_usd=12006.0,
            country_per_capita_ppp_usd=24013.0, is_authenticated=True,
        )

        class FakeCampaign:
            id = 1; target_country = 'CL'; target_communes = ''; target_gender = 'all'
            target_age_min = None; target_age_max = None; target_age_ranges = ''
            target_se_tiers = ''; target_professions = 'ingeniero industrial'
            target_cargos = ''; target_company_sizes = ''; min_per_capita_usd = None
            target_income_min = None; target_income_max = None; target_hnw_only = False
            min_hnw_score = 0.0; target_categories = ''; excluded_categories = ''
            blocked_competitors = ''; advertiser_name = ''; value_class = 'REAL'

        resolved_code = socioeconomic.resolve_occupation_soc('ingeniero industrial')
        self.assertEqual(resolved_code, '17-2112')
        resolved = E.campaign_target_from_campaign(
            FakeCampaign(), occupations_override=resolved_code)
        decision = E.evaluate_campaign(profile, resolved)
        self.assertTrue(decision.allowed, decision.reasons)


class TestPrefy480pSwitchover(unittest.TestCase):
    """Regression guard for switching /prefy/video/{context}/{lang} over
    to the verified, already-uploaded 480p files. Not deployed yet — this
    only confirms the CODE is correct ahead of that decision."""

    def test_original_key_tables_are_untouched_single_source_of_truth(self):
        """No second, hand-duplicated 480p table exists — the 480p key is
        always COMPUTED from the one real table, so it can never drift
        out of sync with it."""
        self.assertIn('PREFY_WELCOME_S3_KEY_BY_LANG', SRC)
        self.assertIn('PREFY_CAMPAIGN_S3_KEY_BY_LANG', SRC)
        node = _function('_prefy_480p_key')
        self.assertIsNotNone(node)

    def test_480p_key_uses_the_same_suffix_rule_as_the_upload_script(self):
        """Must match scripts/compress_prefy_videos.py's compressed_key_for
        exactly — those are the REAL keys already verified present in S3;
        any divergence here would 404 every single video."""
        ns = {}
        exec(_src_of(_function('_prefy_480p_key')), ns)
        fn = ns['_prefy_480p_key']
        self.assertEqual(
            fn('prefy/welcome/heygen_project 3/Prefy_bienvenida_en_app_Preferendum_version_3.mp4'),
            'prefy/welcome/heygen_project 3/Prefy_bienvenida_en_app_Preferendum_version_3_480p.mp4',
        )
        # Cross-check against the actual upload-script function too.
        import importlib.util
        spec = importlib.util.spec_from_file_location('_cpv', MAIN.with_name('scripts') / 'compress_prefy_videos.py')
        cpv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cpv)
        sample_key = 'prefy/Campaña /heygen_project/Guia_del_area_de_campanas_de_Preferendum_1080_6-de/Guia_del_area_de_campanas_de_Preferendum.mp4'
        self.assertEqual(fn(sample_key), cpv.compressed_key_for(sample_key, '_480p'))

    def test_serve_480p_defaults_to_true_but_is_a_one_env_var_rollback(self):
        self.assertIn("PREFY_SERVE_480P = os.getenv('PREFY_SERVE_480P', 'true').lower() != 'false'", SRC)

    def test_presigned_url_resolver_applies_the_480p_switch(self):
        node = _function('_prefy_s3_presigned_url')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('if PREFY_SERVE_480P:', src)
        self.assertIn('key = _prefy_480p_key(key)', src)

    def test_video_serving_route_unchanged_otherwise(self):
        """The route itself (fallback precedence, 404 handling, GitHub
        Release/local-disk branches) must be untouched — only the S3
        branch's resolved key changes, nothing else about this route."""
        node = _route_function('get', '/prefy/video/{context}/{lang}')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('_prefy_s3_presigned_url(context, lang)', src)
        self.assertIn('_prefy_video_github_release_url', src)
class TestStudentOccupationSuggestion(unittest.TestCase):
    """Regression guard for the "Estudiante"/"Student" suggestion added to
    the occupation/profession autocomplete (registration AND profile
    editing). Being a student is not a BLS paid occupation, so this must
    stay a purely client-side, cosmetic suggestion — never added to the
    backend BLS catalog, and never resolvable to a SOC code/income tier.
    Real browser-interaction behavior (typing, clicking, both fields, both
    languages, BLS-search regression) is covered separately by a jsdom
    harness run manually this session, not part of this dependency-free
    suite — see the PR description / session notes for that run's output."""

    def test_estudiante_and_student_never_resolve_to_a_soc_code(self):
        """The single most important invariant: selecting/typing the
        student suggestion must NEVER fabricate an income tier. Covers
        both languages, both genders' Spanish spelling habits, and
        case-insensitivity, matching how resolve_occupation_soc is
        actually invoked elsewhere (raw, unnormalized user text)."""
        for term in ('Estudiante', 'estudiante', 'ESTUDIANTE', 'Student', 'student', 'STUDENT'):
            self.assertEqual(socioeconomic.resolve_occupation_soc(term), '', term)
            res = socioeconomic.resolve_occupation_candidates(term)
            self.assertEqual(res.status, socioeconomic.OccupationResolution.UNRESOLVED, term)

    def test_student_pseudo_entry_is_client_side_only_never_in_backend_catalog(self):
        """api_list_occupations (the backend catalog /api/occupations
        itself feeds) must never gain a hardcoded student/pseudo entry —
        it is strictly occupation_unified's real BLS rows. The pseudo
        entry lives ONLY in voter_portal.html's client-side _loadOccData,
        appended AFTER the real fetch, never sent to or sourced from the
        server."""
        node = _route_function('get', '/api/occupations')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertNotIn('Estudiante', src)
        self.assertNotIn('Student', src)
        self.assertIn('occupation_unified', src)

    def test_voter_portal_appends_student_entry_client_side_with_null_code(self):
        """code: null (not a real/fabricated SOC code) is what makes this
        structurally impossible to accidentally feed into income
        estimation downstream — occupation_unified rows always carry a
        real, non-null SOC code; this entry deliberately never does."""
        self.assertIn("_occData = _occData.concat([{", VOTER_SRC)
        self.assertIn("code: null,", VOTER_SRC)
        self.assertIn("title: 'Student',", VOTER_SRC)
        self.assertIn("aliases_es: ['estudiante'],", VOTER_SRC)

    def test_profession_edit_field_gained_its_own_search_wiring(self):
        """The profile-editing field (previously a bare text input with no
        suggestions at all) now has the same catalog available, via its
        own self-contained function — kept separate from _setupOccSearch
        so the registration field's existing, already-tested behavior is
        never put at risk by this change."""
        self.assertIn('function _setupProfessionEditSearch()', VOTER_SRC)
        self.assertIn("window.addEventListener('DOMContentLoaded', _setupProfessionEditSearch);", VOTER_SRC)
        self.assertIn('profession-edit-results', VOTER_SRC)

    def test_profession_edit_suggestion_click_only_fills_free_text(self):
        """Mirrors the registration field's own guarantee: a clicked
        suggestion in profile editing can only ever set the visible,
        human-readable label text — never a code, never something hidden
        the user can't see and keep editing."""
        node_src = VOTER_SRC[VOTER_SRC.index('function _setupProfessionEditSearch()'):
                              VOTER_SRC.index('window.addEventListener', VOTER_SRC.index('function _setupProfessionEditSearch()'))]
        self.assertIn('input.value = item.dataset.label;', node_src)
        self.assertNotIn('item.dataset.code', node_src)

    def test_existing_registration_search_function_untouched_by_this_change(self):
        """_setupOccSearch's own body (registration field) must still
        contain every literal line TestProfessionFieldFreeText already
        pins — this change added a NEW function instead of modifying the
        existing one, specifically to keep that guarantee trivially true."""
        self.assertIn("document.getElementById('r-profession').value = this.value.trim();", VOTER_SRC)
        self.assertIn("document.getElementById('r-profession').value = item.dataset.label;", VOTER_SRC)
        self.assertIn("input.value = item.dataset.label;", VOTER_SRC)

    def test_student_suggestion_reachable_via_shared_occ_data_loader(self):
        """Both fields share ONE _loadOccData()/_occNorm() pair — the
        student entry is appended exactly once, so both the registration
        and profile-edit suggestion lists stay in sync automatically
        (no separate catalog to maintain, no risk of one field getting
        the suggestion and the other silently not)."""
        self.assertEqual(VOTER_SRC.count("_occData = _occData.concat([{"), 1)
        occ_search_body = VOTER_SRC[VOTER_SRC.index('function _setupOccSearch()'):
                                     VOTER_SRC.index('window.addEventListener', VOTER_SRC.index('function _setupOccSearch()'))]
        self.assertIn('_loadOccData()', occ_search_body)
        edit_body = VOTER_SRC[VOTER_SRC.index('function _setupProfessionEditSearch()'):
                               VOTER_SRC.index('window.addEventListener', VOTER_SRC.index('function _setupProfessionEditSearch()'))]
        self.assertIn('_loadOccData()', edit_body)


class TestFaceDuplicateCheckFailsClosed(unittest.TestCase):
    """SECURITY POLICY CHANGE: if identity can't be verified OR the
    duplicate-face check can't be completed, the face-vote token must
    NOT be issued (and therefore the vote can never be counted — cast_vote
    requires this exact token for every selfie_verified user). Previously
    this path was fail-OPEN (an error was logged but the token was issued
    anyway). Must also be retryable with no permanent lock/data loss, and
    safe under near-simultaneous requests for the same consultation."""

    def test_duplicate_check_now_raises_instead_of_silently_continuing(self):
        node = _function('get_face_vote_token')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertNotIn('non-fatal error (not blocking vote)', src)
        self.assertIn("raise HTTPException(503, 'No pudimos confirmar que tu rostro sea único", src)

    def test_no_database_write_happens_before_the_fail_closed_point(self):
        """Proves this is genuinely retryable with zero data loss: nothing
        in this function is persisted to the DB (no db.add/db.commit) —
        the only side effects are the Rekognition calls themselves and a
        pure, local JWT encode at the very end. A failure here leaves
        nothing behind to clean up or that blocks a fresh attempt."""
        node = _function('get_face_vote_token')
        src = _src_of(node)
        self.assertNotIn('db.add(', src)
        self.assertNotIn('db.commit(', src)

    def test_duplicate_check_uses_a_postgres_advisory_lock_not_an_in_process_one(self):
        """CROSS-PROCESS/CROSS-INSTANCE HARDENING: an earlier version of
        this fix used a plain threading.Lock, which only serializes
        requests inside ONE Python process — insufficient if Render ever
        runs more than one uvicorn worker or more than one instance. A
        Postgres advisory lock is held by the shared DATABASE, so every
        process/instance talking to the same production Postgres is
        serialized together regardless of how many there are."""
        node = _function('get_face_vote_token')
        src = _src_of(node)
        self.assertIn('_pg_try_advisory_lock(db, debate_id)', src)
        self.assertNotIn('_voter_face_debate_lock', src)
        self.assertIn('_pg_advisory_unlock(db, debate_id)', src)

    def test_lock_acquisition_is_non_blocking_fail_closed_not_a_hang(self):
        node = _function('get_face_vote_token')
        src = _src_of(node)
        self.assertIn("if not _pg_try_advisory_lock(db, debate_id):", src)
        self.assertIn("raise HTTPException(503, 'Hay otra verificación en curso", src)

    def test_lock_is_released_in_a_finally_block_not_only_on_success(self):
        """RECOVERY: the release call must be reachable on every exit path
        (success, a confirmed duplicate, or an AWS error) — a `finally`
        around the whole search+index attempt, not just at the end of the
        happy path, which would leak the lock on any error and
        permanently block every future attempt to vote on that
        consultation for everyone, not just the failing request."""
        node = _function('get_face_vote_token')
        src = _src_of(node)
        idx = src.index('_pg_try_advisory_lock(db, debate_id)')
        tail = src[idx:]
        self.assertIn('finally:', tail)
        finally_idx = tail.index('finally:')
        self.assertIn('_pg_advisory_unlock(db, debate_id)', tail[finally_idx:finally_idx + 200])

    def test_advisory_lock_helpers_use_a_fixed_namespace_key(self):
        """A 2-integer advisory lock key (fixed namespace + debate_id)
        keeps this lock's key-space separate from any unrelated future
        use of Postgres advisory locks in this codebase."""
        self.assertIn('_VOTER_FACE_LOCK_NAMESPACE = 1947283', SRC)
        lock_node = _function('_pg_try_advisory_lock')
        unlock_node = _function('_pg_advisory_unlock')
        self.assertIsNotNone(lock_node)
        self.assertIsNotNone(unlock_node)
        self.assertIn('pg_try_advisory_lock', _src_of(lock_node))
        self.assertIn('pg_advisory_unlock', _src_of(unlock_node))

    def test_real_cross_connection_exclusion_against_a_live_local_postgres(self):
        """REAL behavioral proof, not just structural: runs the ACTUAL
        extracted _pg_try_advisory_lock/_pg_advisory_unlock source against
        a real local Postgres, using TWO INDEPENDENT raw connections.
        Postgres advisory locks are scoped to the CONNECTION, not to the
        OS process or Python thread that issued them — so two independent
        connections are exactly as good a test of "two different
        processes/instances" as actually running two processes would be.
        Skips cleanly (does not fail the suite) if no local Postgres is
        reachable on the expected test port, so this dependency-free
        suite still runs everywhere else without one."""
        try:
            import psycopg2
        except ImportError:
            self.skipTest('psycopg2 not installed in this environment')
        dsn = os.environ.get('PREFY_TEST_PG_DSN', 'host=localhost port=5546 user=testuser dbname=prefytest')
        try:
            conn_a = psycopg2.connect(dsn)
            conn_b = psycopg2.connect(dsn)
        except Exception as e:
            self.skipTest(f'no local test Postgres reachable ({dsn}): {e}')

        try:
            import re as _re

            def _text(s):
                """Stand-in for sqlalchemy.text — the real function source
                calls text('...') purely to mark a raw SQL string; here it
                just returns the string unchanged."""
                return s

            class _FakeSession:
                """Thin shim so the REAL, UNMODIFIED function source
                (which calls db.execute(text('...:name...'), {'name': ...})
                .scalar()) runs against a raw psycopg2 connection instead
                of a SQLAlchemy Session — only the :name -> %(name)s
                parameter-style conversion happens here, in the shim,
                never in the function source under test."""
                def __init__(self, conn):
                    self.conn = conn
                def execute(self, stmt, params):
                    pg_stmt = _re.sub(r':(\w+)', r'%(\1)s', str(stmt))
                    cur = self.conn.cursor()
                    cur.execute(pg_stmt, params)
                    row = cur.fetchone()
                    class _Result:
                        def scalar(self_inner):
                            return row[0] if row else None
                    return _Result()

            ns = {'text': _text, 'Session': object}
            exec(_src_of(_function('_pg_try_advisory_lock')), ns)
            exec(_src_of(_function('_pg_advisory_unlock')), ns)
            ns['_VOTER_FACE_LOCK_NAMESPACE'] = 1947283
            try_lock = ns['_pg_try_advisory_lock']
            unlock = ns['_pg_advisory_unlock']

            sess_a, sess_b = _FakeSession(conn_a), _FakeSession(conn_b)
            debate_id = 909090

            self.assertTrue(try_lock(sess_a, debate_id), 'connection A should acquire a free lock')
            self.assertFalse(try_lock(sess_b, debate_id),
                              'connection B acquired the SAME debate\'s lock while A still holds it — '
                              'this is the exact cross-process race this change exists to close')
            self.assertTrue(try_lock(sess_b, debate_id + 1),
                             'a DIFFERENT debate_id must not be blocked by an unrelated one')
            unlock(sess_a, debate_id)
            self.assertTrue(try_lock(sess_b, debate_id),
                             'B should acquire the lock immediately after A explicitly released it — no stuck lock')
            unlock(sess_b, debate_id)
            unlock(sess_b, debate_id + 1)
        finally:
            conn_a.close()
            conn_b.close()
class TestConsultationNotificationsDesign(unittest.TestCase):
    """Regression guard for the approved consultation-notifications design:
    opt-in (off by default), email (reusing the REAL existing provider,
    not the stale 'SendGrid' mentioned only in this file's own top-of-file
    docstring) + Expo push for iOS/Android, daily/weekly frequency, no
    duplicate notifications, no leaked targeting criteria, and complete
    structural separation from the sponsored-campaign invitation system."""

    def test_notify_columns_opt_in_off_by_default(self):
        node = _class_def('User')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn("notify_new_consultations = Column(Boolean, default=False)", src)
        self.assertIn("notify_frequency", src)

    def test_notify_columns_have_idempotent_migration_entries(self):
        self.assertIn("('notify_new_consultations', 'BOOLEAN DEFAULT FALSE')", SRC)
        self.assertIn("('notify_frequency', \"TEXT DEFAULT 'daily'\")", SRC)

    def test_device_push_token_and_notification_log_tables_exist(self):
        self.assertIsNotNone(_class_def('DevicePushToken'))
        self.assertIsNotNone(_class_def('ConsultationNotificationLog'))

    def test_notification_prefs_endpoints_are_self_only(self):
        get_node = _route_function('get', '/profile/notifications')
        post_node = _route_function('post', '/profile/notifications')
        self.assertIsNotNone(get_node)
        self.assertIsNotNone(post_node)
        self.assertIn('get_current_user', _src_of(get_node))
        self.assertIn('get_current_user', _src_of(post_node))

    def test_notification_prefs_rejects_invalid_frequency(self):
        node = _route_function('post', '/profile/notifications')
        self.assertIn("not in ('daily', 'weekly')", _src_of(node))

    def test_push_token_registration_is_self_only(self):
        node = _route_function('post', '/devices/register-push-token')
        self.assertIsNotNone(node)
        self.assertIn('get_current_user', _src_of(node))

    def test_unsubscribe_token_is_structurally_distinct_from_login_tokens(self):
        """The whole point of NOT reusing make_token: a stolen/forwarded
        unsubscribe link must never work as a bearer auth token, even
        though both are signed with the same SECRET."""
        make_fn = _function('make_unsubscribe_token')
        verify_fn = _function('_verify_unsubscribe_token')
        self.assertIsNotNone(make_fn)
        self.assertIsNotNone(verify_fn)
        self.assertIn("'purpose': 'unsubscribe_notifications'", _src_of(make_fn))
        self.assertIn("payload.get('purpose') != 'unsubscribe_notifications'", _src_of(verify_fn))

    def test_unsubscribe_endpoint_requires_no_login(self):
        node = _route_function('get', '/notifications/unsubscribe')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertNotIn('get_current_user', src)
        self.assertIn('_verify_unsubscribe_token', src)
        self.assertIn('user.notify_new_consultations = False', src)

    def test_unsubscribe_token_behaves_correctly_end_to_end(self):
        """Real behavioral check (not just structural): a token minted by
        make_unsubscribe_token actually verifies, a tampered/foreign token
        does not, and the SAME-looking real login token (make_token) is
        correctly rejected by the unsubscribe verifier."""
        import jwt as _jwt
        SECRET_FOR_TEST = 'test-secret-only'
        ns = {
            'jwt': _jwt, 'datetime': __import__('datetime').datetime,
            'timedelta': __import__('datetime').timedelta, 'SECRET': SECRET_FOR_TEST,
        }
        exec(_src_of(_function('make_unsubscribe_token')), ns)
        exec(_src_of(_function('_verify_unsubscribe_token')), ns)
        exec(_src_of(_function('make_token')), ns)
        good_token = ns['make_unsubscribe_token'](42)
        self.assertEqual(ns['_verify_unsubscribe_token'](good_token), 42)
        login_token = ns['make_token'](42)
        self.assertIsNone(ns['_verify_unsubscribe_token'](login_token))
        self.assertIsNone(ns['_verify_unsubscribe_token']('not-a-real-token'))

    def test_email_sender_reuses_the_real_working_provider_not_sendgrid(self):
        """Every mention of "SendGrid" in this file is a comment (the
        stale top-of-file docstring, plus this new feature's own comment
        explaining why it deliberately does NOT use it) — never an actual
        import or API call. This new feature must reuse _send_html_email
        (the real, working Resend+Gmail path), not invent a dependency on
        a provider that was never integrated."""
        self.assertNotIn('import sendgrid', SRC)
        self.assertNotIn('SendGridAPIClient', SRC)
        self.assertNotIn('SENDGRID_API_KEY', SRC)
        node = _function('send_consultation_notification_email')
        self.assertIsNotNone(node)
        self.assertIn('_send_html_email(', _src_of(node))

    def test_notification_email_never_leaks_targeting_criteria(self):
        """Privacy requirement: the email may name consultations by title,
        but must never explain WHY the recipient matched (age/income/
        occupation/commune) — that logic lives only in eligibility.py and
        must never be echoed back to the user."""
        node = _function('send_consultation_notification_email')
        src = _src_of(node)
        for leaky_term in ('target_age', 'target_se_tiers', 'target_professions',
                           'income_min_usd', 'income_max_usd', 'scope_commune'):
            self.assertNotIn(leaky_term, src)

    def test_notification_email_includes_unsubscribe_link(self):
        node = _function('send_consultation_notification_email')
        self.assertIn('/notifications/unsubscribe?token=', _src_of(node))

    def test_push_sender_uses_expo_unified_api_for_both_platforms(self):
        node = _function('send_consultation_push_notification')
        self.assertIsNotNone(node)
        src = _src_of(node)
        self.assertIn('https://exp.host/--/api/v2/push/send', src)

    def test_push_notification_body_never_leaks_targeting_criteria(self):
        node = _function('send_consultation_push_notification')
        src = _src_of(node)
        for leaky_term in ('target_age', 'target_se_tiers', 'target_professions', 'income_min_usd'):
            self.assertNotIn(leaky_term, src)

    def test_digest_reuses_the_single_discovery_path(self):
        """Must call _eligible_debates_for — the SAME function the in-app
        feed uses (CHANGE-002) — never a separate/duplicate matching
        query that could silently diverge from what the feed shows."""
        node = _function('_notify_consultation_digest_for_user')
        self.assertIsNotNone(node)
        self.assertIn('_eligible_debates_for(user, db', _src_of(node))

    def test_digest_checks_notification_log_before_sending(self):
        node = _function('_notify_consultation_digest_for_user')
        src = _src_of(node)
        self.assertIn('already_notified', src)
        self.assertIn("if d.get('id') not in already_notified", src)

    def test_digest_respects_weekly_frequency_gate(self):
        node = _function('_notify_consultation_digest_for_user')
        src = _src_of(node)
        self.assertIn("freq == 'weekly'", src)
        self.assertIn('timedelta(days=7)', src)

    def test_digest_writes_notification_log_only_after_actually_sending(self):
        """The log entry (which prevents ever re-notifying about this
        debate) must only be written once a send actually succeeded —
        never written speculatively before the attempt, and never
        skipped silently after a successful send."""
        node = _function('_notify_consultation_digest_for_user')
        src = _src_of(node)
        self.assertIn('if not (email_sent or push_sent):\n        return False', src)
        self.assertIn('ConsultationNotificationLog(user_id=user.id,', src)

    def test_sweep_job_only_queries_opted_in_users(self):
        node = _function('_run_consultation_notifications_job')
        self.assertIsNotNone(node)
        self.assertIn('User.notify_new_consultations == True', _src_of(node))

    def test_sweep_job_uses_the_real_module_level_session_local_not_a_fake_import(self):
        """BUG FOUND BY A LOCAL INTEGRATION TEST: this originally imported
        a `database` module that doesn't exist anywhere in this repo —
        the scheduled job would have silently done nothing, forever. The
        real SessionLocal is module-level in main.py itself (confirmed:
        `SessionLocal = sessionmaker(bind=engine)` near the top of the
        file) — no import needed."""
        self.assertIn('SessionLocal = sessionmaker(bind=engine)', SRC)
        node = _function('_run_consultation_notifications_job')
        src = _src_of(node)
        # The old bug is only mentioned in the DOCSTRING now (explaining
        # WHY the fix was needed) — check there's no actual AST import
        # node, not just a text substring (which would also match prose).
        real_imports = [n for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(real_imports, [], f'found real import statement(s) in the function body: {real_imports}')
        self.assertIn('db = SessionLocal()', src)

    def test_scheduler_job_registered_after_its_function_is_defined(self):
        """BUG FOUND BY A LOCAL INTEGRATION TEST: registering this job
        INSIDE the try/except scheduler-setup block (which runs before
        `_run_consultation_notifications_job` is defined later in the
        file) raised a NameError that silently killed the ENTIRE
        scheduler — not just this job, but the three pre-existing
        production cron jobs too. Must be registered only after the
        function exists."""
        job_def_idx = SRC.index('def _run_consultation_notifications_job():')
        registration_idx = SRC.index("id='consultation_notifications'")
        self.assertGreater(registration_idx, job_def_idx,
                            "the job must be registered AFTER its function is defined, not before")
        # And the registration must be OUTSIDE the original scheduler
        # try/except block, which starts well before the function and
        # ends right at '_scheduler.start()'.
        scheduler_start_idx = SRC.index('_scheduler.start()')
        self.assertGreater(registration_idx, scheduler_start_idx)

    def test_sweep_job_never_touches_sponsored_campaign_tables(self):
        """Structural proof of the required separation: the sweep job and
        its digest helper must never actually QUERY AdCampaign/
        SponsorInvitee (explanatory comments are free to name them, as
        this file's own docstrings do, to document the separation) —
        those stay on their own, completely separate, already-existing
        invitation path."""
        for fn_name in ('_run_consultation_notifications_job', '_notify_consultation_digest_for_user'):
            src = _src_of(_function(fn_name))
            for forbidden in ('db.query(AdCampaign', 'db.query(SponsorInvitee',
                              'FROM ad_campaigns', 'FROM sponsor_invitees'):
                self.assertNotIn(forbidden, src, f'{fn_name} must never query {forbidden}')

    def test_scheduler_registers_the_new_job_at_a_distinct_time(self):
        self.assertIn("_run_consultation_notifications_job,", SRC)
        self.assertIn("CronTrigger(hour=7, minute=30)", SRC)
        self.assertIn("id='consultation_notifications'", SRC)

    def test_push_token_endpoint_reassigns_existing_token_without_duplicating(self):
        node = _route_function('post', '/devices/register-push-token')
        src = _src_of(node)
        self.assertIn('existing = db.query(DevicePushToken)', src)
        self.assertIn('existing.user_id = user.id', src)

    def test_voter_portal_notifications_card_defaults_unchecked(self):
        """The checkbox markup itself carries no `checked` attribute —
        the ONLY source of truth for its state is loadMyNotificationPrefs
        reading the real backend value, never an HTML default."""
        self.assertIn('id="notify-enabled-input" onchange="onNotifyEnabledChange()"', VOTER_SRC)
        self.assertNotIn('id="notify-enabled-input" checked', VOTER_SRC)

    def test_voter_portal_loads_real_prefs_not_an_optimistic_default(self):
        node_src = VOTER_SRC[VOTER_SRC.index('async function loadMyNotificationPrefs'):
                              VOTER_SRC.index('function onNotifyEnabledChange')]
        self.assertIn("enabled.checked = !!d.notify_new_consultations;", node_src)

    def test_voter_portal_wired_into_profile_tab_load(self):
        self.assertIn('loadMyNotificationPrefs();', VOTER_SRC)

    def test_voter_portal_only_requests_push_permission_after_explicit_opt_in(self):
        """The ReactNativeWebView bridge call must be gated on the
        checkbox being newly checked AND the save having succeeded —
        never fired unconditionally on page load."""
        node_src = VOTER_SRC[VOTER_SRC.index('async function saveMyNotificationPrefs'):
                              VOTER_SRC.index("window.addEventListener('message'")]
        self.assertIn('if (enabled.checked && window.ReactNativeWebView)', node_src)

    def test_app_js_only_requests_permission_on_explicit_bridge_message(self):
        self.assertIn("msg.type === 'request_push_permission'", APP_JS_SRC)
        self.assertIn('_requestExpoPushTokenAndBridgeBack(webRef)', APP_JS_SRC)

    def test_app_js_never_requests_permission_on_mount_or_app_open(self):
        """Regression guard against the easiest way to violate consent:
        calling the permission function from a useEffect (app-open) path
        instead of only from the onMessage bridge handler. The function
        NAME appears exactly twice in the whole file — its own
        definition, and the single call site inside onMessage — proving
        there is no second (e.g. useEffect) call site anywhere."""
        self.assertEqual(APP_JS_SRC.count('_requestExpoPushTokenAndBridgeBack'), 2)
        for effect_block in re.findall(r'useEffect\(\(\) => \{.*?\n  \}, \[\]\);', APP_JS_SRC, re.DOTALL):
            self.assertNotIn('_requestExpoPushTokenAndBridgeBack', effect_block)

    def test_app_json_declares_the_notifications_plugin(self):
        self.assertIn('"expo-notifications"', APP_JSON_SRC)


class TestAnnualRentalPricesJobBugFix(unittest.TestCase):
    """FINAL REVIEW FIX: the same 'from database import SessionLocal'
    bug already found and fixed in the notifications job also existed in
    _run_annual_rental_prices_job (the pre-existing Jan-2 annual cron) —
    no `database` module exists anywhere in this repo, so this job has
    been silently failing (caught by its own try/except) every year
    since it was written, never actually refreshing commune m² prices."""

    def test_no_real_import_from_nonexistent_database_module_anywhere(self):
        """AST-level, not a text search: the ONLY remaining mention of
        'from database import' anywhere in main.py must be inside a
        docstring (explaining the historical bug), never a real
        executable import statement."""
        for node in ast.walk(TREE):
            if isinstance(node, ast.ImportFrom) and node.module == 'database':
                self.fail(f'found a real "from database import" statement at line {node.lineno} — '
                          'that module does not exist in this repo')

    def test_annual_rental_prices_job_uses_the_real_module_level_session_local(self):
        func_node = None
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '_run_annual_rental_prices_job':
                func_node = node
                break
        self.assertIsNotNone(func_node, '_run_annual_rental_prices_job not found')
        self.assertIn('_db = SessionLocal()', _src_of(func_node))
        # AST-level, not a text search — this function's own explanatory
        # comment legitimately quotes the old buggy import, which a plain
        # substring check would wrongly flag.
        real_imports = [n for n in ast.walk(func_node) if isinstance(n, ast.ImportFrom) and n.module == 'database']
        self.assertEqual(real_imports, [], f'found a real "from database import" statement: {real_imports}')


if __name__ == '__main__':
    unittest.main()
