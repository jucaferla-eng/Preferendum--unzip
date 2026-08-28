"""
ledger.py — CHANGE-001 canonical double-entry financial ledger.

CHANGE-002 built canonical MATCHING (eligibility.py). CHANGE-003 built
canonical SOCIOECONOMIC CLASSIFICATION (socioeconomic.py). Both are
dependency-free: pure functions over plain values, no fastapi, no
sqlalchemy, no database — a thin adapter layer in main.py translates ORM
rows into the snapshots these modules consume, and does the actual I/O.

ledger.py follows the exact same split. This module decides WHAT a
financial event means (which accounts move, by how much, and whether the
result is even legal); it never touches a database. main.py's adapters do
the atomic reads/writes, using the primitives this module hands them.

═══════════════════════════════════════════════════════════════════════
WHY A LEDGER  (CHANGE-001 recon findings this module exists to fix)
═══════════════════════════════════════════════════════════════════════

Before CHANGE-001, "money" existed in FOUR uncoordinated representations:
`credit_accounts.balance_credits` (real purchases), `AdCampaign.budget_clp`
/`spent_clp` (advertiser-declared, unbacked by any funds check),
`AdCampaign.remaining_budget` (referenced by payments.py, but the column
was never created — confirmed by direct execution: every route that
touched it crashed with `no such column`), and raw `AdImpressionLog` rows
(the only one nothing wrote inconsistently). None of these agreed with any
other, and nothing prevented an advertiser from serving ads against a
`budget_clp` that no real payment had ever backed.

THE LEDGER IS NOW THE ONLY CANONICAL SOURCE OF FINANCIAL TRUTH. Every
other financial-looking field (`credit_accounts.balance_credits`,
`AdCampaign.spent_clp`) is a read-through CACHE maintained EXCLUSIVELY by
the ledger-posting adapters in main.py — never written independently. This
is the same "single writer, everything else derives from it" pattern
CHANGE-002 established for `se_tier` and CHANGE-003 established for the
economic reference tables.

═══════════════════════════════════════════════════════════════════════
THE RULES THIS MODULE ENCODES  (JC, CHANGE-001)
═══════════════════════════════════════════════════════════════════════

R1. PREPAID ONLY. A campaign may never spend more than it has reserved,
    and a reservation may never exceed the funding account's available
    balance. There is no post-paid path anywhere in this module.

R2. DOUBLE-ENTRY. Every transaction is a list of Entries whose amounts
    sum to exactly zero (within a cent-scale epsilon). Nothing here can
    construct or accept an unbalanced transaction.

R3. REAL AND DEMO NEVER MIX. Every account kind has a FIXED value class
    (see ACCOUNT_KIND_VALUE_CLASS). A transaction's entries must ALL
    belong to the same value class — structurally, not by convention.
    There is no code path in this module that can build a transaction
    mixing REAL and DEMO legs.

R4. IMMUTABLE ONCE POSTED. This module has no "update" or "reverse"
    operation. A refund/release is a NEW transaction with its own entries
    (money flowing back), never a mutation of the original. main.py's
    adapters must never UPDATE or DELETE a posted ledger row — enforced by
    a structural regression test, the same technique CHANGE-002/003 use to
    keep a fixed defect from silently coming back.

R5. IDEMPOTENT BY CONSTRUCTION. Every transaction that represents an
    external or retryable event (funding, demo issuance, spend) carries an
    idempotency key. The SAME key must always produce the SAME result
    without a second economic effect — this module computes deterministic
    keys where one exists naturally; main.py's adapter is responsible for
    the actual dedup check against stored transactions.

R6. NOTHING HERE INVENTS FUNDED HISTORY. This module has no notion of an
    "opening balance" or a way to retroactively mark existing
    `budget_clp`/`spent_clp` as funded. See `reconciliation.py`-equivalent
    functions at the bottom of this file, which only ever REPORT ambiguity,
    never resolve it.
"""

from __future__ import annotations

from typing import Any, Optional

# Policy version — bumped when a rule above changes, so a posted
# transaction can always be traced to the rules that produced it.
POLICY_VERSION = 'change-001.v1'

EPSILON = 0.005  # half a cent — the balance-tolerance for "sums to zero"


# ═══════════════════════════════════════════════════════════════════════
# VALUE CLASSES  (R3)
# ═══════════════════════════════════════════════════════════════════════

REAL = 'REAL'
DEMO = 'DEMO'
VALUE_CLASSES = (REAL, DEMO)


# ═══════════════════════════════════════════════════════════════════════
# ACCOUNT KINDS
# ═══════════════════════════════════════════════════════════════════════
#
# Every account kind's value class is FIXED here, once, and every entry
# inherits it. This is what makes REAL/DEMO mixing structurally impossible
# rather than merely convention: there is no account kind whose class is
# ambiguous or caller-supplied.

# Where real/demo value ENTERS the ledger from outside (Stripe, crypto,
# manual admin credit, or a bounded demo grant). Its balance is a running
# negative number — "how much has ever been issued" — which is the
# standard double-entry technique for modelling value creation: nothing
# here is unconstrained real-world money, it is bookkept exactly like
# every other account, just permitted to go negative because it represents
# the outside world, not a scarce internal resource.
ORIGIN_REAL = 'ORIGIN_REAL'
ORIGIN_DEMO = 'ORIGIN_DEMO'

# A user/advertiser's own available (unreserved) balance.
USER_REAL = 'USER_REAL'
USER_DEMO = 'USER_DEMO'

# Funds a campaign has reserved out of its owner's available balance.
# Exactly one of these applies per campaign — a campaign is REAL or DEMO,
# never both (see CampaignCreate.value_class in main.py).
CAMPAIGN_REAL_RESERVED = 'CAMPAIGN_REAL_RESERVED'
CAMPAIGN_DEMO_RESERVED = 'CAMPAIGN_DEMO_RESERVED'

# Recognized spend sink — where reserved funds go once an impression is
# actually billed. A reporting/audit account, not a per-user balance.
SPEND_REAL = 'SPEND_REAL'
SPEND_DEMO = 'SPEND_DEMO'

ACCOUNT_KIND_VALUE_CLASS = {
    ORIGIN_REAL: REAL, ORIGIN_DEMO: DEMO,
    USER_REAL: REAL, USER_DEMO: DEMO,
    CAMPAIGN_REAL_RESERVED: REAL, CAMPAIGN_DEMO_RESERVED: DEMO,
    SPEND_REAL: REAL, SPEND_DEMO: DEMO,
}

# Account kinds whose balance must never go negative (the "scarce
# resource" accounts). ORIGIN_* and SPEND_* are deliberately excluded —
# ORIGIN legitimately accumulates negative (R..origin note above), and
# SPEND is a monotonically-increasing recognition sink.
CONSTRAINED_KINDS = frozenset(
    {USER_REAL, USER_DEMO, CAMPAIGN_REAL_RESERVED, CAMPAIGN_DEMO_RESERVED})


def value_class_of(account_kind: str) -> Optional[str]:
    return ACCOUNT_KIND_VALUE_CLASS.get(account_kind)


def user_account_kind(value_class: str) -> str:
    return USER_REAL if value_class == REAL else USER_DEMO


def campaign_account_kind(value_class: str) -> str:
    return CAMPAIGN_REAL_RESERVED if value_class == REAL else CAMPAIGN_DEMO_RESERVED


def origin_account_kind(value_class: str) -> str:
    return ORIGIN_REAL if value_class == REAL else ORIGIN_DEMO


def spend_account_kind(value_class: str) -> str:
    return SPEND_REAL if value_class == REAL else SPEND_DEMO


# ═══════════════════════════════════════════════════════════════════════
# TRANSACTION TYPES
# ═══════════════════════════════════════════════════════════════════════

TXN_FUNDING = 'funding'                 # ORIGIN -> USER            (real purchase)
TXN_DEMO_ISSUANCE = 'demo_issuance'     # ORIGIN_DEMO -> USER_DEMO  (bounded test grant)
TXN_RESERVATION = 'reservation'         # USER -> CAMPAIGN_RESERVED (campaign funding)
TXN_SPEND = 'spend'                     # CAMPAIGN_RESERVED -> SPEND (billed impression)
TXN_RELEASE = 'release'                 # CAMPAIGN_RESERVED -> USER (unused funds returned)

TXN_TYPES = (TXN_FUNDING, TXN_DEMO_ISSUANCE, TXN_RESERVATION, TXN_SPEND, TXN_RELEASE)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY / POSTING
# ═══════════════════════════════════════════════════════════════════════

def round_amount(x: Any) -> Optional[float]:
    """Round to the cent. Returns None (never guesses) for anything that
    is not a finite positive number."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float('inf'), float('-inf')):  # NaN / inf
        return None
    return round(v, 2)


class Entry:
    """One leg of a transaction. `amount` is a SIGNED delta to the named
    account's balance — positive increases it, negative decreases it.
    There is no separate debit/credit vocabulary: the sign IS the
    direction, which is simpler to construct and to test correctly.
    """

    __slots__ = ('account_kind', 'account_ref', 'amount')

    def __init__(self, account_kind: str, account_ref: Optional[int], amount: float):
        self.account_kind = account_kind
        self.account_ref = account_ref   # user_id / campaign_id / None for singletons
        self.amount = amount

    @property
    def value_class(self) -> Optional[str]:
        return value_class_of(self.account_kind)

    def as_dict(self) -> dict:
        return {'account_kind': self.account_kind, 'account_ref': self.account_ref,
                'amount': self.amount, 'value_class': self.value_class}

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return f'<Entry {self.account_kind}[{self.account_ref}] {self.amount:+.2f}>'


class Posting:
    """The result of asking this module to build (and validate) a
    transaction. `ok` is the ONLY thing a caller may gate on — mirrors
    eligibility.Decision.allowed / socioeconomic.Classification.resolved.
    """

    __slots__ = ('ok', 'txn_type', 'value_class', 'entries', 'reason', 'policy_version')

    def __init__(self, ok: bool, txn_type: str, value_class: Optional[str],
                entries: list, reason: str = ''):
        self.ok = ok
        self.txn_type = txn_type
        self.value_class = value_class
        self.entries = entries
        self.reason = reason
        self.policy_version = POLICY_VERSION

    def as_dict(self) -> dict:
        return {
            'ok': self.ok, 'txn_type': self.txn_type, 'value_class': self.value_class,
            'reason': self.reason, 'policy_version': self.policy_version,
            'entries': [e.as_dict() for e in self.entries],
        }

    def __repr__(self) -> str:   # pragma: no cover
        return f'<Posting ok={self.ok} {self.txn_type} {self.value_class} reason={self.reason!r}>'


def validate_entries(entries: list, expected_value_class: Optional[str] = None) -> str:
    """Returns '' if the entries form a legal double-entry transaction,
    else a short machine-readable reason string (R2, R3).

    Deliberately does NOT check account balances — that requires the
    database and is main.py's job. This is the part that can be proven
    correct with no I/O at all.
    """
    if not entries or len(entries) < 2:
        return 'too_few_entries'
    classes = set()
    total = 0.0
    for e in entries:
        if e.amount == 0:
            return 'zero_amount_entry'
        vc = e.value_class
        if vc is None:
            return f'unknown_account_kind:{e.account_kind}'
        classes.add(vc)
        total += e.amount
    if len(classes) != 1:
        return 'mixed_value_class'
    (only_class,) = tuple(classes)
    if expected_value_class is not None and only_class != expected_value_class:
        return 'value_class_mismatch'
    if abs(total) > EPSILON:
        return 'unbalanced'
    return ''


# ═══════════════════════════════════════════════════════════════════════
# TRANSACTION BUILDERS — one per business event, each a pure function
# returning a validated Posting. main.py's adapter takes `.entries` and
# performs the actual atomic DB writes (see main.py `_ledger_post`).
# ═══════════════════════════════════════════════════════════════════════

def build_funding(value_class: str, user_id: int, amount: Any) -> Posting:
    """External money (Stripe/crypto/manual for REAL, grant for DEMO)
    entering a user's available balance."""
    amt = round_amount(amount)
    if amt is None or amt <= 0:
        return Posting(False, TXN_FUNDING, value_class, [], 'invalid_amount')
    if value_class not in VALUE_CLASSES:
        return Posting(False, TXN_FUNDING, value_class, [], 'invalid_value_class')
    entries = [
        Entry(origin_account_kind(value_class), None, -amt),
        Entry(user_account_kind(value_class), user_id, amt),
    ]
    reason = validate_entries(entries, value_class)
    return Posting(reason == '', TXN_FUNDING, value_class, entries, reason)


def build_reservation(value_class: str, user_id: int, campaign_id: int, amount: Any) -> Posting:
    """Moves funds from a user's available balance into a campaign's
    reserved balance (R1: this is the ONLY way a campaign acquires
    spendable funds). Whether the user actually HAS enough is a balance
    check main.py's adapter performs atomically — this function only
    builds and validates the shape of the transaction."""
    amt = round_amount(amount)
    if amt is None or amt <= 0:
        return Posting(False, TXN_RESERVATION, value_class, [], 'invalid_amount')
    if value_class not in VALUE_CLASSES:
        return Posting(False, TXN_RESERVATION, value_class, [], 'invalid_value_class')
    entries = [
        Entry(user_account_kind(value_class), user_id, -amt),
        Entry(campaign_account_kind(value_class), campaign_id, amt),
    ]
    reason = validate_entries(entries, value_class)
    return Posting(reason == '', TXN_RESERVATION, value_class, entries, reason)


def build_spend(value_class: str, campaign_id: int, amount: Any) -> Posting:
    """A billed impression/event: moves funds from a campaign's reserved
    balance into the recognized-spend sink. R1: main.py's adapter must
    reject this atomically if the reservation cannot cover it — never
    allow the campaign's reserved balance to go negative."""
    amt = round_amount(amount)
    if amt is None or amt <= 0:
        return Posting(False, TXN_SPEND, value_class, [], 'invalid_amount')
    if value_class not in VALUE_CLASSES:
        return Posting(False, TXN_SPEND, value_class, [], 'invalid_value_class')
    entries = [
        Entry(campaign_account_kind(value_class), campaign_id, -amt),
        Entry(spend_account_kind(value_class), None, amt),
    ]
    reason = validate_entries(entries, value_class)
    return Posting(reason == '', TXN_SPEND, value_class, entries, reason)


def build_release(value_class: str, user_id: int, campaign_id: int, amount: Any) -> Posting:
    """Unused reserved funds returned to the SAME user, SAME value class
    (F: REAL -> REAL, DEMO -> DEMO, never cross). Structurally cannot
    cross classes: campaign_account_kind and user_account_kind are both
    derived from the single `value_class` argument."""
    amt = round_amount(amount)
    if amt is None or amt <= 0:
        return Posting(False, TXN_RELEASE, value_class, [], 'invalid_amount')
    if value_class not in VALUE_CLASSES:
        return Posting(False, TXN_RELEASE, value_class, [], 'invalid_value_class')
    entries = [
        Entry(campaign_account_kind(value_class), campaign_id, -amt),
        Entry(user_account_kind(value_class), user_id, amt),
    ]
    reason = validate_entries(entries, value_class)
    return Posting(reason == '', TXN_RELEASE, value_class, entries, reason)


# ═══════════════════════════════════════════════════════════════════════
# DEMO GRANT POLICY  (G — bounded, test-oriented, never REAL)
# ═══════════════════════════════════════════════════════════════════════

# A demo grant is deliberately small and capped. These are policy
# constants, not security theatre: the actual enforcement (idempotency key
# + lifetime-total check) happens against real stored data in main.py's
# adapter; these functions only compute what that adapter needs to enforce
# it, so the POLICY is unit-testable without a database.
#
# CHANGE-001 remediation (§7) — PROVISIONAL TESTING DEFAULTS, NOT AN
# APPROVED BUSINESS POLICY. 500/grant and a 5000 lifetime cap were chosen
# to exercise the full demo funding -> allocation -> spend -> release flow
# end to end in tests; JC has not approved these specific numbers as
# permanent policy (same status as socioeconomic.THRESHOLDS_APPROVED_BY_BUSINESS
# — see that module's identical disclaimer). DEMO_POLICY_APPROVED_BY_BUSINESS
# stays False until an explicit business decision says otherwise; any admin
# route that surfaces this policy must expose that flag, not just the
# numbers, so nobody mistakes "the tests pass" for "these are the real
# limits". `demo_grant_allowed`/`build_demo_grant` accept override kwargs so
# a deployment can configure the policy from ONE place (an env var read
# once in main.py) instead of editing this module — see main.py's
# DEMO_GRANT_AMOUNT_CREDITS / DEMO_GRANT_MAX_LIFETIME_CREDITS.
DEMO_POLICY_VERSION = 'change-001-remediation.v1'
DEMO_POLICY_APPROVED_BY_BUSINESS = False
DEMO_GRANT_AMOUNT = 500.0
DEMO_GRANT_MAX_LIFETIME = 5000.0          # hard cap across all grants ever
DEMO_GRANT_COOLDOWN_SECONDS = 86400       # one grant per rolling day


def demo_grant_idempotency_key(user_id: int, day_bucket: str) -> str:
    """Deterministic key: the SAME user requesting a demo grant within the
    SAME day bucket always produces the SAME key, so main.py's adapter's
    idempotency check (identical to the Stripe-retry pattern) collapses
    repeated requests to a single economic effect without needing a
    separate rate-limiter."""
    return f'demo:{user_id}:{day_bucket}'


def demo_grant_allowed(already_issued_lifetime: Any, *,
                       grant_amount: float = DEMO_GRANT_AMOUNT,
                       max_lifetime: float = DEMO_GRANT_MAX_LIFETIME) -> bool:
    """R.. bounded: refuses once the lifetime cap is reached, independent
    of whether the cooldown/idempotency key was somehow bypassed. Belt and
    suspenders — two independent reasons a runaway demo-mint can't happen.

    `grant_amount`/`max_lifetime` default to the module's provisional
    constants but can be overridden by the caller — this is the ONE seam a
    deployment-level policy override goes through (main.py), so the numbers
    never need editing in more than one place."""
    try:
        issued = float(already_issued_lifetime or 0)
    except (TypeError, ValueError):
        issued = 0.0
    return (issued + grant_amount) <= max_lifetime + EPSILON


def build_demo_grant(user_id: int, already_issued_lifetime: Any, *,
                     grant_amount: float = DEMO_GRANT_AMOUNT,
                     max_lifetime: float = DEMO_GRANT_MAX_LIFETIME) -> Posting:
    if not demo_grant_allowed(already_issued_lifetime, grant_amount=grant_amount,
                              max_lifetime=max_lifetime):
        return Posting(False, TXN_DEMO_ISSUANCE, DEMO, [], 'lifetime_cap_reached')
    return build_funding(DEMO, user_id, grant_amount)


# ═══════════════════════════════════════════════════════════════════════
# RECONCILIATION  (H — read-only, reports ambiguity, resolves nothing)
# ═══════════════════════════════════════════════════════════════════════

RECON_OK = 'ok'
RECON_MISMATCH = 'mismatch'
RECON_AMBIGUOUS_LEGACY = 'ambiguous_legacy'
RECON_NO_LEDGER_ACCOUNT = 'no_ledger_account'


def reconcile_user_balance(legacy_balance: Any, ledger_balance: Any) -> dict:
    """Compares the legacy `credit_accounts.balance_credits` cache against
    the ledger's own computed balance for the same user. R6: this ONLY
    reports; it never decides which number is right and never writes
    anything. A mismatch here means the legacy cache drifted before the
    ledger existed (or a bug let something write it independently) — it is
    always presented as a finding requiring human review, never silently
    resolved in either direction.
    """
    lb = round_amount(legacy_balance) if legacy_balance is not None else None
    gb = round_amount(ledger_balance) if ledger_balance is not None else None
    if gb is None:
        return {'status': RECON_NO_LEDGER_ACCOUNT, 'legacy': lb, 'ledger': gb,
                'note': 'no ledger account exists for this user yet'}
    if lb is None:
        return {'status': RECON_AMBIGUOUS_LEGACY, 'legacy': lb, 'ledger': gb,
                'note': 'no legacy value to compare'}
    if abs(lb - gb) <= EPSILON:
        return {'status': RECON_OK, 'legacy': lb, 'ledger': gb, 'note': ''}
    return {'status': RECON_MISMATCH, 'legacy': lb, 'ledger': gb,
            'note': f'legacy cache diverges from the ledger by {lb - gb:+.2f}'}


def reconcile_campaign_spend(budget_clp: Any, spent_clp: Any, impression_log_sum_clp: Any,
                             ledger_spend_credits: Any, usd_to_clp: float) -> dict:
    """Compares FOUR pre-existing representations of one campaign's spend:
    the advertiser-declared cap, the (possibly stale — CHANGE-001 recon
    found the codebase's own admin recompute tool exists BECAUSE this
    drifts) `spent_clp` field, the raw impression-log sum, and — once
    CHANGE-001 is live — the ledger's own recognized spend. Never
    resolves a mismatch; only reports it, with enough detail (each raw
    number) for a human to decide.
    """
    def _n(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    b, s, log_sum = _n(budget_clp), _n(spent_clp), _n(impression_log_sum_clp)
    ledger_credits = _n(ledger_spend_credits)
    ledger_clp = (ledger_credits * usd_to_clp) if ledger_credits is not None else None

    findings = []
    if s is not None and log_sum is not None and abs(s - log_sum) > 1.0:
        findings.append(f'spent_clp ({s:.0f}) diverges from AdImpressionLog sum '
                        f'({log_sum:.0f}) by {s - log_sum:+.0f} CLP')
    if ledger_clp is not None and log_sum is not None and abs(ledger_clp - log_sum) > 1.0:
        findings.append(f'ledger-recognized spend ({ledger_clp:.0f} CLP-equiv) diverges '
                        f'from AdImpressionLog sum ({log_sum:.0f}) by '
                        f'{ledger_clp - log_sum:+.0f} CLP')
    if b is not None and s is not None and s > b + 1.0:
        findings.append(f'spent_clp ({s:.0f}) EXCEEDS budget_clp ({b:.0f}) — '
                        f'pre-ledger overspend, cannot be retroactively explained')

    status = RECON_MISMATCH if findings else RECON_OK
    return {
        'status': status,
        'budget_clp': b, 'spent_clp': s, 'impression_log_sum_clp': log_sum,
        'ledger_spend_credits': ledger_credits, 'ledger_spend_clp_equiv': ledger_clp,
        'findings': findings,
    }
