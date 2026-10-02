"""
test_jc_demo_account.py — JC live-demo account regression suite.

Covers the extension of the existing Google Play Full Review demo
architecture (GOOGLE_PLAY_FULL_REVIEW_EMAIL / _is_google_full_review_account)
to also admit JC's live-demo account (JC_FULL_DEMO_EMAIL /
_is_jc_full_demo_account) for ELEVATED CREATION/VISIBILITY AUTHORIZATION
ONLY, via a shared _is_full_demo_account() helper — without ever mutating
User.role, without weakening authorization for any other account, and
WITHOUT giving JC the Google Play reviewer's demo/no-write VOTING
behavior. JC's own votes must use the exact same real, persisting path
as any ordinary user; only the Google Play reviewer gets simulated,
non-counted votes. These two concerns are deliberately split across two
different predicates at the vote-branch call site — this suite proves
that split is real, not just documented.

STRUCTURAL tests (parse main.py's AST; no imports, no database, no AWS
key needed — main.py cannot even be imported in this dev environment,
missing boto3/twilio/sendgrid/stripe/cloudinary) prove the wiring is
actually in place and that User.role is never assigned inside the three
login endpoints that grant the override. BEHAVIOURAL tests exec the real,
extracted predicate-function source (not a hand-retyped copy) so drift
between this test and the committed code is impossible.

Run:
    python3 -m unittest test_jc_demo_account -v
"""

import ast
import unittest
from pathlib import Path

MAIN = Path(__file__).with_name('main.py')
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)


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


def _assigns_role(node) -> bool:
    """True if `node`'s body contains an assignment to some_name.role —
    i.e. a persisted User.role mutation (the thing requirement #5
    forbids for the demo-account branch of these specific functions)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Attribute) and target.attr == 'role':
                    return True
    return False


def _exec_function_source(name, extra_names=()):
    """Extract a top-level function's exact source from the real
    committed main.py and exec it in an isolated namespace — the
    behavioural tests below run against the ACTUAL code, never a
    hand-retyped stand-in that could silently drift from it."""
    node = _function(name)
    assert node is not None, f'{name} not found in main.py'
    ns = {}
    for extra in extra_names:
        extra_node = _function(extra) if not extra.isupper() else None
        if extra_node is not None:
            exec(compile(ast.Module(body=[extra_node], type_ignores=[]), '<extract>', 'exec'), ns)
    # Also pull in any UPPER_CASE module-level constant the function references.
    exec(_src_of(node), ns)
    return ns[name]


def _module_level_constant(name):
    for node in TREE.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            return ast.literal_eval(node.value)
    return None


# ═══════════════════════════════════════════════════════════════════════
# Behavioural — real extracted predicate functions
# ═══════════════════════════════════════════════════════════════════════

class TestPredicatesExtracted(unittest.TestCase):

    def setUp(self):
        ns = {}
        for name in ('GOOGLE_PLAY_FULL_REVIEW_EMAIL', 'JC_FULL_DEMO_EMAIL'):
            ns[name] = _module_level_constant(name)
        exec(_src_of(_function('_is_google_full_review_account')), ns)
        exec(_src_of(_function('_is_jc_full_demo_account')), ns)
        exec(_src_of(_function('_is_full_demo_account')), ns)
        self.is_google_review   = ns['_is_google_full_review_account']
        self.is_jc_demo         = ns['_is_jc_full_demo_account']
        self.is_full_demo       = ns['_is_full_demo_account']
        self.jc_email           = ns['JC_FULL_DEMO_EMAIL']
        self.google_email       = ns['GOOGLE_PLAY_FULL_REVIEW_EMAIL']

    def test_jc_email_is_exactly_the_requested_account(self):
        self.assertEqual(self.jc_email, 'jucaferla24649@gmail.com')

    def test_jc_and_google_emails_stay_distinct_constants(self):
        self.assertNotEqual(self.jc_email, self.google_email)

    def test_is_jc_demo_account_matches_case_and_whitespace_insensitively(self):
        self.assertTrue(self.is_jc_demo('jucaferla24649@gmail.com'))
        self.assertTrue(self.is_jc_demo('JUCAFERLA24649@GMAIL.COM'))
        self.assertTrue(self.is_jc_demo('  jucaferla24649@gmail.com  '))

    def test_is_jc_demo_account_false_for_everything_else(self):
        self.assertFalse(self.is_jc_demo(self.google_email))
        self.assertFalse(self.is_jc_demo('some.voter@example.com'))
        self.assertFalse(self.is_jc_demo(''))
        self.assertFalse(self.is_jc_demo(None))

    def test_is_google_review_unaffected_by_jc_email(self):
        """The Google Play reviewer predicate must not have been widened —
        it still recognizes only its own account."""
        self.assertTrue(self.is_google_review(self.google_email))
        self.assertFalse(self.is_google_review(self.jc_email))

    def test_is_full_demo_account_covers_both_and_only_both(self):
        self.assertTrue(self.is_full_demo(self.jc_email))
        self.assertTrue(self.is_full_demo(self.google_email))
        self.assertFalse(self.is_full_demo('some.voter@example.com'))
        self.assertFalse(self.is_full_demo(''))
        self.assertFalse(self.is_full_demo(None))

    def test_legacy_otp_skip_set_is_untouched(self):
        """APP_REVIEW_DEMO_EMAILS (OTP-skip only) must not have grown a
        new member as a side effect of this change — JC's account was
        never added to it, and the legacy accounts in it must still be
        structurally unable to reach full-demo capabilities (proven
        separately below: they use a different predicate entirely)."""
        legacy_set = _module_level_constant('APP_REVIEW_DEMO_EMAILS')
        self.assertEqual(
            legacy_set,
            {'jucaferla@gmail.com', 'chatgpt.auditor@preferendum.com', 'googleplay.reviewer@preferendum.com'},
        )
        self.assertNotIn('jucaferla24649@gmail.com', legacy_set)

    def test_vote_gate_predicate_distinguishes_jc_from_google_reviewer(self):
        """Direct behavioural proof, using the real extracted
        _is_google_full_review_account function (the exact predicate the
        demo-vote branch in _cast_vote_inner is gated on, per the
        structural test above): it returns True for the Google Play
        reviewer and False for JC. Combined with the structural proof
        that the branch uses this predicate (not _is_full_demo_account),
        this proves JC's votes fall through to the real, persisting
        path while the reviewer's still don't."""
        self.assertTrue(self.is_google_review(self.google_email))
        self.assertFalse(self.is_google_review(self.jc_email))


# ═══════════════════════════════════════════════════════════════════════
# Structural — prove the wiring is real and User.role is never mutated
# ═══════════════════════════════════════════════════════════════════════

LOGIN_ROUTES = [
    ('post', '/organizers/login'),
    ('post', '/organizer/login'),
    ('post', '/marketer/login'),
]


class TestLoginEndpointsWired(unittest.TestCase):

    def test_each_login_route_exists_and_calls_is_full_demo_account(self):
        for method, path in LOGIN_ROUTES:
            node = _route_function(method, path)
            self.assertIsNotNone(node, f'{method.upper()} {path} not found')
            self.assertIn('_is_full_demo_account', _calls_in(node),
                           f'{method.upper()} {path} does not call _is_full_demo_account')

    def test_each_login_route_never_assigns_user_role(self):
        """Requirement #5 — stored User.role is not mutated by switching
        modes. The demo-account override must work purely through the
        JWT's own role claim (make_token's role argument), never by
        writing to the ORM object's .role attribute (which a later
        db.commit() in the SAME request would persist)."""
        for method, path in LOGIN_ROUTES:
            node = _route_function(method, path)
            self.assertFalse(_assigns_role(node),
                              f'{method.upper()} {path} assigns .role — would persist a role mutation')

    def test_each_login_route_still_requires_db_role_for_non_demo_accounts(self):
        """No global bypass: the 403/401 guard must still reference the
        real DB role check (role != 'organizer', role not in (...), etc.)
        for a non-demo account — i.e. is_demo only ever widens, never
        replaces, the original guard."""
        for method, path in LOGIN_ROUTES:
            src = _src_of(_route_function(method, path))
            self.assertIn('user.role', src, f'{method.upper()} {path} lost its DB-role check entirely')
            self.assertIn('is_demo', src, f'{method.upper()} {path} lost the is_demo guard')


class TestEligibilityAndVotingAndCampaignAuthority(unittest.TestCase):

    def test_consultation_decision_calls_full_demo_helper(self):
        node = _function('_consultation_decision')
        self.assertIsNotNone(node)
        self.assertIn('_is_full_demo_account', _calls_in(node))

    def test_campaign_eligibility_calls_full_demo_helper(self):
        # The campaign-for-user eligibility adapter (STEP-13-era docstring
        # calls it out explicitly as the Google-reviewer content-visibility
        # exception); locate it by its distinctive call signature instead
        # of a brittle exact name.
        found = False
        for node in ast.walk(TREE):
            if isinstance(node, ast.FunctionDef) and 'evaluate_campaign_for_user_in_consultation' in _calls_in(node):
                if '_is_full_demo_account' in _calls_in(node):
                    found = True
        self.assertTrue(found, 'campaign eligibility adapter does not call _is_full_demo_account')

    def test_cast_vote_demo_branch_gated_only_on_google_review_not_jc(self):
        # The route is a thin wrapper; the real logic (and the demo-vote
        # branch) lives in _cast_vote_inner.
        node = _function('_cast_vote_inner')
        self.assertIsNotNone(node)
        src = _src_of(node)
        # The demo/no-write vote branch must be gated EXCLUSIVELY on
        # _is_google_full_review_account — never on _is_full_demo_account
        # (which would also match JC) and never on _is_jc_full_demo_account
        # directly. JC gets elevated creation authority but votes for real.
        self.assertIn('_is_google_full_review_account(user.email)', src)
        self.assertNotIn('_is_full_demo_account(user.email)', src)
        self.assertNotIn('_is_jc_full_demo_account', src)
        # The demo-vote branch must never also commit a real vote —
        # i.e. no db.commit() call textually inside the demo return block.
        # We check this by finding the
        # `if _is_google_full_review_account(user.email):` If-node and
        # confirming its own body has no Call to db.commit.
        demo_if = None
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                test_src = ast.get_source_segment(SRC, sub.test) or ''
                if '_is_google_full_review_account(user.email)' in test_src and 'user.role' not in test_src:
                    demo_if = sub
                    break
        self.assertIsNotNone(demo_if, 'could not locate the demo-vote if-branch')
        demo_calls = set()
        for sub in ast.walk(demo_if):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Attribute):
                    demo_calls.add(f.attr)
        self.assertNotIn('commit', demo_calls, 'demo-vote branch must never call db.commit()')

    def test_campaign_authority_demo_branch_never_writes_marketer_profile(self):
        node = _function('_require_campaign_authority')
        self.assertIsNotNone(node)
        demo_if = None
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                test_src = ast.get_source_segment(SRC, sub.test) or ''
                if '_is_full_demo_account' in test_src:
                    demo_if = sub
                    break
        self.assertIsNotNone(demo_if)
        demo_calls = _calls_in(demo_if)
        self.assertNotIn('add', demo_calls, 'demo branch must not create a MarketerProfile row')
        self.assertNotIn('commit', demo_calls, 'demo branch must not commit anything')

    def test_match_campaigns_matching_engine_has_no_demo_account_knowledge(self):
        """Campaign targeting/delivery as seen by ORDINARY voters (and by
        JC's audience during a real presentation) must be completely
        unaffected by this change — the matching engine itself must not
        know about either allowlisted email at all. Only CREATION
        authority (_require_campaign_authority) and the two visibility
        exceptions are allowed to reference the demo helpers; the engine
        that decides which campaigns a real voter actually sees must not."""
        node = _function('_match_campaigns')
        self.assertIsNotNone(node)
        src = _src_of(node)
        for needle in ('_is_full_demo_account', '_is_jc_full_demo_account',
                       '_is_google_full_review_account', 'JC_FULL_DEMO_EMAIL'):
            self.assertNotIn(needle, src, f'{needle!r} leaked into the campaign matching engine')

    def test_debate_discovery_has_no_creator_or_demo_account_special_casing(self):
        """A consultation JC creates must be discoverable by a normal
        eligible voter exactly like any other consultation — _eligible_
        debates_for must not filter by creator identity or reference
        either allowlisted email anywhere."""
        node = _function('_eligible_debates_for')
        self.assertIsNotNone(node)
        src = _src_of(node)
        for needle in ('creator_id ==', 'creator_id !=', '_is_full_demo_account',
                       '_is_jc_full_demo_account', 'JC_FULL_DEMO_EMAIL',
                       'GOOGLE_PLAY_FULL_REVIEW_EMAIL'):
            self.assertNotIn(needle, src, f'{needle!r} found in consultation discovery — would special-case by creator/account')


class TestNoGlobalBypassInCanonicalEvaluator(unittest.TestCase):

    def test_eligibility_module_never_references_demo_accounts(self):
        """The dependency-free canonical evaluator (eligibility.py),
        applied to EVERY account unconditionally, must have no knowledge
        of JC's or the Google reviewer's email at all — the allowlist
        exists only in main.py's adapter layer, never in the universal
        evaluator. This is what makes 'no global authorization bypass
        exists' true structurally, not just by convention."""
        elig_src = Path(__file__).with_name('eligibility.py').read_text(encoding='utf-8')
        for needle in ('jucaferla24649', 'googleplay.reviewer', 'JC_FULL_DEMO',
                       'GOOGLE_PLAY_FULL_REVIEW', '_is_full_demo_account'):
            self.assertNotIn(needle, elig_src, f'{needle!r} leaked into the canonical evaluator')

    def test_ordinary_account_is_unaffected(self):
        """A plain unittest.mock-free behavioural check: for any email
        that is neither allowlist, is_full_demo_account (real extracted
        function) returns False, so every 'and not is_demo' / 'or
        _is_full_demo_account(...)' guard falls through to the exact
        same original check ordinary users have always faced."""
        ns = {'GOOGLE_PLAY_FULL_REVIEW_EMAIL': _module_level_constant('GOOGLE_PLAY_FULL_REVIEW_EMAIL'),
              'JC_FULL_DEMO_EMAIL': _module_level_constant('JC_FULL_DEMO_EMAIL')}
        exec(_src_of(_function('_is_google_full_review_account')), ns)
        exec(_src_of(_function('_is_jc_full_demo_account')), ns)
        exec(_src_of(_function('_is_full_demo_account')), ns)
        for ordinary_email in ('voter1@example.com', 'another.citizen@test.org', 'admin@preferendum.com'):
            self.assertFalse(ns['_is_full_demo_account'](ordinary_email))


class TestNoSecretsInSource(unittest.TestCase):

    def test_no_password_or_token_literal_near_new_constants(self):
        """The only new literal introduced by this change is an email
        address (not a secret) — JC_FULL_DEMO_EMAIL. Scan the whole file
        for anything that looks like a hardcoded password/token/AWS key
        sitting next to the new constant/predicate block."""
        start = SRC.index('JC_FULL_DEMO_EMAIL')
        end = SRC.index('def _is_full_demo_account')
        window = SRC[start:end]
        for forbidden in ('password=', "password '", 'AKIA', 'secret=', 'Bearer ey'):
            self.assertNotIn(forbidden, window)

    def test_jc_demo_email_constant_has_no_password_assigned_alongside_it(self):
        node_src = SRC
        self.assertNotIn("JC_FULL_DEMO_EMAIL = 'jucaferla24649@gmail.com'\nJC_", node_src)


if __name__ == '__main__':
    unittest.main()
