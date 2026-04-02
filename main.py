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
import models
import os

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Preferendum API",
    version="1.0.0",
    description="En memoria de José Ignacio Fernández (1989-2024)"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "preferendum-secret"))

@app.get("/")
def root():
    return {
        "system": "Preferendum",
        "version": "1.0.0",
        "status": "running",
        "dedication": "En memoria de José Ignacio Fernández (1989-2024)"
    }

@app.get("/health")
def health():
    return {"status": "ok"}
