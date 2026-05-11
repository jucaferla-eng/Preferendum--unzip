"""
verification.py
===============
PREFERENDUM — Sistema de Verificación de Identidad

Maneja:
1. Email OTP — vía SendGrid
2. SMS OTP — vía Twilio
3. Generación y validación de códigos

Agregar al main.py:
    from verification import router as verify_router
    app.include_router(verify_router)

Variables de entorno requeridas:
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER
    SENDGRID_API_KEY
    FROM_EMAIL (ej: noreply@preferendum.com)
"""

import os
import random
import string
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/verify", tags=["verification"])

# ══════════════════════════════════════════════════════════════
# IN-MEMORY OTP STORE (replace with Redis or DB in production)
# ══════════════════════════════════════════════════════════════

otp_store = {}  # {email_or_phone: {code, expires_at, attempts}}

def generate_otp() -> str:
    """Generate 6-digit OTP code."""
    return ''.join(random.choices(string.digits, k=6))

def store_otp(key: str, code: str, expires_minutes: int = 10):
    otp_store[key] = {
        "code": code,
        "expires_at": (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat(),
        "attempts": 0,
    }

def validate_otp(key: str, code: str) -> bool:
    if key not in otp_store:
        return False
    entry = otp_store[key]
    if datetime.utcnow() > datetime.fromisoformat(entry["expires_at"]):
        del otp_store[key]
        return False
    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del otp_store[key]
        raise HTTPException(400, "Too many attempts. Request a new code.")
    if entry["code"] == code:
        del otp_store[key]
        return True
    return False


# ══════════════════════════════════════════════════════════════
# SMS — TWILIO
# ══════════════════════════════════════════════════════════════

def send_sms_otp(phone: str, code: str) -> bool:
    """Send OTP via Twilio SMS."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token   = os.getenv("TWILIO_AUTH_TOKEN")
    from_number  = os.getenv("TWILIO_PHONE_NUMBER", "+15075027781")

    if not account_sid or not auth_token:
        print(f"[Twilio] MOCK - Would send {code} to {phone}")
        return True  # Mock for development

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=f"Your Preferendum verification code is: {code}. Valid for 10 minutes.",
            from_=from_number,
            to=phone
        )
        print(f"[Twilio] SMS sent to {phone}: {message.sid}")
        return True
    except Exception as e:
        print(f"[Twilio] Error: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# EMAIL — SENDGRID
# ══════════════════════════════════════════════════════════════

def send_email_otp(email: str, code: str) -> bool:
    """Send OTP via SendGrid email."""
    api_key    = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "noreply@preferendum.com")

    if not api_key:
        print(f"[SendGrid] MOCK - Would send {code} to {email}")
        return True  # Mock for development

    try:
        import urllib.request
        import urllib.parse

        html_content = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;background:#07090f;color:#fff;padding:40px;border-radius:12px;">
            <h1 style="color:#3b82f6;font-size:28px;margin-bottom:4px;">prefer<span style="color:#fff">endum</span></h1>
            <p style="color:#94a3b8;margin-top:0;">Verified democracy</p>
            <hr style="border:1px solid #1e2a3d;margin:24px 0;">
            <p style="font-size:16px;">Your verification code is:</p>
            <div style="background:#1e2a3d;border-radius:8px;padding:24px;text-align:center;margin:20px 0;">
                <span style="font-size:36px;font-weight:bold;letter-spacing:8px;color:#3b82f6;">{code}</span>
            </div>
            <p style="color:#94a3b8;font-size:14px;">Valid for 10 minutes. Do not share this code with anyone.</p>
            <hr style="border:1px solid #1e2a3d;margin:24px 0;">
            <p style="color:#4a5568;font-size:12px;font-style:italic;">
                In memory of Jose Ignacio Fernandez (1989-2024)
            </p>
        </div>
        """

        data = json.dumps({
            "personalizations": [{"to": [{"email": email}]}],
            "from": {"email": from_email, "name": "Preferendum"},
            "subject": f"Your Preferendum code: {code}",
            "content": [
                {"type": "text/plain", "value": f"Your Preferendum verification code is: {code}. Valid for 10 minutes."},
                {"type": "text/html", "value": html_content}
            ]
        }).encode()

        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            print(f"[SendGrid] Email sent to {email}: {resp.status}")
            return resp.status in (200, 202)
    except Exception as e:
        print(f"[SendGrid] Error: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════

class SendOTPRequest(BaseModel):
    email: str = None
    phone: str = None

class VerifyOTPRequest(BaseModel):
    email: str = None
    phone: str = None
    code: str

@router.post("/send")
def send_otp(data: SendOTPRequest):
    """Send OTP to email or phone."""
    if not data.email and not data.phone:
        raise HTTPException(400, "Provide email or phone")

    code = generate_otp()
    results = {}

    if data.email:
        store_otp(data.email, code)
        ok = send_email_otp(data.email, code)
        results["email"] = "sent" if ok else "failed"

    if data.phone:
        store_otp(data.phone, code)
        ok = send_sms_otp(data.phone, code)
        results["sms"] = "sent" if ok else "failed"

    return {
        "success": True,
        "message": "Verification code sent",
        "results": results,
        "expires_in": "10 minutes"
    }

@router.post("/confirm")
def confirm_otp(data: VerifyOTPRequest):
    """Validate OTP code."""
    key = data.email or data.phone
    if not key:
        raise HTTPException(400, "Provide email or phone")

    valid = validate_otp(key, data.code)
    if not valid:
        raise HTTPException(400, "Invalid or expired code")

    return {
        "verified": True,
        "message": "Identity verified successfully",
        "key": key
    }

@router.get("/test")
def test_verification():
    """Test endpoint — sends a test OTP."""
    return {
        "status": "Verification system active",
        "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "sendgrid": bool(os.getenv("SENDGRID_API_KEY")),
        "mock_mode": not bool(os.getenv("TWILIO_ACCOUNT_SID"))
    }
