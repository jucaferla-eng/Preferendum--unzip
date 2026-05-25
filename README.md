# Preferendum — Complete Backend System

*En memoria de José Ignacio Fernández (1989–2024)*

---

## Run in 3 steps

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server
uvicorn main:app --reload

# 3. Run full system test (new terminal)
python test_system.py
```

Server runs at: **http://localhost:8000**
Interactive API docs: **http://localhost:8000/docs**

---

## What works right now (SQLite, no setup needed)

| Endpoint | What it does |
|---|---|
| `POST /auth/register` | Register voter (7 fields) |
| `POST /auth/login` | Login → JWT token |
| `GET /auth/me` | Current user profile |
| `POST /debates/` | Create debate (organizer) |
| `GET /debates/` | Personalized feed with ads injected |
| `GET /debates/{id}` | Debate detail + comments |
| `POST /debates/{id}/comments` | Post comment |
| `POST /debates/{id}/comments/{id}/like` | Like a comment |
| `POST /vote/` | **Cast vote** → AES-256 encrypt → SHA-256 hash → Polygon → verification code |
| `GET /vote/check/{debate_id}` | Has this voter already voted? |
| `GET /results/{debate_id}` | Live results with demographic breakdown |
| `GET /verify/vote/{vcode}` | Self-verify vote (José's insight) |
| `POST /advertiser/upload-campaign/` | Create ad campaign |
| `GET /advertiser/dashboard/{id}` | Campaign impressions + spend |
| `POST /ads/view/` | Record ad impression (20 CLP) |
| `GET /ads/user/{id}` | Get matched ads for voter |
| `GET /stats/global` | Platform-wide statistics |

---

## The vote flow (bridge destruction)

```
Voter → POST /vote/ {debate_id, option}
  │
  ├── Pull demographics (gender, age_group, county, country)
  ├── encrypt_vote()  → AES-256-CBC, random IV
  ├── SHA-256(encrypted) → vote_hash
  ├── send_vote_to_blockchain(vote_hash) → tx_hash
  ├── Store AnonymousVoteRecord (NO voter_id)
  ├── Store HasVotedLog (user_id + debate_id ONLY — no vote)
  ├── voter_id = None; del voter_id  ← BRIDGE DESTROYED
  └── Return verification_code to voter
```

---

## For production

### 1. PostgreSQL
```
DATABASE_URL=postgresql://user:pass@host:5432/preferendum
```

### 2. Polygon blockchain
Deploy `PreferendumVote.sol` then set in `.env`:
```
CONTRACT_ADDRESS=0x...
PREFERENDUM_WALLET_KEY=...
PREFERENDUM_WALLET_ADDRESS=0x...
```
The system uses mock tx hashes in dev — no votes are lost.

### 3. Change all secrets in `.env`
- `JWT_SECRET`
- `SESSION_SECRET`
- `VOTE_ENCRYPTION_KEY`

---

## File structure

```
preferendum/
├── main.py                          # App entry point — all routers wired
├── db.py                            # Database connection
├── models.py                        # All SQLAlchemy models
├── vote_routes.py                   # Vote submission + bridge destruction
├── routes_debate.py                 # Debates + comments + ad injection
├── routes_question.py               # Question stubs
├── requirements.txt
├── .env.template                    # Copy to .env and fill in
├── test_system.py                   # Full automated test suite
├── auth/
│   ├── routes_auth.py               # Register, Login, JWT
│   ├── security.py                  # bcrypt + JWT
│   └── __init__.py
├── utils/
│   ├── encryptor.py                 # AES-256-CBC vote encryption
│   └── blockchain.py                # Polygon integration + dev fallback
├── advertising/
│   └── ad_matching_engine.py        # Match ads to voter profile
├── advertiser/
│   ├── routes_ads_upload.py         # Create campaigns
│   └── routes_dashboard.py          # Campaign stats
├── distribution/
│   └── routes_distribute_ads.py     # Get ads for user
├── tracking/
│   └── routes_track_views.py        # Record impressions (20 CLP/view)
├── verification/
│   ├── routes_vote_verification.py  # Self-verify vote
│   └── routes_global_stats.py       # Platform stats
└── results/
    └── results_router.py            # Live results + demographics
```
