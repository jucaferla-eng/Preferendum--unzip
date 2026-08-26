"""
test_matching_wiring.py — CHANGE-002 endpoint-wiring guards.

STRUCTURAL tests: they parse main.py and assert that every consultation and
campaign path is wired to the canonical evaluator, that each Phase-0 bypass is
gone, and that no campaign mutation route is reachable without authorization.

They need no database and no application dependencies, so they stay runnable
even where main.py cannot be imported.

They are deliberately narrow — a structural test proves "the weaker code is not
present and the canonical call is present", not "the endpoint returns 403".
Behavioural coverage of the decision itself lives in test_eligibility.py, and
end-to-end HTTP coverage in test_integration_http.py.

Their distinct value is catching a NEW unguarded route that nobody wrote a
behavioural test for.

Run:
    python3 -m unittest test_matching_wiring -v
"""

import ast
import re
import unittest
from pathlib import Path

MAIN = Path(__file__).with_name('main.py')
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _route_functions():
    """{(method, path): FunctionDef} for every @app.<method>('<path>') route."""
    out = {}
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == 'app'):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            out[(fn.attr, dec.args[0].value)] = node
    return out


ROUTES = _route_functions()


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


def _dependency_names(node) -> set:
    """Names used inside Depends(...) in the signature."""
    out = set()
    for arg in list(node.args.args) + list(node.args.kwonlyargs):
        pass
    for default in list(node.args.defaults) + list(node.args.kw_defaults or []):
        if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) \
                and default.func.id == 'Depends':
            for a in default.args:
                if isinstance(a, ast.Name):
                    out.add(a.id)
                elif isinstance(a, ast.Attribute):
                    out.add(a.attr)
    return out


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ═══════════════════════════════════════════════════════════════════════
# 26/31. Consultation paths are authenticated and canonical
# ═══════════════════════════════════════════════════════════════════════

AUTH_DEPS = {'get_current_user', 'get_verified_user'}

# Every route that exposes consultation existence or content to an end user.
CONSULTATION_READ_ROUTES = [
    ('get', '/debates'),
    ('get', '/debates/feed'),
    ('get', '/debates/for-me'),
    ('get', '/debates/{debate_id}'),
    ('get', '/debates/{debate_id}/opinions'),
    ('get', '/debates/{debate_id}/comments'),
]

CANONICAL_CALLS = {
    '_eligible_debates_for',
    '_require_consultation_access',
    '_user_may_see_consultation',
    '_consultation_decision',
    'evaluate_consultation',
}

# Any of these means "the canonical campaign evaluator decided this".
CANONICAL_CAMPAIGN_CALLS = {
    '_campaign_decision',
    'evaluate_campaign_for_user_in_consultation',
    'evaluate_campaign',
}


class TestConsultationWiring(unittest.TestCase):

    def test_31_consultation_routes_require_authentication(self):
        """Rule 2: unauthenticated users must not see consultations."""
        for method, path in CONSULTATION_READ_ROUTES:
            fn = ROUTES.get((method, path))
            self.assertIsNotNone(fn, f'route {method.upper()} {path} disappeared')
            deps = _dependency_names(fn)
            self.assertTrue(
                deps & AUTH_DEPS,
                f'{method.upper()} {path} does not require an authenticated user '
                f'(deps={sorted(deps)})')

    def test_26_consultation_routes_consume_the_canonical_evaluator(self):
        """Rules 3/4: every discovery and access path uses the one evaluator."""
        for method, path in CONSULTATION_READ_ROUTES:
            fn = ROUTES[(method, path)]
            calls = _calls_in(fn)
            self.assertTrue(
                calls & CANONICAL_CALLS,
                f'{method.upper()} {path} does not call the canonical evaluator '
                f'(calls={sorted(calls)})')

    def test_04_vote_endpoint_reevaluates_eligibility(self):
        """Rule 4: the vote path independently re-evaluates, server-side."""
        fn = _function('_cast_vote_inner')
        self.assertIsNotNone(fn)
        self.assertIn('_consultation_decision', _calls_in(fn),
                      'vote endpoint must call the canonical evaluator')
        body = _src_of(fn)
        self.assertIn('.allowed', body)
        self.assertRegex(body, r'if not _decision\.allowed',
                         'vote must deny when the canonical decision is not allowed')

    def test_vote_eligibility_runs_before_the_vote_is_written(self):
        body = _src_of(_function('_cast_vote_inner'))
        self.assertLess(body.index('_consultation_decision'), body.index('db.add(vote)'),
                        'eligibility must be re-checked BEFORE the vote is recorded')

    def test_discovery_does_not_filter_on_client_supplied_geography(self):
        """The old feed filtered on a client-supplied `country` query param."""
        for method, path in [('get', '/debates'), ('get', '/debates/feed'),
                             ('get', '/debates/for-me')]:
            fn = ROUTES[(method, path)]
            arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
            for banned in ('country', 'commune', 'county'):
                self.assertNotIn(
                    banned, arg_names,
                    f'{method.upper()} {path} still accepts client-supplied {banned!r}')


# ═══════════════════════════════════════════════════════════════════════
# 24. target_debate_ids bypass regression
# ═══════════════════════════════════════════════════════════════════════

class TestCampaignBypassRegression(unittest.TestCase):

    def test_24_match_campaigns_has_no_pinned_short_circuit(self):
        """Phase 0 G-8: _match_campaigns returned pinned campaigns before any
        filter ran. There must be no early `return` guarded by
        target_debate_ids anywhere in the function."""
        fn = _function('_match_campaigns')
        self.assertIsNotNone(fn)
        body = _src_of(fn)
        # Locate every `return` and ensure none of them sits inside a block
        # that mentions target_debate_ids before the eligibility call.
        elig_pos = min(body.index(n) for n in CANONICAL_CAMPAIGN_CALLS if n in body)
        for m in re.finditer(r'^\s*return\s', body, re.M):
            if m.start() < elig_pos:
                self.fail('_match_campaigns returns before canonical eligibility '
                          f'runs, at offset {m.start()}')
        self.assertNotIn('pinned_orm', body,
                         'the pinned short-circuit variable is still present')

    def test_24b_match_campaigns_calls_canonical_evaluator(self):
        fn = _function('_match_campaigns')
        self.assertTrue(_calls_in(fn) & CANONICAL_CAMPAIGN_CALLS,
                        '_match_campaigns must decide eligibility canonically')

    def test_24c_auto_pin_on_campaign_creation_removed(self):
        """/marketer/campaigns pinned every new campaign to all live debates."""
        fn = ROUTES.get(('post', '/marketer/campaigns'))
        self.assertIsNotNone(fn)
        body = _src_of(fn)
        self.assertNotIn('campaign.target_debate_ids =', body,
                         'campaign creation still auto-pins')

    def test_24d_eligibility_snapshot_cannot_see_association(self):
        """Structural: the campaign eligibility snapshot has no field through
        which association could influence the decision."""
        import eligibility as E
        self.assertNotIn('target_debate_ids', E.CampaignTarget.__slots__)
        self.assertNotIn('target_debate_ids', E.ConsultationTarget.__slots__)


# ═══════════════════════════════════════════════════════════════════════
# 25. Campaign-serving paths are consistent
# ═══════════════════════════════════════════════════════════════════════

CAMPAIGN_SERVING_ROUTES = [
    ('get', '/ads/featured'),
    ('get', '/debates/{debate_id}/opinions'),
    ('post', '/ads/view'),
]


class TestCampaignServingWiring(unittest.TestCase):

    def test_25_every_serving_path_uses_the_canonical_decision(self):
        for method, path in CAMPAIGN_SERVING_ROUTES:
            fn = ROUTES.get((method, path))
            self.assertIsNotNone(fn, f'{method.upper()} {path} disappeared')
            calls = _calls_in(fn)
            self.assertTrue(
                calls & (CANONICAL_CAMPAIGN_CALLS | {'_match_campaigns'}),
                f'{method.upper()} {path} serves ads without the canonical '
                f'decision (calls={sorted(calls)})')

    def test_opinions_prepend_bypass_removed(self):
        """Phase 0 G-9: an unfiltered 'prepend recent campaigns' block."""
        fn = ROUTES[('get', '/debates/{debate_id}/opinions')]
        body = _src_of(fn)
        self.assertNotIn('prepend', body.replace('prepend" ELIMINADO', ''),
                         'the prepend bypass block is still present')
        self.assertNotIn('matched = prepend + matched', body)

    def test_ads_view_requires_auth_and_eligibility(self):
        """Phase 0 G-12: anonymous, untargeted, budget-debiting endpoint."""
        fn = ROUTES[('post', '/ads/view')]
        self.assertTrue(_dependency_names(fn) & AUTH_DEPS,
                        '/ads/view must require an authenticated user')
        self.assertTrue(_calls_in(fn) & CANONICAL_CAMPAIGN_CALLS)

    def test_ads_view_does_not_trust_client_demographics(self):
        body = _src_of(ROUTES[('post', '/ads/view')])
        for banned in ('gender      = data.gender', 'county      = data.county',
                       'country     = data.country'):
            self.assertNotIn(banned, body,
                             '/ads/view still records client-supplied demographics')


# ═══════════════════════════════════════════════════════════════════════
# 29/30. Results visibility
# ═══════════════════════════════════════════════════════════════════════

RESULTS_ROUTES = [
    ('get', '/r/{debate_id}'),
    ('get', '/debates/{debate_id}/results'),
    ('get', '/pilot/{debate_id}/live'),
]


class TestResultsVisibility(unittest.TestCase):

    def test_29_restricted_results_are_authorized_server_side(self):
        for method, path in RESULTS_ROUTES:
            fn = ROUTES.get((method, path))
            self.assertIsNotNone(fn, f'{method.upper()} {path} disappeared')
            self.assertIn('_may_see_results', _calls_in(fn),
                          f'{method.upper()} {path} does not enforce results visibility')

    def test_30_creator_and_admin_retain_access(self):
        fn = _function('_may_see_results')
        self.assertIsNotNone(fn)
        body = _src_of(fn)
        self.assertIn("'admin'", body, 'admin access must be preserved')
        self.assertIn('creator_id', body, 'creator access must be preserved')
        self.assertIn("'restricted'", body)

    def test_pilot_dashboard_no_longer_treats_id_as_a_token(self):
        body = _src_of(ROUTES[('get', '/pilot/{debate_id}/live')])
        self.assertNotIn('No auth required', body)


# ═══════════════════════════════════════════════════════════════════════
# 17/18. Closed list is enforced
# ═══════════════════════════════════════════════════════════════════════

class TestClosedListWiring(unittest.TestCase):

    def test_closed_list_is_read_not_just_written(self):
        """Phase 0 G-7: closed_list_entries was write-only."""
        fn = _function('_is_closed_list_member')
        self.assertIsNotNone(fn, 'closed-list membership resolver missing')
        self.assertIn('ClosedListEntry', _src_of(fn))

    def test_consultation_decision_resolves_membership(self):
        body = _src_of(_function('_consultation_decision'))
        self.assertIn('_is_closed_list_member', body)
        self.assertIn('is_closed_list', body)

    def test_upload_marks_the_consultation_as_closed_list(self):
        fn = ROUTES.get(('post', '/organizer/closed-list'))
        self.assertIsNotNone(fn)
        self.assertIn('is_closed_list = True', _src_of(fn))

    def test_migration_backfills_existing_closed_lists(self):
        self.assertIn('UPDATE debates SET is_closed_list = TRUE', SRC)


# ═══════════════════════════════════════════════════════════════════════
# No weaker evaluator remains reachable
# ═══════════════════════════════════════════════════════════════════════

class TestNoWeakerPathRemains(unittest.TestCase):

    RETIRED = ['_tier_matches', '_normalize_gender']

    def test_superseded_matchers_are_gone(self):
        defined = {n.name for n in ast.walk(TREE)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in self.RETIRED:
            self.assertNotIn(name, defined,
                             f'{name} still exists and could be used as a weaker evaluator')

    def test_dead_router_modules_deleted(self):
        for fname in ['ad_matching_engine.py', 'routes_debate.py',
                      'routes_distribute_ads.py', 'vote_routes 2.py',
                      'models.py', 'db.py', 'results_router.py']:
            self.assertFalse(Path(__file__).with_name(fname).exists(),
                             f'{fname} still present — a weaker matcher remains on disk')

    def test_targeting_agent_legacy_entrypoint_not_used_by_main(self):
        """The legacy entrypoint selected columns that do not exist in the live
        schema (cpm, remaining_budget, status, min_income_tier). It must not be
        called from main.py, and must not exist at all."""
        called = set()
        for sub in ast.walk(TREE):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
        self.assertNotIn('match_campaigns_to_debate', called,
                         'main.py still calls the legacy targeting_agent entrypoint')
        imported = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.ImportFrom) and node.module == 'targeting_agent':
                imported |= {a.name for a in node.names}
        self.assertNotIn('match_campaigns_to_debate', imported,
                         'main.py still imports the legacy entrypoint')

    def test_targeting_agent_legacy_entrypoint_deleted(self):
        ta = ast.parse(Path(__file__).with_name('targeting_agent.py').read_text(encoding='utf-8'))
        defined = {n.name for n in ast.walk(ta)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn('match_campaigns_to_debate', defined,
                         'the legacy campaign matcher still exists in targeting_agent.py')

    def test_canonical_module_is_dependency_free(self):
        """eligibility.py must stay importable without fastapi/sqlalchemy so it
        can never acquire a hidden request/DB dependency."""
        tree = ast.parse(Path(__file__).with_name('eligibility.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        forbidden = {'fastapi', 'sqlalchemy', 'main', 'boto3', 'web3', 'pydantic'}
        self.assertFalse(imported & forbidden,
                         f'eligibility.py must not import {sorted(imported & forbidden)}')


# ═══════════════════════════════════════════════════════════════════════
# Persistence: targeting the consultant sets must actually be stored
# ═══════════════════════════════════════════════════════════════════════

class TestPersistence(unittest.TestCase):

    def test_consultation_creation_persists_shared_vocabulary(self):
        """All three creation paths must store the same targeting fields."""
        self.assertEqual(SRC.count("target_professions=getattr(data"), 3)
        self.assertEqual(SRC.count("is_closed_list=bool(getattr(data"), 3)
        self.assertEqual(SRC.count("income_min_usd=getattr(data"), 3,
                         '/organizer/consultations used to drop income targeting')

    def test_campaign_creation_persists_income_and_frequency(self):
        fn = ROUTES.get(('post', '/advertiser/campaigns'))
        body = _src_of(fn)
        for field in ('target_income_min', 'target_income_max', 'frequency_cap'):
            self.assertIn(field, body, f'/advertiser/campaigns drops {field}')

    def test_marketer_campaign_persists_hnw(self):
        body = _src_of(ROUTES[('post', '/marketer/campaigns')])
        for field in ('target_hnw_only', 'min_hnw_score'):
            self.assertIn(field, body, f'/marketer/campaigns drops {field}')

    def test_hnw_columns_declared_on_user_model(self):
        """Phase 0 G-14: columns existed in the DB but not on the ORM class, so
        every hasattr-guarded write silently did nothing."""
        for cls in ast.walk(TREE):
            if isinstance(cls, ast.ClassDef) and cls.name == 'User':
                assigned = {t.id for n in cls.body if isinstance(n, ast.Assign)
                            for t in n.targets if isinstance(t, ast.Name)}
                for col in ('hnw_score', 'verified_hnw', 'hnw_source'):
                    self.assertIn(col, assigned, f'User.{col} not declared')
                return
        self.fail('User model not found')

    def test_hnw_score_is_persisted_by_tier_assignment(self):
        body = _src_of(_function('_assign_user_tier'))
        self.assertIn('hnw_score=:hnw', body)

    def test_hnw_behaviour_signal_uses_the_real_column(self):
        """debate_votes has voter_id, not user_id — the old query always raised."""
        body = _src_of(_function('_calculate_hnw_score'))
        self.assertIn('v.voter_id = :uid', body)
        self.assertNotIn('v.user_id = :uid', body)


# ═══════════════════════════════════════════════════════════════════════
# Campaign authorization (CHANGE-002 phase 2)
#
# JC: ANONYMOUS USERS MAY NOT CREATE OR ACTIVATE REAL CAMPAIGNS, and being
# authenticated must not let you touch someone else's campaign.
#
# The behavioural proof lives in test_integration_http.py (real HTTP). These
# structural guards exist for a different job: they FAIL WHEN A NEW campaign
# mutation route is added without a guard, which a behavioural suite cannot
# notice because nobody thought to write a test for the new route.
# ═══════════════════════════════════════════════════════════════════════

# Routes that create/modify/activate a REAL Preferendum ad campaign, or move
# its money. Admin-secret routes are listed separately below.
CAMPAIGN_MUTATION_ROUTES = [
    ('post',  '/advertiser/campaigns'),
    ('patch', '/advertiser/campaigns/{campaign_id}'),
    ('put',   '/advertiser/campaigns/{campaign_id}/pause'),
    ('post',  '/marketer/campaigns'),
    ('post',  '/payments/allocate-to-campaign'),
    ('post',  '/payments/return-from-campaign/{campaign_id}'),
]

# These must additionally prove OWNERSHIP, not merely identity.
CAMPAIGN_OWNERSHIP_ROUTES = [
    ('patch', '/advertiser/campaigns/{campaign_id}'),
    ('put',   '/advertiser/campaigns/{campaign_id}/pause'),
    ('post',  '/payments/allocate-to-campaign'),
    ('post',  '/payments/return-from-campaign/{campaign_id}'),
]

AUTHORITY_CALLS = {'_require_campaign_authority', '_require_campaign_owner'}


class TestCampaignAuthorizationWiring(unittest.TestCase):

    def test_every_campaign_mutation_route_is_authenticated(self):
        for key in CAMPAIGN_MUTATION_ROUTES:
            fn = ROUTES.get(key)
            self.assertIsNotNone(fn, f'route {key} not found')
            deps = _dependency_names(fn)
            self.assertTrue(deps & AUTH_DEPS,
                            f'{key[0].upper()} {key[1]} is ANONYMOUS — '
                            f'deps={sorted(deps)}')

    def test_every_campaign_mutation_route_checks_authority_or_ownership(self):
        for key in CAMPAIGN_MUTATION_ROUTES:
            fn = ROUTES[key]
            calls = _calls_in(fn)
            self.assertTrue(calls & AUTHORITY_CALLS,
                            f'{key[0].upper()} {key[1]} authenticates but never '
                            f'checks campaign authority/ownership')

    def test_ownership_routes_check_ownership_specifically(self):
        """Authority alone is not enough: any approved marketer would pass."""
        for key in CAMPAIGN_OWNERSHIP_ROUTES:
            calls = _calls_in(ROUTES[key])
            self.assertIn('_require_campaign_owner', calls,
                          f'{key[0].upper()} {key[1]} does not verify OWNERSHIP — '
                          'one advertiser could act on another\'s campaign')

    def test_creation_binds_the_campaign_to_the_caller(self):
        """advertiser_email IS the ownership key, so it cannot be free text."""
        for key in (('post', '/advertiser/campaigns'), ('post', '/marketer/campaigns')):
            calls = _calls_in(ROUTES[key])
            self.assertIn('_bind_campaign_to_caller', calls,
                          f'{key[1]} lets the caller name another advertiser')

    def test_marketer_campaign_no_longer_manufactures_its_own_approval(self):
        """The old body auto-created a User with role='marketer' and an
        auto-APPROVED MarketerProfile for an anonymous caller, so the
        verification chain it claimed to require never ran.

        Asserted over the AST, not the source text, so the comment that
        documents the removed behaviour does not itself trip the test.
        """
        fn = ROUTES[('post', '/marketer/campaigns')]
        calls = _calls_in(fn)
        for constructor in ('MarketerProfile', 'User', 'hashpw', 'gensalt'):
            self.assertNotIn(constructor, calls,
                             f'/marketer/campaigns still calls {constructor}() — '
                             'it is minting identity for the caller')
        # And no keyword anywhere in the body approves a profile.
        for sub in ast.walk(fn):
            if isinstance(sub, ast.keyword) and sub.arg == 'status':
                self.assertFalse(
                    isinstance(sub.value, ast.Constant) and sub.value.value == 'approved',
                    '/marketer/campaigns sets status="approved"')

    def test_authority_gate_requires_an_approved_non_suspended_profile(self):
        body = _src_of(_function('_require_campaign_authority'))
        self.assertIn("!= 'approved'", body)
        self.assertIn("'suspended'", body)
        self.assertIn('MarketerProfile', body)

    def test_ownership_gate_compares_against_the_authenticated_identity(self):
        body = _src_of(_function('_require_campaign_owner'))
        self.assertIn('advertiser_email', body)
        self.assertIn('user.email', body)
        self.assertIn('_require_campaign_authority', body)

    def test_admin_campaign_routes_still_require_the_admin_secret(self):
        admin_routes = [k for k in ROUTES
                        if k[1].startswith('/admin/campaigns')
                        and k[0] in ('post', 'patch', 'put', 'delete')]
        self.assertTrue(admin_routes, 'no admin campaign routes found')
        for key in admin_routes:
            body = _src_of(ROUTES[key])
            self.assertTrue("ADMIN_SECRET" in body or '_check_admin' in body,
                            f'{key[0].upper()} {key[1]} is not admin-gated')

    def test_no_unguarded_campaign_mutation_route_escapes_the_list(self):
        """Catches a NEW campaign mutation route added without a guard."""
        for (method, path), fn in ROUTES.items():
            if method not in ('post', 'patch', 'put', 'delete'):
                continue
            if 'campaign' not in path.lower():
                continue
            if path.startswith('/admin/') or path.startswith('/marketing/'):
                continue  # admin-secret gated / external ad platforms
            guarded = bool(_dependency_names(fn) & AUTH_DEPS)
            self.assertTrue(guarded,
                            f'UNGUARDED campaign mutation route: '
                            f'{method.upper()} {path}')


# ═══════════════════════════════════════════════════════════════════════
# K-14 invitations (CHANGE-002 phase 2)
#
# JC: AN ORDINARY INVITATION DOES NOT BYPASS TARGETING.
# ═══════════════════════════════════════════════════════════════════════

class TestInvitationWiring(unittest.TestCase):

    def test_send_path_classifies_invitees_with_the_canonical_evaluator(self):
        fn = ROUTES[('post', '/admin/sponsors/{sponsor_id}/campaigns/{campaign_id}/send')]
        calls = _calls_in(fn)
        self.assertIn('_consultation_decision', calls,
                      'invitations are filtered by a parallel rule, not the '
                      'canonical evaluator')

    def test_determinably_ineligible_invitees_are_skipped(self):
        body = _src_of(ROUTES[('post', '/admin/sponsors/{sponsor_id}/campaigns/{campaign_id}/send')])
        self.assertIn('INELIGIBLE', body)
        self.assertIn('continue', body)

    def test_unresolved_invitees_are_not_promoted_to_eligible(self):
        """UNKNOWN must not become permission: an unresolved invitee may still
        be onboarded, but without naming the consultation."""
        body = _src_of(ROUTES[('post', '/admin/sponsors/{sponsor_id}/campaigns/{campaign_id}/send')])
        self.assertIn('disclose', body)
        self.assertIn('disclose = False', body)

    def test_consultation_title_is_only_disclosed_to_eligible_invitees(self):
        body = _src_of(ROUTES[('post', '/admin/sponsors/{sponsor_id}/campaigns/{campaign_id}/send')])
        self.assertIn("debate and disclose", body,
                      'the consultation title is emailed without checking '
                      'eligibility first')

    def test_invitation_does_not_grant_access_at_the_destination(self):
        """Destination routes must not consult any invite token."""
        for key in (('get', '/debates/{debate_id}'), ('post', '/debates/{debate_id}/vote')):
            body = _src_of(ROUTES[key])
            for token_name in ('invite', 'invite_token', 'SponsorInvitee'):
                self.assertNotIn(token_name, body,
                                 f'{key[1]} inspects {token_name!r} — an '
                                 'invitation must never authorize')


# ═══════════════════════════════════════════════════════════════════════
# CRIT-2 — frontend must send credentials to endpoints CHANGE-002 protected.
#
# voter_portal.html is a static asset, so this is the appropriate mechanism:
# there is no runtime to drive. It failed before the remediation, when
# openDebate(), loadComments() and _showDebateBannerOnAuth() fetched
# protected routes with no Authorization header and rendered the resulting
# 401 body as if it were a consultation.
# ═══════════════════════════════════════════════════════════════════════

FRONTENDS = ['voter_portal.html', 'preferendum_organizer.html']

# Consultation routes that now require a session.
PROTECTED_FETCH_PATTERNS = [
    r'\$\{API\}/debates/\$\{[^}]+\}`',            # GET /debates/{id}
    r'\$\{API\}/debates/\$\{[^}]+\}/results`',
    r'\$\{API\}/debates/\$\{[^}]+\}/opinions`',
    r'\$\{API\}/debates/\$\{[^}]+\}/comments`',
    r'\$\{API\}/debates/search-similar',
]


def _fetch_calls(text_src):
    """Yield (line_no, call_text) for every fetch(...) call.

    `call_text` is the ONE call's own argument list, extracted by matching
    parentheses. An earlier version of this helper scanned a fixed window of
    following lines, which made it blind: a bare `fetch(url)` sitting next to
    a sibling call that did pass `authHeaders` was scored as authenticated.
    Per-call extraction is what makes this test able to fail.
    """
    for m in re.finditer(r'fetch\(', text_src):
        start = m.end()
        depth, i = 1, start
        while i < len(text_src) and depth:
            if text_src[i] == '(':
                depth += 1
            elif text_src[i] == ')':
                depth -= 1
            i += 1
            if i - start > 1200:      # runaway guard
                break
        yield text_src.count('\n', 0, m.start()) + 1, text_src[start:i]


class TestFrontendSendsCredentials(unittest.TestCase):

    def test_every_protected_fetch_carries_authorization(self):
        offenders = []
        for fname in FRONTENDS:
            path = MAIN.with_name(fname)
            if not path.exists():
                continue
            src = path.read_text(encoding='utf-8')
            for lineno, call in _fetch_calls(src):
                if not any(re.search(p, call) for p in PROTECTED_FETCH_PATTERNS):
                    continue
                if 'Authorization' in call or 'authHeaders' in call:
                    continue
                offenders.append(f'{fname}:{lineno}: fetch({call.strip()[:90]}')
        self.assertEqual(offenders, [],
                         'protected endpoint fetched without credentials:\n  '
                         + '\n  '.join(offenders))

    def test_open_debate_does_not_render_an_error_body_as_a_consultation(self):
        src = MAIN.with_name('voter_portal.html').read_text(encoding='utf-8')
        start = src.index('async function openDebate')
        body = src[start:start + 2600]
        self.assertIn('authHeaders', body)
        # It must check the response before using it.
        self.assertIn('dr.ok', body)
        self.assertIn('db.id', body,
                      'openDebate does not validate the payload shape')

    def test_pre_login_banner_does_not_request_protected_content(self):
        src = MAIN.with_name('voter_portal.html').read_text(encoding='utf-8')
        start = src.index('async function _showDebateBannerOnAuth')
        body = src[start:start + 1400]
        self.assertNotIn('fetch(', body,
                         'the logged-out banner still fetches consultation content')


# ═══════════════════════════════════════════════════════════════════════
# Remediation wiring guards
# ═══════════════════════════════════════════════════════════════════════

class TestRemediationWiring(unittest.TestCase):

    def test_one_closed_list_normalization_only(self):
        """CRIT-1: write and read must share a single primitive."""
        upload = _src_of(ROUTES[('post', '/organizer/closed-list')])
        self.assertIn('_closed_list_hash', upload)
        member = _src_of(_function('_is_closed_list_member'))
        self.assertIn('_closed_list_hash', member)
        # The old divergent inline normalization must be gone from both.
        for body, where in ((upload, 'upload'), (member, 'lookup')):
            self.assertNotIn(".replace('.', '').replace('-', '')", body,
                             f'{where} still normalizes inline')

    def test_closed_list_hash_delegates_to_the_canonical_primitive(self):
        body = _src_of(_function('_closed_list_hash'))
        self.assertIn('norm_national_id', body)

    def test_every_results_route_checks_consultation_content(self):
        """HIGH-1: public results are not a back door."""
        for key in (('get', '/debates/{debate_id}/results'),
                    ('get', '/r/{debate_id}'),
                    ('get', '/pilot/{debate_id}/live')):
            calls = _calls_in(ROUTES[key])
            self.assertIn('_may_see_consultation_content', calls,
                          f'{key[1]} can leak a restricted consultation')

    def test_content_gate_precedes_the_vote_first_gate(self):
        """Otherwise anonymous callers (who skip 'vote first') would learn
        more than authenticated ineligible ones."""
        body = _src_of(ROUTES[('get', '/debates/{debate_id}/results')])
        self.assertLess(body.index('_may_see_consultation_content'),
                        body.index('Debes votar primero'),
                        'the vote-first gate runs before the content gate')

    def test_public_results_projection_excludes_consultation_content(self):
        """The allow-list itself must not name any protected field."""
        block_start = SRC.index('_PUBLIC_RESULT_FIELDS = (')
        block = SRC[block_start:SRC.index(')', block_start)]
        for forbidden in ('title', 'context', 'options', 'scope_commune',
                          'scope_country', 'target_gender', 'target_age_min',
                          'results', 'inst_name', 'option_images'):
            self.assertNotIn(f"'{forbidden}'", block,
                             f'public result projection exposes {forbidden}')
        # And it is an allow-list, not a deny-list.
        body = _src_of(_function('_public_results_payload'))
        self.assertIn('_PUBLIC_RESULT_FIELDS', body)

    def test_internal_dedup_route_uses_the_existing_agent_secret(self):
        fn = ROUTES[('get', '/internal/debates/dedup')]
        body = _src_of(fn)
        self.assertIn('X-Agent-Secret', body)
        self.assertIn('ADMIN_SECRET', body)
        # And it must not be reachable with an ordinary user session.
        self.assertNotIn('get_current_user', body)

    def test_public_debates_listing_was_not_reopened(self):
        deps = _dependency_names(ROUTES[('get', '/debates')])
        self.assertTrue(deps & AUTH_DEPS,
                        '/debates was reopened while restoring dedup')

    def test_agents_authenticate_their_dedup_queries(self):
        for fname in ('preferendum_agent.py', 'se_lifestyle_agent.py'):
            src = MAIN.with_name(fname).read_text(encoding='utf-8')
            self.assertIn('/internal/debates/dedup', src, fname)
            self.assertNotIn("BACKEND_URL}/debates?limit", src,
                             f'{fname} still queries the public listing')

    def test_agents_fail_loudly_when_dedup_is_unavailable(self):
        for fname in ('preferendum_agent.py', 'se_lifestyle_agent.py'):
            src = MAIN.with_name(fname).read_text(encoding='utf-8')
            self.assertIn('DEDUP UNAVAILABLE', src,
                          f'{fname} can still fail dedup silently')


if __name__ == '__main__':
    unittest.main(verbosity=2)
