# Preferendum — Daily Work Log

Plain-language record of what changed each day, why, and how it was verified —
so anyone (a new developer, an auditor, Juan Carlos) can pick up exactly where
the last entry left off, with no guessing and no need to trust anyone's memory.

Format per entry: **Date — what changed — why — how it was proven to work — what's next**

---

## 2026-06-06

**Branch:** `working-copy-2026-06-06` (isolated copy, branched off tag
`checkpoint-2026-06-06-verified-matrix-matching`, which is the last fully
verified-good state — safe to roll back to at any time with zero loss)

**What changed:**
1. Restored the device/IMEI anti-fraud vote lock — it was silently dead because
   the verification step that populates it was unreachable in the app. Now a
   background call registers each device's fingerprint right after registration
   and login, with no new screens or user friction.
2. Fixed three fake verification steps in the registration flow (SMS code,
   ID-document upload, device/SIM registration) that were `setTimeout` placeholders
   pretending to call the backend — they now make real calls to the real endpoints.
3. Fixed the campaign↔consultation targeting mismatch — campaigns now actually
   check whether their targeting (country/commune/gender/age) is compatible with
   each consultation's own scope, instead of ignoring it entirely.
4. Added an admin tool to deactivate test/expired ad campaigns (so QA campaigns
   never pollute what investors or auditors see).
5. Tagged the verified state and pushed the tag to GitHub as a permanent rollback
   point.

**How it was proven (not claimed):**
- Created two real test campaigns through the live production API with deliberately
  narrow targeting, queried the real production matching function across four
  consultations with different scopes, and confirmed the results matched expectations
  exactly — then deactivated the test campaigns and confirmed they're gone.
- Raw command + raw server response for every check is in this session's history —
  reproducible by anyone with a terminal, no coding knowledge required to read the
  ✅/❌ output.

**Known gaps — still real, not yet fixed (do not claim these work):**
- The "7-layer verification" screen only ever completes step 1 (email) — the success
  handler exits straight to the app feed instead of advancing to step 2, so steps 2-7
  (now individually fixed) are still unreachable in the live user flow. Needs a
  structural fix to the handoff, tested carefully so it doesn't block real users
  if SMS/Rekognition have a bad moment during a live demo.
- The "Portal Institucional" (organizer) login screen collects org name/email/password
  but never sends them anywhere — no real account/auth sits behind consultation or
  campaign creation. `POST /debates` and `POST /marketer/campaigns` accept anonymous
  requests. This should get real authentication before any real institutional rollout.
- `GET /organizer/consultations`, `GET /organizer/consultations/{id}/results`,
  `/marketer/estimate`, `/marketer/communes` exist and work on the backend but the
  app never calls them — "my consultations" and CPM-by-commune views are
  session-only / hardcoded placeholders in the UI.

**Next planned work:**
- Build a one-command, plain-language pass/fail test script against the live system
  (so anyone — Juan Carlos, university auditors, anyone with a terminal — can verify
  every claim themselves, without trusting anyone's word, mine included).
- Then close the known gaps above, one at a time, each one proven live before being
  marked done — same standard as the matrix-matching fix.

**Where to resume:** start from "Next planned work" above. The isolated branch
`working-copy-2026-06-06` is where new work happens — `main` and the checkpoint tag
stay untouched and safe until a change is proven and ready to be merged forward.

---

## 2026-06-07 — closing the "7-layer verification" gap

**Branch:** `working-copy-2026-06-06` (still isolated, still safe to roll back)
**Commit:** `b53e2d94`

**What changed (the verification chain is now real end to end, not a facade):**
1. Step 1 (email) used to finish by sending the user straight to the feed —
   steps 2 through 7 were unreachable no matter how good they were. Now
   confirming the email code advances to step 2, and each step already chains
   correctly into the next (2→3→4→5→6→7), so the full chain is now reachable.
2. Step 6 ("Geolocation") was completely fake — a 1.8s fake spinner that always
   displayed "Chile detectado / Ubicación confirmada" with no real check behind
   it. It now asks the device for its real GPS position and sends it to the
   backend's `/verify/location` endpoint (which existed and worked, but nothing
   ever called it). The on-screen text no longer claims a confirmation that
   hasn't happened yet.
3. Step 7 ("Blockchain") was completely fake — a 2.8s fake spinner that
   displayed a **made-up transaction hash** (`TX: 0x7212c52de19...`) typed
   directly into the screen, regardless of anything real happening. It now
   asks the user for their real wallet address (with an optional "Conectar con
   MetaMask" button when the browser supports it) and sends it to the backend's
   real `/verify/wallet` endpoint. The fabricated hash is gone completely.
4. Removed the on-screen promise "si no tienes wallet, te creamos una
   automáticamente" — building a secure system that generates and custodies
   private keys is its own multi-week project with real security stakes
   (a half-built version would be worse than not having it). Saying only what
   the system actually does, even if that's a smaller claim, is the whole point
   of this week's work.
5. Lightened three colors that were nearly invisible against the app's dark
   navy background (`#090D18`): the "organizer" and "marketer" buttons on the
   choose-your-path screen, and the results bar gradient.

**How it was proven:**
- Extracted the live script block from `assets/app.html` and ran `node --check`
  before and after every edit — zero syntax errors introduced.
- Traced every `setVfStep(N)` call by hand to confirm the chain 1→2→3→4→5→6→7
  has no remaining dead ends or premature exits to the feed.
- Confirmed both `/verify/location` and `/verify/wallet` exist and work on the
  live backend (main.py:1777 and main.py:1804) before wiring the UI to them —
  did not invent new backend behavior, only connected the app to what was
  already real and unused.

**Known gaps — still real, not yet fixed:**
- Same three items listed in the 2026-06-06 entry above (organizer/marketer
  login has no real auth behind it; several working backend endpoints are
  still unused by the UI). These are Monday's planned work.
- Wallet verification is honest but still shallow on the backend side: it only
  checks that the address has the right *shape* (`0x` + 40 hex chars), not that
  the user actually controls it (no signature challenge). That's a real,
  disclosed limitation — not a fabrication — and is in scope for a future pass,
  not these 84 hours.

**Where to resume:** Monday's work — wire the unused organizer/marketer backend
endpoints (`GET /organizer/consultations`, `GET /organizer/consultations/{id}/results`,
`/marketer/estimate`, `/marketer/communes`) into their real screens, and put real
authentication behind consultation/campaign creation.
