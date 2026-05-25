# CLAUDE.md — Preferendum Complete Build Instructions

## For Claude Code — Read this first before doing anything

---

## What is Preferendum

Preferendum is a **verified decision platform** — not just a voting app.

Any organization (companies, professional associations, productive sectors, universities, local governments) can ask questions to their members, customers, shareholders, or employees. Results are verified on blockchain, completely transparent, with a public Legitimacy Score.

**Key insight:** Preferendum sells "decision environments" — people who are actively deciding something, which is infinitely more valuable than passive scrolling. This is how advertising works here: ads appear between debate opinions, targeted by geographic purchasing power (housing m² proxy), never by personal data.

**Revenue model:**

1. Advertising CPM inside debates (targeted by commune/SE tier)
1. Organizational subscriptions for creating consultations

**Privacy architecture:**

- AES-256 vote encryption
- Bridge destruction: voter_id = None after vote
- XXXX-XXXX-XXXX verification code per vote
- Blockchain anchoring on Polygon (currently mock)
- Legitimacy Score: % of voters who verified their vote was counted correctly

---

## Current System State

### Backend — LIVE at https://preferendum-unzip.onrender.com

- FastAPI + SQLite on Render
- GitHub: github.com/jucaferla-eng/Preferendum-unzip
- Start command: `uvicorn main:app --host 0.0.0.0 --port 10000`

**Working endpoints:**

- POST /auth/register — registration with email OTP
- POST /auth/login — JWT login
- GET /auth/me — profile
- GET /debates — list debates
- GET /debates/feed — feed by country
- POST /debates/{id}/vote — vote, returns XXXX-XXXX-XXXX code
- POST /debates/{id}/verify — verify vote by code
- GET /debates/{id}/opinions — opinions with ads every 5
- POST /debates/{id}/opinions — post opinion
- GET /privacy — privacy policy HTML
- GET /marketers — marketer landing page
- GET /organizers — organizer landing page
- GET /organizer-panel — organizer dashboard

**Email:** Uses Gmail SMTP (GMAIL_USER + GMAIL_APP_PASSWORD env vars)
**SMS:** Twilio paid account (TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN)
**Blockchain:** Mock (generates fake 0x hash) — real Polygon pending

### Mobile App — iOS on TestFlight, Android on Google Play

- React Native + Expo
- Bundle ID iOS: com.caip.preferendumapp
- Bundle ID Android: com.caip.preferendum
- EAS Project: @jifg749090/preferendum
- Apple Team: 94LF36AQDA
- Apple App ID: 6765727101

---

## What's DONE (don't redo)

- ✅ Auth: register, login, JWT
- ✅ Debates: create, list, vote, verify, results, legitimacy score
- ✅ Bridge destruction implemented
- ✅ Opinions with ads every 5
- ✅ 3 demo debates pre-loaded
- ✅ Privacy policy page
- ✅ Marketer landing page at /marketers
- ✅ Organizer landing page at /organizers
- ✅ Organizer dashboard at /organizer-panel
- ✅ Feed loads from backend (with fallback to static data)
- ✅ Login connected to backend
- ✅ Register connected to backend
- ✅ Vote connected to backend (returns real XXXX-XXXX-XXXX)
- ✅ Vote verification connected to backend
- ✅ Debate room opinions loading from backend

---

## What's MISSING — Build this

### 1. ORGANIZER API ROUTES (add to main.py)

```python
# POST /organizer/register
# POST /organizer/consultations  — create a real debate
# GET /organizer/consultations   — list organizer's debates
# POST /organizer/closed-list    — upload authorized voter IDs (hashed)
# GET /organizer/consultations/{id}/results — detailed results
```

The organizer dashboard already exists at /organizer-panel. It needs:

- The "Nueva consulta" modal to actually call POST /organizer/consultations
- The results page to call GET /organizer/consultations/{id}/results
- Registration form to call POST /organizer/register

### 2. MARKETER API ROUTES (add to main.py)

```python
# POST /marketer/register
# POST /marketer/estimate        — budget allocation by commune CPM
# POST /marketer/campaigns       — launch campaign (creates DebateAd entries)
# GET /marketer/communes         — CPM table by commune
# GET /marketer/campaigns/{id}/metrics — impressions, voters reached
```

CPM table (housing m² proxy):

- SE A (>120m²): Vitacura $14.50, Las Condes $12.80, Providencia $11.20
- SE B (80-120m²): Ñuñoa $8.40, Macul $7.60, San Miguel $7.20
- SE C (55-80m²): Santiago $5.20, Recoleta $4.40, Maipú $5.60
- SE D (<55m²): La Pintana $3.20, El Bosque $3.40, Cerro Navia $3.00

### 3. COMMUNE AGENT (already written as commune_agent.py)

The CPM optimization logic is already in the outputs. Integrate it into the marketer routes.

### 4. EMAIL VERIFICATION FIX

Current state: Gmail SMTP fails with 535 error (bad credentials).
DNS for preferendum.com was added to NameBright (Resend DKIM records).
When DNS propagates (24-48h), update main.py to use Resend API:

```python
def send_email_otp(email, code, name=''):
    resend_key = os.getenv('RESEND_API_KEY')
    # POST to https://api.resend.com/emails
    # from: noreply@preferendum.com
```

### 5. DEBATE ROOM — POST OPINION UI

The debate room loads opinions from backend but has no UI to post a new opinion.
Add in App.js inside the debate screen:

- TextInput for new opinion
- Knowledge level selector (Expert/Good/Familiar/Low/New)
- Submit button → POST /debates/{id}/opinions

### 6. ORGANIZER PANEL — CREATE CONSULTATION FLOW

The organizer dashboard (preferendum_organizer.html at /organizer-panel) has a modal
for creating consultations but the form doesn't actually call the API.
Connect the "Publicar consulta" button to POST /organizer/consultations.

### 7. MARKETER PANEL — CREATE CAMPAIGN FLOW

The marketer dashboard (preferendum_marketers.html at /marketers) has a campaign
creation modal. Connect it to POST /marketer/campaigns.

### 8. SMART CONTRACT — Polygon (Preferendum.sol exists)

The Solidity contract is written but not deployed.
When wallet with MATIC is available:

- Deploy Preferendum.sol to Polygon mainnet
- Set CONTRACT_ADDRESS in Render environment
- Replace mock_blockchain_tx() with real Web3 call

---

## Architecture Decisions (don't change these)

1. **Debate room reads from TOP always** — never from bottom. Users must see all ads (every 5 opinions). This is the marketer metric: cost per voter who SAW the ad.
1. **Results are visible BEFORE voting** — but results are hidden (🙈) until after a voter casts their own vote. Show results after voting.
1. **Verification code (XXXX-XXXX-XXXX)** is only verifiable AFTER debate closing date.
1. **Legitimacy Score** is always public — the organizer cannot hide it.
1. **Bridge destruction** — voter_id is set to None immediately after vote is recorded. The identity is never linked to the vote in the database.
1. **Closed List** — organizer can upload a file of authorized voter IDs. System hashes them with SHA-256. When a voter tries to participate, their national_id is hashed and checked against the list.
1. **Ad placement** — ads appear every 5 opinions in debate room. The marketer metric is "cost per voter who SAW the ad" — not total debate voters.
1. **Corporate debates** — keep vote distribution private to the commissioning company, but always show the public legitimacy score.

---

## Environment Variables on Render (already set)

- JWT_SECRET ✅
- TWILIO_ACCOUNT_SID ✅
- TWILIO_AUTH_TOKEN ✅
- TWILIO_PHONE_NUMBER: +15075027781 ✅
- GMAIL_USER: jucaferla@gmail.com ✅
- GMAIL_APP_PASSWORD ✅ (535 error — fix with Resend when DNS propagates)
- SENDGRID_API_KEY ✅ (403 error — use Resend instead)
- RESEND_API_KEY ✅ (pending DNS verification)
- FROM_EMAIL: jucaferla@preferendum.com ✅

---

## Design System ("Democratic Precision")

- Background: #090D18 (deep civic navy)
- Primary blue: #2563EB
- Verified green: #10B981
- Democratic gold: #F59E0B
- Coral: #F43F5E
- White: #F0F4FF
- Muted: #64748B

---

## Priority Order

1. Add organizer + marketer API routes to main.py → push to GitHub → Render auto-deploys
1. Fix email: update send_email_otp to use Resend API
1. Connect organizer panel form to API
1. Connect marketer panel form to API
1. Add post-opinion UI to debate room in App.js
1. Build new iOS version and submit to App Store (version must be > 5.0.0, use 6.0.1)

---

## In memory of José Ignacio Fernández (1989–2024)
## Who proved the Preferendum concept through real civic voting campaigns.
