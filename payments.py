"""
payments.py
===========
PREFERENDUM — Sistema de Pagos Completo

Métodos soportados:
  • Stripe Checkout — tarjetas, Apple Pay, Google Pay, OXXO (MX), Boleto (BR),
                       Webpay (CL), PSE (CO), Efecty (CO), SEPA, ACH
  • POL (Polygon MATIC) — para usuarios crypto-nativos
  • USDC (Polygon)      — stablecoin, precio estable

Arquitectura:
  1 Credit = $1 USD — unidad interna universal
  Anunciante compra Credits → Credits financian campañas
  Por cada impresión servida → se descuenta CPM/1000 Credits del presupuesto
  Campaña sin Credits → se pausa automáticamente

Flujo Stripe:
  POST /payments/stripe/create-session → URL de Stripe Checkout
  (usuario paga en Stripe) → Stripe llama webhook
  POST /payments/stripe/webhook → verificamos firma → acreditamos Credits

Flujo Crypto:
  GET /payments/crypto/quote?amount_usd=X → cuánto POL/USDC enviar
  Anunciante envía al wallet de Preferendum
  POST /payments/crypto/confirm → verificamos TX en Polygon → acreditamos Credits

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import os, json, hashlib, time
from typing import Optional
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# ══════════════════════════════════════════════════════════════
# PAQUETES DE CRÉDITOS
# Bonus por volumen — incentiva compras grandes
# ══════════════════════════════════════════════════════════════

CREDIT_PACKAGES = [
    {
        'id':         'starter',
        'name':       'Starter',
        'price_usd':  50,
        'credits':    50,
        'bonus_pct':  0,
        'description': 'Para empezar — ~8,000 impresiones en comunas mid',
    },
    {
        'id':         'growth',
        'name':       'Growth',
        'price_usd':  200,
        'credits':    215,
        'bonus_pct':  7.5,
        'description': '+7.5% bonus — ~35,000 impresiones en comunas mid',
    },
    {
        'id':         'pro',
        'name':       'Pro',
        'price_usd':  500,
        'credits':    550,
        'bonus_pct':  10,
        'description': '+10% bonus — ~90,000 impresiones en comunas mid',
    },
    {
        'id':         'enterprise',
        'name':       'Enterprise',
        'price_usd':  2000,
        'credits':    2300,
        'bonus_pct':  15,
        'description': '+15% bonus — contacto directo para tarifa negociada',
    },
]

PACKAGE_BY_ID = {p['id']: p for p in CREDIT_PACKAGES}

# CPM de referencia para estimaciones (se usa el de la matriz real al servir)
CPM_REFERENCE = {'premium': 12.0, 'mid': 6.0, 'growth': 3.0, 'volume': 1.5}

# Preferendum wallet para pagos crypto
PREFERENDUM_WALLET = os.getenv('WALLET_ADDRESS', '0x668108Ecfd50993Cf3bCcbeE0ADaedF5Fa306d51')

# Dirección USDC en Polygon
USDC_CONTRACT_POLYGON = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'


# ══════════════════════════════════════════════════════════════
# ESQUEMA DB — se llama desde main.py al iniciar
# ══════════════════════════════════════════════════════════════

PAYMENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS credit_accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL UNIQUE REFERENCES users(id),
    balance_credits  REAL    NOT NULL DEFAULT 0,
    total_purchased  REAL    NOT NULL DEFAULT 0,
    total_spent      REAL    NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    campaign_id      INTEGER REFERENCES ad_campaigns(id),
    type             TEXT    NOT NULL,
    amount_credits   REAL    NOT NULL,
    balance_after    REAL    NOT NULL DEFAULT 0,
    amount_usd       REAL,
    payment_method   TEXT,
    payment_ref      TEXT    UNIQUE,
    description      TEXT,
    status           TEXT    NOT NULL DEFAULT 'completed',
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crypto_payment_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    amount_usd       REAL    NOT NULL,
    credits_to_add   REAL    NOT NULL,
    currency         TEXT    NOT NULL DEFAULT 'POL',
    expected_amount  REAL    NOT NULL,
    usd_rate         REAL    NOT NULL,
    wallet_to        TEXT    NOT NULL,
    tx_hash          TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending',
    expires_at       TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    confirmed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_credit_tx_user   ON credit_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_tx_ref    ON credit_transactions(payment_ref);
CREATE INDEX IF NOT EXISTS idx_crypto_req_user  ON crypto_payment_requests(user_id, status);
"""

PAYMENTS_SCHEMA_SQL_PG = """
CREATE TABLE IF NOT EXISTS credit_accounts (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL UNIQUE REFERENCES users(id),
    balance_credits  FLOAT   NOT NULL DEFAULT 0,
    total_purchased  FLOAT   NOT NULL DEFAULT 0,
    total_spent      FLOAT   NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    campaign_id      INTEGER REFERENCES ad_campaigns(id),
    type             TEXT    NOT NULL,
    amount_credits   FLOAT   NOT NULL,
    balance_after    FLOAT   NOT NULL DEFAULT 0,
    amount_usd       FLOAT,
    payment_method   TEXT,
    payment_ref      TEXT    UNIQUE,
    description      TEXT,
    status           TEXT    NOT NULL DEFAULT 'completed',
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crypto_payment_requests (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    amount_usd       FLOAT   NOT NULL,
    credits_to_add   FLOAT   NOT NULL,
    currency         TEXT    NOT NULL DEFAULT 'POL',
    expected_amount  FLOAT   NOT NULL,
    usd_rate         FLOAT   NOT NULL,
    wallet_to        TEXT    NOT NULL,
    tx_hash          TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending',
    expires_at       TIMESTAMP NOT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    confirmed_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_credit_tx_user   ON credit_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_tx_ref    ON credit_transactions(payment_ref);
CREATE INDEX IF NOT EXISTS idx_crypto_req_user  ON crypto_payment_requests(user_id, status);
"""


# ══════════════════════════════════════════════════════════════
# HELPERS DE CUENTA
# ══════════════════════════════════════════════════════════════

def get_or_create_account(db: Session, user_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM credit_accounts WHERE user_id = :uid"),
        {'uid': user_id}
    ).fetchone()
    if not row:
        # CHANGE-001 remediation (§4) — found via real concurrent testing,
        # not the audit text itself: two callers can both see "no row" and
        # both INSERT for the SAME brand-new user (e.g. two concurrent
        # first-ever purchases). user_id is UNIQUE on credit_accounts, so
        # the loser must not crash — it re-selects the winner's row
        # instead, same pattern as _ledger_post's idempotency-key race fix.
        try:
            db.execute(
                text("INSERT INTO credit_accounts (user_id) VALUES (:uid)"),
                {'uid': user_id}
            )
            db.commit()
        except IntegrityError:
            db.rollback()
        row = db.execute(
            text("SELECT * FROM credit_accounts WHERE user_id = :uid"),
            {'uid': user_id}
        ).fetchone()
    return dict(row._mapping)


def add_credits(
    db: Session,
    user_id: int,
    amount_credits: float,
    method: str,
    ref: str,
    description: str,
    amount_usd: float = 0.0,
    tx_type: str = 'purchase',
    campaign_id: int = None,
) -> dict:
    """
    Adds credits to a user account. Idempotent: if payment_ref already exists,
    returns existing transaction without double-crediting.
    """
    # Idempotency check
    if ref:
        existing = db.execute(
            text("SELECT id FROM credit_transactions WHERE payment_ref = :ref"),
            {'ref': ref}
        ).fetchone()
        if existing:
            return {'ok': True, 'idempotent': True, 'ref': ref}

    get_or_create_account(db, user_id)  # ensures the row exists; balance itself read below atomically
    # CHANGE-001 remediation (§4) — this used to read balance_credits into
    # Python, add to it, and UPDATE with the computed value: a classic
    # lost-update race under two concurrent add_credits calls for the same
    # user. credit_accounts is a non-authoritative legacy display/cache
    # mirror (the canonical value lives in ledger_balances, see
    # _ledger_fund), but a lossy mirror is still a wrong number shown to
    # the user, so the arithmetic now happens INSIDE the atomic UPDATE
    # itself (delta, not snapshot-plus-delta) and RETURNING reads back the
    # exact post-update value with no window for another writer to
    # interleave.
    row = db.execute(
        text("""
            UPDATE credit_accounts
            SET balance_credits = balance_credits + :delta,
                total_purchased = total_purchased + :purchased,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :uid
            RETURNING balance_credits
        """),
        {
            'delta':     amount_credits,
            'purchased': amount_credits if tx_type == 'purchase' else 0,
            'uid':       user_id,
        }
    ).fetchone()
    new_balance = row[0]
    db.execute(
        text("""
            INSERT INTO credit_transactions
              (user_id, campaign_id, type, amount_credits, balance_after,
               amount_usd, payment_method, payment_ref, description)
            VALUES
              (:uid, :cid, :type, :amount, :bal, :usd, :method, :ref, :desc)
        """),
        {
            'uid':    user_id,
            'cid':    campaign_id,
            'type':   tx_type,
            'amount': amount_credits,
            'bal':    new_balance,
            'usd':    amount_usd,
            'method': method,
            'ref':    ref,
            'desc':   description,
        }
    )
    db.commit()
    return {'ok': True, 'credits_added': amount_credits, 'new_balance': new_balance}


def deduct_credits_for_impression(db: Session, campaign_id: int, cpm: float) -> bool:
    """DEPRECATED (CHANGE-001) — DO NOT CALL. Superseded by
    main._ledger_spend, which every ad-serving route uses instead.

    This function references `ad_campaigns.remaining_budget` and
    `ad_campaigns.impressions_served`, neither of which exists in any
    schema — confirmed by direct execution: every call crashed with
    `no such column`. It predates the ledger and is kept, unreachable,
    only so nothing external that may still import this name breaks at
    import time. See ledger.py and main.py's `_ledger_*` adapters.
    """
    cost = cpm / 1000.0
    result = db.execute(
        text("""
            UPDATE ad_campaigns
            SET remaining_budget    = remaining_budget - :cost,
                impressions_served  = COALESCE(impressions_served, 0) + 1
            WHERE id = :cid
              AND remaining_budget >= :cost
        """),
        {'cost': cost, 'cid': campaign_id}
    )
    db.commit()
    if result.rowcount == 0:
        # Budget exhausted — pause campaign
        db.execute(
            text("UPDATE ad_campaigns SET status='paused' WHERE id=:cid AND remaining_budget < :cost"),
            {'cid': campaign_id, 'cost': cost}
        )
        db.commit()
        return False
    return True


def allocate_budget_to_campaign(db: Session, user_id: int, campaign_id: int, credits: float) -> dict:
    """DEPRECATED (CHANGE-001) — DO NOT CALL. Superseded by
    main._ledger_reserve (see also POST /payments/allocate-to-campaign).

    Read-modify-write on `credit_accounts.balance_credits` (a real race
    under concurrency) and references `ad_campaigns.remaining_budget`,
    which does not exist in any schema — confirmed by direct execution.
    Also has no REAL/DEMO concept. Kept, unreachable, only so nothing
    external that may still import this name breaks at import time.
    """
    account = get_or_create_account(db, user_id)
    if account['balance_credits'] < credits:
        return {'ok': False, 'error': f"Insufficient credits: balance {account['balance_credits']:.2f}, requested {credits:.2f}"}

    new_balance = account['balance_credits'] - credits
    db.execute(
        text("UPDATE credit_accounts SET balance_credits=:bal, updated_at=CURRENT_TIMESTAMP WHERE user_id=:uid"),
        {'bal': new_balance, 'uid': user_id}
    )
    db.execute(
        text("UPDATE ad_campaigns SET remaining_budget = COALESCE(remaining_budget,0) + :c WHERE id=:cid"),
        {'c': credits, 'cid': campaign_id}
    )
    db.execute(
        text("""
            INSERT INTO credit_transactions
              (user_id, campaign_id, type, amount_credits, balance_after, description, payment_method)
            VALUES (:uid, :cid, 'allocation', :neg, :bal, 'Budget allocated to campaign', 'internal')
        """),
        {'uid': user_id, 'cid': campaign_id, 'neg': -credits, 'bal': new_balance}
    )
    db.commit()
    return {'ok': True, 'allocated': credits, 'remaining_account_balance': new_balance}


def return_budget_to_account(db: Session, user_id: int, campaign_id: int) -> dict:
    """DEPRECATED (CHANGE-001) — DO NOT CALL. Superseded by
    main._ledger_release (see also POST /payments/return-from-campaign/{id}).

    References `ad_campaigns.remaining_budget` (does not exist — confirmed
    by direct execution) and unconditionally zeroes it rather than
    decrementing by the amount actually returned, which under concurrency
    could erase and double-credit a spend that landed mid-transaction.
    Kept, unreachable, only so nothing external that may still import this
    name breaks at import time.
    """
    row = db.execute(
        text("SELECT remaining_budget FROM ad_campaigns WHERE id=:cid"),
        {'cid': campaign_id}
    ).fetchone()
    if not row or not row[0]:
        return {'ok': True, 'returned': 0}

    credits = float(row[0])
    account = get_or_create_account(db, user_id)
    new_balance = account['balance_credits'] + credits

    db.execute(
        text("UPDATE ad_campaigns SET remaining_budget=0, status='paused' WHERE id=:cid"),
        {'cid': campaign_id}
    )
    db.execute(
        text("UPDATE credit_accounts SET balance_credits=:bal, updated_at=CURRENT_TIMESTAMP WHERE user_id=:uid"),
        {'bal': new_balance, 'uid': user_id}
    )
    db.execute(
        text("""
            INSERT INTO credit_transactions
              (user_id, campaign_id, type, amount_credits, balance_after, description, payment_method)
            VALUES (:uid, :cid, 'refund', :c, :bal, 'Unspent budget returned from campaign', 'internal')
        """),
        {'uid': user_id, 'cid': campaign_id, 'c': credits, 'bal': new_balance}
    )
    db.commit()
    return {'ok': True, 'returned': credits, 'new_balance': new_balance}


# ══════════════════════════════════════════════════════════════
# STRIPE
# ══════════════════════════════════════════════════════════════

def _stripe(db=None):
    import stripe as _s
    key = (os.getenv('APP_STRIPE_KEY') or os.getenv('STRIPE_SECRET_KEY') or '').strip()
    if not key and db is not None:
        try:
            from sqlalchemy import text as _text
            row = db.execute(_text("SELECT value FROM app_config WHERE key='stripe_secret_key'")).fetchone()
            if row:
                key = row[0].strip()
        except Exception:
            pass
    if not key:
        raise HTTPException(503, 'Stripe not configured — set STRIPE_SECRET_KEY')
    _s.api_key = key
    return _s


def create_stripe_checkout(user_id: int, package_id: str, success_url: str, cancel_url: str, db=None) -> dict:
    pkg = PACKAGE_BY_ID.get(package_id)
    if not pkg:
        raise HTTPException(400, f'Unknown package: {package_id}')

    stripe = _stripe(db)

    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=[{
            'price_data': {
                'currency':     'usd',
                'unit_amount':  pkg['price_usd'] * 100,  # Stripe uses cents
                'product_data': {
                    'name':        f"Preferendum Credits — {pkg['name']}",
                    'description': f"{pkg['credits']} Credits (1 Credit = $1 USD){' +'+str(pkg['bonus_pct'])+'% bonus' if pkg['bonus_pct'] else ''}",
                },
            },
            'quantity': 1,
        }],
        payment_method_types=[
            'card',
        ],
        payment_method_options={
            'card': {'request_three_d_secure': 'automatic'},
        },
        success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=cancel_url,
        metadata={
            'user_id':    str(user_id),
            'package_id': package_id,
            'credits':    str(pkg['credits']),
        },
        expires_at=int(time.time()) + 3600,  # 1 hour to complete
    )
    return {'checkout_url': session.url, 'session_id': session.id}


def handle_stripe_webhook(payload: bytes, stripe_signature: str) -> dict:
    stripe = _stripe()
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    if not webhook_secret:
        raise HTTPException(503, 'Stripe webhook secret not configured')

    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, 'Invalid Stripe signature')

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        meta    = session.get('metadata', {})
        user_id = int(meta.get('user_id', 0))
        credits = float(meta.get('credits', 0))
        pkg_id  = meta.get('package_id', '')
        pkg     = PACKAGE_BY_ID.get(pkg_id, {})
        ref     = f"stripe_{session['id']}"

        if user_id and credits:
            return {
                'action':   'add_credits',
                'user_id':  user_id,
                'credits':  credits,
                'amount_usd': pkg.get('price_usd', 0),
                'method':   'stripe',
                'ref':      ref,
                'desc':     f"Stripe: {pkg.get('name','package')} ({credits} Credits)",
            }

    return {'action': 'noop', 'event_type': event['type']}


# ══════════════════════════════════════════════════════════════
# CRYPTO — POL y USDC en Polygon
# ══════════════════════════════════════════════════════════════

def get_crypto_quote(amount_usd: float, currency: str = 'POL') -> dict:
    """
    Fetches current POL or USDC price and calculates how much to send.
    Uses CoinGecko free API (no key required).
    USDC is always 1:1 with USD.
    """
    currency = currency.upper()

    if currency == 'USDC':
        return {
            'currency':        'USDC',
            'usd_rate':        1.0,
            'amount_expected': round(amount_usd, 2),
            'note':            'USDC is a stablecoin pegged to USD — send exactly this amount',
        }

    if currency == 'POL':
        try:
            import requests
            r = requests.get(
                'https://api.coingecko.com/api/v3/simple/price',
                params={'ids': 'matic-network', 'vs_currencies': 'usd'},
                timeout=8,
            )
            data = r.json()
            pol_price = float(data['matic-network']['usd'])
        except Exception:
            pol_price = 0.60  # fallback price
        pol_amount = round(amount_usd / pol_price, 4)
        return {
            'currency':        'POL',
            'usd_rate':        pol_price,
            'amount_expected': pol_amount,
            'note':            f'Send exactly {pol_amount} POL to lock this rate (valid 30 min)',
        }

    raise HTTPException(400, f'Unsupported currency: {currency}. Use POL or USDC.')


def create_crypto_payment_request(db: Session, user_id: int, amount_usd: float, currency: str = 'POL') -> dict:
    """
    Creates a pending crypto payment request.
    Advertiser sends the exact amount shown to our wallet address.
    """
    if amount_usd < 10:
        raise HTTPException(400, 'Minimum crypto payment is $10 USD')

    quote = get_crypto_quote(amount_usd, currency)
    credits = float(amount_usd)  # 1:1 USD→Credits

    # Add bonus if amount matches a package
    for pkg in sorted(CREDIT_PACKAGES, key=lambda p: p['price_usd'], reverse=True):
        if amount_usd >= pkg['price_usd']:
            credits = pkg['credits']
            break

    expires_at = datetime.utcnow().isoformat()[:10] + 'T' + \
                 f"{(datetime.utcnow().hour):02d}:{(datetime.utcnow().minute + 30) % 60:02d}:00"

    result = db.execute(
        text("""
            INSERT INTO crypto_payment_requests
              (user_id, amount_usd, credits_to_add, currency, expected_amount,
               usd_rate, wallet_to, expires_at)
            VALUES (:uid, :usd, :cr, :cur, :exp, :rate, :wallet, :expires)
        """),
        {
            'uid':     user_id,
            'usd':     amount_usd,
            'cr':      credits,
            'cur':     currency,
            'exp':     quote['amount_expected'],
            'rate':    quote['usd_rate'],
            'wallet':  PREFERENDUM_WALLET,
            'expires': expires_at,
        }
    )
    db.commit()
    request_id = result.lastrowid

    return {
        'request_id':        request_id,
        'wallet_address':    PREFERENDUM_WALLET,
        'currency':          currency,
        'amount_to_send':    quote['amount_expected'],
        'amount_usd':        amount_usd,
        'credits_to_receive': credits,
        'expires_at':        expires_at,
        'instructions':      f"Send exactly {quote['amount_expected']} {currency} to {PREFERENDUM_WALLET}. "
                             f"Then confirm with your transaction hash.",
        'network':           'Polygon Mainnet (chainId 137)',
        'note':              quote['note'],
    }


def confirm_crypto_payment(db: Session, user_id: int, request_id: int, tx_hash: str) -> dict:
    """
    Advertiser provides their transaction hash after sending.
    We verify on Polygon: correct recipient, correct amount (±5% tolerance), confirmed.
    """
    req = db.execute(
        text("SELECT * FROM crypto_payment_requests WHERE id=:id AND user_id=:uid AND status='pending'"),
        {'id': request_id, 'uid': user_id}
    ).fetchone()
    if not req:
        raise HTTPException(404, 'Payment request not found or already processed')

    req = dict(req._mapping)

    # Normalize tx_hash
    if not tx_hash.startswith('0x'):
        tx_hash = '0x' + tx_hash
    tx_hash = tx_hash.lower()

    # Verify on Polygon
    verification = _verify_polygon_tx(
        tx_hash        = tx_hash,
        expected_to    = PREFERENDUM_WALLET,
        expected_amount= req['expected_amount'],
        currency       = req['currency'],
    )

    if not verification['ok']:
        raise HTTPException(400, verification['error'])

    # Mark request confirmed
    db.execute(
        text("""
            UPDATE crypto_payment_requests
            SET status='confirmed', tx_hash=:tx, confirmed_at=datetime('now')
            WHERE id=:id
        """),
        {'tx': tx_hash, 'id': request_id}
    )
    db.commit()

    return {
        'action':     'add_credits',
        'user_id':    user_id,
        'credits':    req['credits_to_add'],
        'amount_usd': req['amount_usd'],
        'method':     f"crypto_{req['currency'].lower()}",
        'ref':        f"crypto_{tx_hash}",
        'desc':       f"Crypto {req['currency']}: ${req['amount_usd']:.2f} USD → {req['credits_to_add']} Credits",
    }


def _verify_polygon_tx(tx_hash: str, expected_to: str, expected_amount: float, currency: str) -> dict:
    """
    Verifies a Polygon transaction using web3.py.
    Checks: correct recipient, correct amount (±5%), at least 1 confirmation.
    """
    try:
        from web3 import Web3
        rpc = os.getenv('POLYGON_RPC_URL', 'https://1rpc.io/matic')
        w3  = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 15}))

        tx      = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        if not receipt or receipt['status'] != 1:
            return {'ok': False, 'error': 'Transaction failed or not confirmed on Polygon'}

        to_addr = (tx.get('to') or '').lower()

        if currency == 'POL':
            # Native POL transfer
            if to_addr != expected_to.lower():
                return {'ok': False, 'error': f'Transaction sent to wrong address: {to_addr}'}
            amount_sent = float(w3.from_wei(tx['value'], 'ether'))
            tolerance   = expected_amount * 0.05
            if abs(amount_sent - expected_amount) > tolerance:
                return {'ok': False, 'error': f'Amount mismatch: expected ~{expected_amount} POL, got {amount_sent} POL'}

        elif currency == 'USDC':
            # ERC-20 USDC transfer — parse Transfer event
            usdc_contract = w3.eth.contract(
                address=Web3.to_checksum_address(USDC_CONTRACT_POLYGON),
                abi=[{
                    'name':   'Transfer',
                    'type':   'event',
                    'inputs': [
                        {'name': 'from',  'type': 'address', 'indexed': True},
                        {'name': 'to',    'type': 'address', 'indexed': True},
                        {'name': 'value', 'type': 'uint256', 'indexed': False},
                    ],
                }]
            )
            logs = usdc_contract.events.Transfer().process_receipt(receipt)
            matched = [
                l for l in logs
                if l['args']['to'].lower() == expected_to.lower()
            ]
            if not matched:
                return {'ok': False, 'error': 'No USDC transfer to Preferendum wallet found in this TX'}
            # USDC on Polygon has 6 decimals
            amount_sent = float(matched[0]['args']['value']) / 1_000_000
            tolerance   = expected_amount * 0.05
            if abs(amount_sent - expected_amount) > tolerance:
                return {'ok': False, 'error': f'USDC amount mismatch: expected ~{expected_amount}, got {amount_sent}'}

        return {'ok': True, 'amount_verified': amount_sent}

    except Exception as e:
        return {'ok': False, 'error': f'Polygon verification error: {str(e)}'}
