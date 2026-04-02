# ============================================================
# Preferendum — main.py
# Complete unified FastAPI application
# All modules wired together and working
#
# In memory of José Ignacio Fernández (1989–2024)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from db import engine, Base
import models  # registers all SQLAlchemy models

# Route modules
from auth.routes_auth import router as auth_router
from vote_routes import router as vote_router
from routes_debate import router as debate_router
from routes_question import router as question_router
from advertiser.routes_ads_upload import router as ads_upload_router
from advertiser.routes_dashboard import router as ads_dashboard_router
from distribution.routes_distribute_ads import router as ads_dist_router
from tracking.routes_track_views import router as tracking_router
from verification.routes_vote_verification import router as verification_router
from verification.routes_global_stats import router as stats_router
from results.results_router import router as results_router

import os

# ── CREATE TABLES ───────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── APP ─────────────────────────────────────────────────────
app = FastAPI(
    title="Preferendum API",
    description="Democratic voting platform — verified, anonymous, blockchain-anchored.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── MIDDLEWARE ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "preferendum-dev-secret-change-in-prod"),
)

# ── ROUTERS ──────────────────────────────────────────────────
app.include_router(auth_router)           # /auth/register  /auth/login  /auth/me
app.include_router(vote_router)           # /vote/
app.include_router(debate_router)         # /debates/
app.include_router(question_router)       # /questions/
app.include_router(ads_upload_router)     # /advertiser/upload-campaign/
app.include_router(ads_dashboard_router)  # /advertiser/dashboard/{id}
app.include_router(ads_dist_router)       # /ads/user/{user_id}
app.include_router(tracking_router)       # /ads/view/
app.include_router(verification_router)   # /verify/vote/
app.include_router(stats_router)          # /stats/global
app.include_router(results_router)        # /results/{debate_id}

# ── ROOT ─────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "system": "Preferendum",
        "version": "1.0.0",
        "status": "running",
        "dedication": "En memoria de José Ignacio Fernández (1989–2024)",
        "docs": "/docs",
        "modules": [
            "auth", "voting", "debates", "questions",
            "advertising", "tracking", "verification", "results"
        ]
    }
