#!/usr/bin/env python3
"""
test_system.py
Preferendum — Full system test
Runs against the local server and exercises every endpoint.

Usage:
  1. Start server: uvicorn main:app --reload
  2. Run tests:    python test_system.py

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import requests
import json
import sys

BASE = "http://localhost:8000"
PASS = "✅"
FAIL = "❌"

results = []

def test(name, fn):
    try:
        r = fn()
        ok = r.status_code in (200, 201)
        results.append((ok, name, r.status_code))
        mark = PASS if ok else FAIL
        print(f"  {mark}  {name} [{r.status_code}]")
        if not ok:
            print(f"       {r.text[:120]}")
        return r
    except Exception as e:
        results.append((False, name, "ERR"))
        print(f"  {FAIL}  {name} [ERROR: {e}]")
        return None

print("\n" + "="*55)
print("  PREFERENDUM — SYSTEM TEST")
print("="*55)

# ── 1. ROOT ──────────────────────────────────────────────────
print("\n[1] Root")
r = test("GET /", lambda: requests.get(f"{BASE}/"))
if r:
    data = r.json()
    print(f"       System: {data.get('system')} v{data.get('version')}")

# ── 2. REGISTER VOTER ────────────────────────────────────────
print("\n[2] Register voter")
voter = {
    "email":       "maria.gonzalez@test.cl",
    "name":        "María González",
    "password":    "SecurePass123!",
    "country":     "CL",
    "state":       "Región Metropolitana",
    "county":      "Las Condes",
    "dob":         "1990-05-15",
    "gender":      "F",
    "national_id": "12345678-9",
}
r = test("POST /auth/register", lambda: requests.post(f"{BASE}/auth/register", json=voter))
voter_id = r.json().get("id") if r and r.ok else None

# Register a second voter (male, different age)
voter2 = {
    "email":       "carlos.rodriguez@test.cl",
    "name":        "Carlos Rodríguez",
    "password":    "SecurePass456!",
    "country":     "CL",
    "state":       "Región Metropolitana",
    "county":      "Las Condes",
    "dob":         "1985-03-20",
    "gender":      "M",
    "national_id": "98765432-1",
}
r2 = test("POST /auth/register (voter 2)", lambda: requests.post(f"{BASE}/auth/register", json=voter2))

# ── 3. LOGIN ─────────────────────────────────────────────────
print("\n[3] Login")
r = test("POST /auth/login", lambda: requests.post(
    f"{BASE}/auth/login",
    data={"username": voter["email"], "password": voter["password"]},
))
token = r.json().get("access_token") if r and r.ok else None
headers = {"Authorization": f"Bearer {token}"} if token else {}
print(f"       Token: {token[:30]}…" if token else "       No token")

# Login voter 2
r2 = test("POST /auth/login (voter 2)", lambda: requests.post(
    f"{BASE}/auth/login",
    data={"username": voter2["email"], "password": voter2["password"]},
))
token2 = r2.json().get("access_token") if r2 and r2.ok else None
headers2 = {"Authorization": f"Bearer {token2}"} if token2 else {}

# ── 4. ME ────────────────────────────────────────────────────
print("\n[4] Current user")
r = test("GET /auth/me", lambda: requests.get(f"{BASE}/auth/me", headers=headers))
if r and r.ok:
    me = r.json()
    print(f"       User: {me['name']} · {me['gender']} · {me['county']} · {me['country']}")

# ── 5. CREATE ORGANIZER + DEBATES ────────────────────────────
print("\n[5] Create organizer and debates")

# Register organizer
org = {
    "email":       "municipalidad@lascondes.cl",
    "name":        "Municipalidad Las Condes",
    "password":    "OrgPass789!",
    "country":     "CL",
    "state":       "Región Metropolitana",
    "county":      "Las Condes",
    "dob":         "1980-01-01",
    "gender":      "O",
    "national_id": "76543210-K",
}
r_org = test("POST /auth/register (organizer)", lambda: requests.post(f"{BASE}/auth/register", json=org))

# Manually set role to organizer via DB (in test we'll just proceed)
r_org_login = test("POST /auth/login (organizer)", lambda: requests.post(
    f"{BASE}/auth/login",
    data={"username": org["email"], "password": org["password"]},
))
org_token = r_org_login.json().get("access_token") if r_org_login and r_org_login.ok else token
org_headers = {"Authorization": f"Bearer {org_token}"}

# For testing, use voter token — organizer role check bypassed in simplified test
debate_data = {
    "title":       "¿Prioridad para el presupuesto municipal 2027?",
    "description": "La Municipalidad de Las Condes consulta a sus vecinos sobre la asignación del presupuesto 2027.",
    "category":    "gov",
    "institution": "Municipalidad de Las Condes",
    "inst_type":   "gov",
    "country":     "CL",
    "state":       "Región Metropolitana",
    "county":      "Las Condes",
    "options":     ["Infraestructura vial", "Salud pública", "Educación", "Áreas verdes"],
    "end_dt":      "2026-12-31T18:00:00",
}

# Temporarily patch role check for test
r_deb = test("POST /debates/ (create)", lambda: requests.post(
    f"{BASE}/debates/", json=debate_data, headers=headers
))
debate_id = None
if r_deb and r_deb.ok:
    debate_id = r_deb.json().get("id")
    print(f"       Debate ID: {debate_id}")
else:
    # Try with a fallback — some setups require organizer role
    print("       Note: debate creation may require organizer role in production")
    debate_id = 1  # assume ID 1 for remaining tests

# ── 6. LIST DEBATES (personalized feed) ──────────────────────
print("\n[6] Personalized debate feed")
r = test("GET /debates/", lambda: requests.get(f"{BASE}/debates/", headers=headers))
if r and r.ok:
    data = r.json()
    print(f"       Feed items: {len(data.get('feed', []))} (debates + ads)")
    print(f"       Total debates: {data.get('total_debates', 0)}")

# ── 7. GET SINGLE DEBATE ─────────────────────────────────────
print("\n[7] Get debate detail")
if debate_id:
    r = test(f"GET /debates/{debate_id}", lambda: requests.get(
        f"{BASE}/debates/{debate_id}", headers=headers
    ))

# ── 8. POST COMMENT ──────────────────────────────────────────
print("\n[8] Post comment to debate")
if debate_id:
    r = test("POST /debates/{id}/comments", lambda: requests.post(
        f"{BASE}/debates/{debate_id}/comments",
        json={"content": "Creo que la salud pública debería ser la prioridad número uno."},
        headers=headers,
    ))
    r2c = test("POST /debates/{id}/comments (voter 2)", lambda: requests.post(
        f"{BASE}/debates/{debate_id}/comments",
        json={"content": "La infraestructura vial afecta a todos directamente cada día."},
        headers=headers2,
    ))

# ── 9. CAST VOTE ─────────────────────────────────────────────
print("\n[9] Cast votes — bridge destruction")
vcode = None
if debate_id:
    vote_payload = {"debate_id": debate_id, "option_selected": "Salud pública"}
    r = test("POST /vote/ (voter 1)", lambda: requests.post(
        f"{BASE}/vote/", json=vote_payload, headers=headers
    ))
    if r and r.ok:
        data = r.json()
        vcode = data.get("verification_code")
        tx    = data.get("tx_hash", "")
        print(f"       ✓ Verification code: {vcode}")
        print(f"       ✓ Blockchain tx: {tx[:30]}…")

    # Voter 2 votes differently
    vote2_payload = {"debate_id": debate_id, "option_selected": "Infraestructura vial"}
    r2v = test("POST /vote/ (voter 2)", lambda: requests.post(
        f"{BASE}/vote/", json=vote2_payload, headers=headers2
    ))

    # Double-vote prevention
    r_dup = test("POST /vote/ (duplicate — must fail 409)", lambda: requests.post(
        f"{BASE}/vote/", json=vote_payload, headers=headers
    ))
    if r_dup:
        expected = r_dup.status_code == 409
        print(f"       {'✅' if expected else '❌'} Duplicate correctly {'rejected' if expected else 'NOT rejected'} [{r_dup.status_code}]")

# ── 10. CHECK VOTED ──────────────────────────────────────────
print("\n[10] Check voted status")
if debate_id:
    r = test("GET /vote/check/{debate_id}", lambda: requests.get(
        f"{BASE}/vote/check/{debate_id}", headers=headers
    ))
    if r and r.ok:
        print(f"       has_voted: {r.json().get('has_voted')}")

# ── 11. RESULTS ──────────────────────────────────────────────
print("\n[11] Live results")
if debate_id:
    r = test(f"GET /results/{debate_id}", lambda: requests.get(
        f"{BASE}/results/{debate_id}", headers=headers
    ))
    if r and r.ok:
        data = r.json()
        print(f"       Total votes: {data.get('total_votes')}")
        for opt in data.get("results", []):
            bar = "█" * int(opt["percentage"] / 5)
            print(f"       {opt['option'][:30]:30} {bar} {opt['percentage']}% ({opt['votes']}v)")
        print(f"       Irreversible: {data.get('is_statistically_irreversible')}")

# ── 12. SELF-VERIFICATION ────────────────────────────────────
print("\n[12] Self-verification (José's insight)")
if vcode:
    r = test(f"GET /verify/vote/{vcode}", lambda: requests.get(
        f"{BASE}/verify/vote/{vcode}"
    ))
    if r and r.ok:
        data = r.json()
        print(f"       Verified: {data.get('verified')}")
        print(f"       Vote hash: {data.get('vote_hash', '')[:30]}…")
        print(f"       TX: {data.get('tx_hash', '')[:30]}…")

# ── 13. AD CAMPAIGN ──────────────────────────────────────────
print("\n[13] Ad campaign creation + tracking")
import requests as req
r_ad = test("POST /advertiser/upload-campaign/", lambda: req.post(
    f"{BASE}/advertiser/upload-campaign/",
    data={
        "advertiser_email":     "samsung@test.com",
        "advertiser_name":      "Samsung Galaxy",
        "campaign_title":       "Galaxy S26 — Ya disponible",
        "budget_clp":           "500000",
        "ad_type":              "banner",
        "target_country":       "CL",
        "target_gender":        "all",
        "target_age_ranges":    "18-24,25-34,35-44",
        "target_categories":    "gov,priv",
        "excluded_categories":  "",
        "blocked_competitors":  "Apple,Xiaomi",
        "start_date":           "2026-01-01T00:00:00",
        "end_date":             "2026-12-31T23:59:59",
    }
))
campaign_id = r_ad.json().get("campaign_id") if r_ad and r_ad.ok else None
if campaign_id:
    print(f"       Campaign ID: {campaign_id}")

    # Track impression
    r_track = test("POST /ads/view/", lambda: req.post(
        f"{BASE}/ads/view/",
        json={
            "campaign_id": campaign_id,
            "debate_id":   debate_id,
            "gender":      "F",
            "age_group":   "25-34",
            "county":      "Las Condes",
            "country":     "CL",
        }
    ))
    if r_track and r_track.ok:
        print(f"       Spent CLP: {r_track.json().get('spent_clp')}")

    # Dashboard
    r_dash = test(f"GET /advertiser/dashboard/{campaign_id}", lambda: req.get(
        f"{BASE}/advertiser/dashboard/{campaign_id}"
    ))
    if r_dash and r_dash.ok:
        d = r_dash.json()
        print(f"       Impressions: {d.get('impressions')} · Spent: ${d.get('spent_clp')} CLP")

# ── 14. GLOBAL STATS ─────────────────────────────────────────
print("\n[14] Global stats")
r = test("GET /stats/global", lambda: requests.get(f"{BASE}/stats/global"))
if r and r.ok:
    s = r.json()
    print(f"       Votes: {s['total_votes']} · Debates: {s['total_debates']} · Voters: {s['total_voters']}")

# ── SUMMARY ──────────────────────────────────────────────────
print("\n" + "="*55)
passed = sum(1 for ok,_,_ in results if ok)
total  = len(results)
print(f"  RESULTS: {passed}/{total} passed")
if passed == total:
    print("  ✅ ALL TESTS PASSED — System is working")
else:
    failed = [(n,c) for ok,n,c in results if not ok]
    print(f"  ❌ Failed:")
    for n,c in failed:
        print(f"     · {n} [{c}]")
print("="*55)
print("  En memoria del Socio Fundador José Ignacio Fernández (1989–2024)")
print("="*55 + "\n")

sys.exit(0 if passed == total else 1)
