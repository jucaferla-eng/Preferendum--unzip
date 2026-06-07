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

---

## 2026-06-07 (continued) — organizer/marketer panels now run on real accounts and real numbers

**Branch:** `working-copy-2026-06-06`
**Commits:** `6b9beca9`, `c2ad14fa`, `42aff69c` (fast-forwarded to `main`, deployed)

**What changed:**
1. The institutional "Entrar al portal" button used to do nothing real — now it
   calls `/organizer/login`, and if that account doesn't exist yet, it registers
   one via `/organizer/register` and logs straight in. Person-type accounts are
   now auto-approved on the backend (a one-person account has no company/RUT
   for a reviewer to check, so there's nothing to gate on); company accounts
   still go to manual review, matching what the portal already promised.
2. "Publicar consulta" used to call a generic `/debates` endpoint without the
   organizer's auth token and read a response key (`data.debate`) the real
   endpoint never returns. Now it requires login, calls the real
   `/organizer/consultations`, and reads `data.consultation`.
3. The marketer "Lanzar campaña" button used to swallow every error silently
   (`catch (_) {}`) and always show "¡Campaña lanzada!" even when the server
   rejected it — a textbook fake-success facade. It now shows the real campaign
   ID the server assigned, or a real error message when the launch fails.
4. The marketer dashboard showed made-up totals for "Impresiones", "Gasto" and
   "% en público objetivo" no matter who was logged in. It now aggregates real
   numbers from `GET /marketer/campaigns/{id}/metrics` for the campaigns this
   account actually launched, and shows "—" honestly while loading / before any
   campaign exists.
5. The organizer "Dashboard en vivo" stats grid showed the same hardcoded
   "245 votos / 86% participación / 3 debates / 1 en verificación" for every
   account. It now aggregates real totals from `GET /organizer/consultations`
   (votes, count, live, verifying) — or "—" while loading.
6. The "Integridad del sistema" card listed three made-up consultations with
   made-up Legitimacy Scores ("Presupuesto 2027: 98%", "Plan movilidad: 97%",
   "Global: 97.5%") — the exact kind of fabricated number that would sink this
   project's credibility if an auditor noticed it didn't match anything in the
   database. It now lists the organizer's real consultations with their real,
   server-computed `legitimacy_score`, and shows an honest "Sin votos
   verificados aún" / empty state for consultations or accounts with no data.
7. Added a small backend endpoint, `PATCH /admin/debates/{id}?status=`, so test
   consultations created while proving this work can be closed/hidden cleanly
   afterward (modeled on the existing `/admin/campaigns/{id}/deactivate`).

**How it was proven:**
- Wrote `/tmp/e2e_proof_2026-06-07.py` — a script that runs against the live
  production server (not local, not mocked): registers a real organizer
  account, confirms it's auto-approved, creates a real consultation through the
  authenticated route, confirms it shows up in "mis consultas", registers a
  real marketer account, launches a real campaign, reads its real metrics
  (confirming budget and zero fabricated impressions), then cleans up both
  the test consultation and campaign via admin endpoints. **15/15 checks
  passed** against the live server at preferendum-unzip-d2zd.onrender.com.
- After the dashboard rewrite, extracted the live script block from the
  deployed `/app` page and parsed it with `acorn` (`ecmaVersion: 2020`) — caught
  and fixed a missing closing parenthesis (the new conditional rendering added
  one extra nesting level that the old hardcoded array didn't have) before it
  ever reached a user. Confirmed `LIVE_PARSE_OK` against the deployed page
  after the fix, and confirmed by string search that the fabricated numbers
  ("Presupuesto 2027", "Plan movilidad… 97", "Global… 97.5") are gone from the
  live bundle and the real "Legitimacy Score por consulta (público, real)" card
  is present.

**Known gaps — still real, not yet fixed:**
- `GET /organizer/consultations/{id}/results` (results detail view),
  `/marketer/estimate` (budget allocation), and `/marketer/communes`
  (CPM-by-commune table) are real, working backend endpoints that no screen
  calls yet. That's tomorrow's (Tuesday's) work, alongside the TestFlight
  rebuild — `App.js` loads `assets/app.html` from a bundled local file, so
  these `app.html` changes are already live on the web `/app` route but won't
  reach the mobile app until a new build is uploaded.

**Where to resume:** wire `GET /organizer/consultations/{id}/results`,
`/marketer/estimate`, `/marketer/communes` into their screens, then do a full
regression pass on all three flows (voter, organizer, marketer) before building
and uploading the new TestFlight version.

---

## 2026-06-07 (continued II) — closed all three remaining unused-endpoint gaps, found and fixed two more fabrications

**Branch:** `working-copy-2026-06-06` (fast-forwarded to `main`, deployed)
**Commit:** `3097b8fe`

**What changed:**
1. "Integridad del sistema" (organizer): each consultation card now has a
   "Ver resultados reales →" toggle that expands a real panel calling
   `GET /organizer/consultations/{id}/results` — shows the real
   `verifications.confirmed/total` count and real gender/age demographics
   from actual votes, with an honest "aún no hay votos verificados para
   mostrar demografía real" empty state. No invented numbers.
2. Marketer "Revisa y lanza" step: added an "Estimación real del servidor"
   card with a button that calls `POST /marketer/estimate` — the same CPM
   optimization engine the backend uses to actually allocate the campaign's
   budget — and shows real `total_impressions`, `total_contacts_est`,
   `cost_per_contact_clp`, `cpm_promedio`, and the top 5 commune allocations
   by budget share. This **replaced a fabrication**: `estImp` was a pure
   client-side guess (`budget / 4.8`, no relation to the real CPM table)
   that was being shown as "Impresiones estimadas" in three different
   screens (budget step, review step, post-launch summary). All three are
   now gone — removed entirely rather than leaving a fake number next to a
   real one.
3. Marketer "Presupuesto" step: added a "Tabla CPM real por comuna" card
   that calls `GET /marketer/communes` and lists the live CPM-by-commune
   table (with SE tier and source: "database" vs "fallback") — the actual
   data the optimization engine reads when it allocates a budget.
4. **Found and fixed two more fabrications while working through this list**
   (not in the original known-gaps list — caught by reading the surrounding
   code while wiring the real features in):
   - Marketer hub "Campañas activas" was hardcoded to **always** show two
     fake campaigns ("Samsung Galaxy" and "L'Oréal Paris" with invented
     impressions and spend — 510/CLP 10,200 and 265/CLP 5,300) regardless
     of which account was logged in or whether it had ever launched
     anything. Replaced with the account's real launched campaigns
     (aggregated from `GET /marketer/campaigns/{id}/metrics`, the same data
     source `mktStats` already used), each showing its real title,
     targeting, impressions, spend, and a real "● En vivo / Pausada" badge
     driven by the campaign's actual `is_active` flag — plus an honest
     "aún no has lanzado ninguna campaña" empty state.
   - The institutional "Publicidad" preview tab showed the *same two fake
     campaigns* with an unconditional "● En vivo" badge — i.e. presented as
     real live platform activity to every organizer account. There is no
     public endpoint suitable for listing genuinely live campaigns on this
     screen, so rather than inventing one under time pressure, the honest
     fix was to relabel it: badge now reads "Ejemplo" (neutral grey, not
     green) and the heading gained a one-line caption — "Así luce una
     campaña dentro de Preferendum (ejemplo ilustrativo, no son campañas
     reales en curso)". A clearly-labeled illustrative mockup is not a
     fabrication; presenting invented numbers as live activity is — this
     fix draws that line correctly.

**How it was proven:**
- Wrote `/tmp/e2e_marketer_estimate_communes.py` and ran it against the
  live production server: `GET /marketer/communes` returned 34 real rows
  (source=database) with the correct shape, and `POST /marketer/estimate`
  — sent the *exact* payload shape the new UI button now sends — returned
  a real allocation across 16 communes with real impressions/CPM math
  (e.g. La Pintana: CPM $3.10, 9.8% of budget, 16,566 impressions). Both
  ✅. Script deleted after the run (its purpose was proof, not a fixture).
- Extracted the live script block from `assets/app.html` after every single
  edit and ran both `node --check` and `acorn.parse(..., {ecmaVersion: 2020})`
  — every edit passed clean on the first or corrected attempt before moving
  to the next. Zero syntax errors reached the commit.
- After deploying, pulled the live `/app` page and grepped it directly:
  confirmed `estImp` appears **zero** times (the fabrication is gone from
  production, not just from the source), confirmed the real-data hooks
  (`myCampaignsDetail`, `Estimación real del servidor`, `Tabla CPM real por
  comuna`, the empty-state copy) are present in the deployed bundle, and
  confirmed the "● En vivo" badge is now driven by `ad.active ? ... : ...`
  (a real boolean) rather than being a hardcoded string, with the
  illustrative-example badge correctly relabeled "Ejemplo".

**Known gaps — still real, not yet fixed:**
- None of the four originally-listed unused organizer/marketer endpoints
  remain unused — this closes that list completely.
- The institutional "Publicidad" tab still shows an illustrative example
  rather than real live campaign data, because no public endpoint exists to
  list genuinely-live campaigns for that screen. This is now honestly
  labeled rather than hidden — a real (smaller) feature for a future pass
  if organizers need to see real live ads on the platform, not a blocker.

**Where to resume:** Tuesday's plan — full regression pass on all three
flows (voter, organizer, marketer) live, then build and upload the new
TestFlight version (these `app.html` changes are live on the web `/app`
route now, but `App.js` bundles a local copy for mobile, so they won't
reach iOS/Android until a fresh build is submitted).

---

## 2026-06-07 (continued III) — automated integrity-test suite, running unattended after every deploy

**Branch:** `working-copy-2026-06-06` (fast-forwarded to `main`, deployed)
**Commits:** `91f0b64c` (suite + ad-frequency + opinion polling), `d5948e84` (CI deploy-race fix)

**What changed:**
1. Added `tests/test_vote_integrity.py` — a pytest suite that runs against
   the LIVE production server (no mocks, no local server) with fresh
   disposable accounts and a disposable consultation it creates and closes
   itself. It proves, end to end, the five things the founder asked an
   unattended system to verify after every deploy:
   - **An account can't vote twice** in the same consultation (409 "Ya
     votaste en esta consulta").
   - **A device can't be used to vote twice** — proven via the *actual*
     mechanism (`/verify/imei` permanently binds an IMEI hash to one
     account, 409 "Device already registered to another account" the
     instant a second account tries), not just the `cast_vote` backstop
     check, because the backstop can never be reached through the normal
     registration flow — the front door is the one that's locked.
   - **A national ID (RUT/DNI) can't vote twice**, even from a totally
     different account and device (409 "Este documento de identidad ya
     votó en esta consulta").
   - **Bridge destruction is real** — `voter_id` is `None` on the live
     vote row the instant the vote is recorded, checked directly against
     the database via a new admin-gated proof endpoint, not inferred.
   - **Verification codes are unique and valid** — `XXXX-XXXX-XXXX` shape,
     distinct across two independent votes, and each one resolves to the
     correct chosen option through the public `/debates/{id}/verify` route.
2. Added two `ADMIN_SECRET`-gated test-support endpoints to `main.py`
   (same pattern as the existing `/admin/*` routes):
   - `GET /admin/test-otp` — returns the current pending OTP for an
     account+channel, so CI can finish email verification despite the
     known-broken email pipeline (Gmail 535 / Resend pending DNS — see
     "EMAIL VERIFICATION FIX" above) without reading a real inbox.
   - `GET /admin/test-vote-bridge` — returns the literal `voter_id` and a
     computed `bridge_destroyed` boolean for a given verify_code+debate.
     Dual-purpose: CI proof, and a tool independent auditors can use to
     check this core privacy claim against the live database themselves.
3. Added `.github/workflows/integrity-tests.yml` — runs the suite
   automatically on every push to `main` (i.e. after every deploy, since
   Render watches `main`), daily at a quiet hour, and on demand
   (`workflow_dispatch`). Reports PASS/FAIL with zero human involvement,
   exactly as requested: *"Los test deben correr solos, sin intervención
   humana, y reportar Pass o Fail."*
4. Set `AD_EVERY_N_OPINIONS = 2` (was a hardcoded `5`) — a temporary,
   founder-requested change to speed up testing the ad/campaign-metrics
   cycle before Wednesday's investor lunch. Documented inline in `main.py`
   with an explicit note to revert to `5` (the documented production value)
   once testing is done.
5. Added 20-second opinion-list polling to the debate room in `app.html` —
   while a user is in a single-topic debate, they now see other people's
   opinions appear as they're posted in real time, matching the founder's
   description: *"verá quienes pasaron antes y dieron su opinión o la
   están dando en ese momento simultáneamente."* No invented activity —
   it's the real `GET /debates/{id}/opinions` response, refreshed.

**A real bug found and fixed mid-stream — the deploy-race condition:**

The very first CI run failed with **404 Not Found** on the brand-new admin
endpoints — alarming at first glance, but the diagnosis was simple: GitHub
Actions starts running the instant you `git push`, while Render takes
**~10-15 minutes** to actually finish deploying that push. The workflow was
testing the *previous* live deploy — which, correctly, didn't have this
commit's new routes yet. Not a test bug, not a backend bug — a race between
two independent systems that needed an explicit handshake.

**Fix (`d5948e84`):** `/health` now reports `git_commit` (Render sets
`RENDER_GIT_COMMIT` automatically on every deploy). The workflow gained a
"wait for this commit to actually be live" step that polls `/health` until
`git_commit` matches `github.sha` — the exact commit that triggered the
run — before running a single test. Job timeout raised to 60 minutes to
give both that wait (~15 min) and the slow, separately-disclosed
email-bound registration flow (~3-4 min per account) real headroom, so
neither shows up as a false "FAIL" on the thing actually being tested.

**How it was proven (not claimed):**
- Ran `tests/test_vote_integrity.py` directly against the live production
  server at `preferendum-unzip-d2zd.onrender.com` with `pytest -v`:
  ```
  tests/test_vote_integrity.py::test_same_account_cannot_vote_twice PASSED
  tests/test_vote_integrity.py::test_same_device_cannot_vote_twice_across_accounts PASSED
  tests/test_vote_integrity.py::test_same_national_id_cannot_vote_twice_across_accounts PASSED
  tests/test_vote_integrity.py::test_bridge_destruction_and_unique_valid_code PASSED
  ================== 4 passed, 1 warning in 1114.71s (0:18:34) ===================
  ```
  **4/4 — every one of the five requested checks confirmed live**, with
  real accounts, a real consultation, real votes, real verification codes,
  and a direct read of the live database row proving `voter_id is None`.
  (It's slow — ~18 minutes — entirely because each disposable test account
  has to wait through the same broken email-OTP path real users hit; the
  `/admin/test-otp` endpoint works around *reading* it, not the backend's
  send-and-commit latency, which is honest and correct.)
- Confirmed the deploy of `91f0b64c` went live by polling `/admin/debug-ads`
  and seeing `ads_would_show_at_indices` step by 2 instead of 5, and by
  calling the two new admin endpoints directly and getting real "User not
  found" / "Vote not found" responses (proving the routes exist and the
  `ADMIN_SECRET` gate works) instead of generic 404s.
- Confirmed the GitHub Actions run that failed was run `27101966390`,
  created at `2026-06-07T19:06:29Z` — within seconds of the `91f0b64c`
  push and ~3 minutes before the deploy actually finished propagating
  (confirmed live at ~19:09 UTC by the same `/admin/debug-ads` probe) —
  which is exactly the race window the fix now closes.

**Known gaps — still real, not yet fixed:**
- `AD_EVERY_N_OPINIONS = 2` is a temporary testing value — **must be
  reverted to `5`** (the documented production value in `CLAUDE.md`) once
  the pre-lunch testing window closes. It's commented inline so this isn't
  forgotten.
- The integrity suite is slow (~18 min/run) purely because of the broken
  email pipeline — once Resend's DNS verification completes and
  `send_email_otp` switches over (see "EMAIL VERIFICATION FIX"), real
  registration (and this suite) should get dramatically faster. Not a
  suite problem; a downstream-dependency problem, disclosed and tracked.
- This was pushed from the local machine because the CI fix needed to be
  proven against the live system before trusting CI to prove itself — a
  bit of a bootstrapping problem inherent to "writing the thing that
  checks your work." The *next* CI run (auto-triggered by this push, or
  manually triggered via GitHub's Actions tab → "integrity-tests" →
  "Run workflow") is the first one that should go green on its own, with
  the deploy-wait step doing its job. Worth checking once it runs.

**Where to resume:** verify the next CI run goes green (auto on push, or
trigger manually from the Actions tab — `gh` CLI isn't installed locally
and the dispatch API needs auth we don't have). Then back to Tuesday's
plan: full regression pass + TestFlight rebuild. Also remember to revert
`AD_EVERY_N_OPINIONS` to `5` before the investor lunch.
