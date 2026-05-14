import os
import random
import string
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    gmail_user = os.getenv("GMAIL_USER", "jucaferla@gmail.com")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_password:
        print(f"[Gmail MOCK] Code {code} to {email}")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your Preferendum verification code: {code}"
        msg["From"] = f"Preferendum <{gmail_user}>"
        msg["To"] = email

        text = f"Your Preferendum verification code is: {code}\nValid for 10 minutes."
        html = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;background:#07090f;color:#fff;padding:40px;border-radius:12px;">
            <h1 style="color:#3b82f6;font-size:28px;">prefer<span style="color:#fff">endum</span></h1>
            <p>Your verification code is:</p>
            <div style="background:#1e2a3d;border-radius:8px;padding:24px;text-align:center;">
                <span style="font-size:36px;font-weight:bold;letter-spacing:8px;color:#3b82f6;">{code}</span>
            </div>
            <p style="color:#94a3b8;font-size:14px;">Valid for 10 minutes. Do not share this code.</p>
            <p style="color:#4a5568;font-size:12px;font-style:italic;">In memory of Jose Ignacio Fernandez (1989-2024)</p>
        </div>
        """

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, email, msg.as_string())

        print(f"[Gmail] Email sent to {email}")
        return True
    except Exception as e:
        print(f"[Gmail Error] {e}")
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
        "gmail": bool(os.getenv("GMAIL_APP_PASSWORD")),
        "sendgrid": bool(os.getenv("SENDGRID_API_KEY")),
    }
