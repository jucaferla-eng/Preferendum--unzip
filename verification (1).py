import os
import random
import string
import json
import urllib.request
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/verify", tags=["verification"])

otp_store = {}


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


def store_otp(key, code, expires_minutes=10):
    otp_store[key] = {
        "code": code,
        "expires_at": (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat(),
        "attempts": 0,
    }


def validate_otp(key, code):
    if key not in otp_store:
        return False
    entry = otp_store[key]
    if datetime.utcnow() > datetime.fromisoformat(entry["expires_at"]):
        del otp_store[key]
        return False
    entry["attempts"] += 1
    if entry["attempts"] > 5:
        del otp_store[key]
        raise HTTPException(400, "Too many attempts")
    if entry["code"] == code:
        del otp_store[key]
        return True
    return False


def send_sms_otp(phone, code):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "+15075027781")
    if not account_sid or not auth_token:
        print(f"[Twilio MOCK] Code {code} to {phone}")
        return True
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=f"Your Preferendum code: {code}. Valid 10 min.",
            from_=from_number,
            to=phone
        )
        return True
    except Exception as e:
        print(f"[Twilio Error] {e}")
        return False


def send_email_otp(email, code):
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "noreply@preferendum.com")
    if not api_key:
        print(f"[SendGrid MOCK] Code {code} to {email}")
        return True
    try:
        data = json.dumps({
            "personalizations": [{"to": [{"email": email}]}],
            "from": {"email": from_email, "name": "Preferendum"},
            "subject": f"Your Preferendum code: {code}",
            "content": [{"type": "text/plain", "value": f"Your verification code is: {code}. Valid for 10 minutes."}]
        }).encode()
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status in (200, 202)
    except Exception as e:
        print(f"[SendGrid Error] {e}")
        return False


class SendOTPRequest(BaseModel):
    email: str = None
    phone: str = None


class VerifyOTPRequest(BaseModel):
    email: str = None
    phone: str = None
    code: str


@router.post("/send")
def send_otp(data: SendOTPRequest):
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
    return {"success": True, "message": "Code sent", "results": results}


@router.post("/confirm")
def confirm_otp(data: VerifyOTPRequest):
    key = data.email or data.phone
    if not key:
        raise HTTPException(400, "Provide email or phone")
    valid = validate_otp(key, data.code)
    if not valid:
        raise HTTPException(400, "Invalid or expired code")
    return {"verified": True, "message": "Identity verified"}


@router.get("/test")
def test_verification():
    return {
        "status": "Verification system active",
        "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "sendgrid": bool(os.getenv("SENDGRID_API_KEY")),
    }
