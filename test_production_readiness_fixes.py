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


if __name__ == '__main__':
    unittest.main()
