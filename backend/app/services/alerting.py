"""Alerting Service — Twilio SMS/WhatsApp + Firebase Cloud Messaging.

Configure via backend/.env:
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
  FIREBASE_CREDENTIALS_PATH (path to service account JSON)
"""
import json
import httpx
from datetime import datetime
from typing import Optional
from app.config import settings


# ── Configuration helpers ────────────────────────────────────────────────────
def is_twilio_configured():
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_from_number
    )


def is_firebase_configured():
    return bool(settings.firebase_credentials_path)


# In-memory subscriber list (in production, store in DB)
_subscribers = []


# ── SMS via Twilio ──────────────────────────────────────────────────────────
async def send_sms(to_number: str, message: str) -> dict:
    """Send SMS via Twilio."""
    if not is_twilio_configured():
        return {
            "status": "simulated",
            "channel": "sms",
            "to": to_number,
            "message": message,
            "note": "Twilio not configured — set TWILIO_ACCOUNT_SID in .env"
        }

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
        auth = (settings.twilio_account_sid, settings.twilio_auth_token)
        data = {
            "From": settings.twilio_from_number,
            "To": to_number,
            "Body": message,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, auth=auth, data=data, timeout=10)
            result = resp.json()

        return {
            "status": "sent" if resp.status_code < 300 else "failed",
            "channel": "sms",
            "to": to_number,
            "sid": result.get("sid"),
            "error": result.get("message") if resp.status_code >= 300 else None,
        }
    except Exception as e:
        return {"status": "error", "channel": "sms", "to": to_number, "error": str(e)}


# ── WhatsApp via Twilio ─────────────────────────────────────────────────────
async def send_whatsapp(to_number: str, message: str) -> dict:
    """Send WhatsApp message via Twilio."""
    if not is_twilio_configured():
        return {
            "status": "simulated",
            "channel": "whatsapp",
            "to": to_number,
            "message": message,
            "note": "Twilio not configured — set TWILIO_ACCOUNT_SID in .env"
        }

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
        auth = (settings.twilio_account_sid, settings.twilio_auth_token)
        from_num = f"whatsapp:{settings.twilio_from_number}"
        to_num = f"whatsapp:{to_number}"
        data = {
            "From": from_num,
            "To": to_num,
            "Body": message,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, auth=auth, data=data, timeout=10)
            result = resp.json()

        return {
            "status": "sent" if resp.status_code < 300 else "failed",
            "channel": "whatsapp",
            "to": to_number,
            "sid": result.get("sid"),
            "error": result.get("message") if resp.status_code >= 300 else None,
        }
    except Exception as e:
        return {"status": "error", "channel": "whatsapp", "to": to_number, "error": str(e)}


# ── Push Notification via Firebase Cloud Messaging ───────────────────────────
async def send_push(tokens: list, title: str, body: str, data: dict = None) -> dict:
    """Send push notification via FCM."""
    if not is_firebase_configured():
        return {
            "status": "simulated",
            "channel": "push",
            "token_count": len(tokens),
            "title": title,
            "body": body,
            "note": "Firebase not configured — set FIREBASE_CREDENTIALS_PATH in .env"
        }

    try:
        access_token = await _get_fcm_token()
        if not access_token:
            return {"status": "error", "channel": "push", "error": "Failed to get FCM token"}

        fcm_url = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_sender_id}/messages:send"

        results = []
        for token in tokens:
            payload = {
                "message": {
                    "token": token,
                    "notification": {
                        "title": title,
                        "body": body,
                    },
                    "data": data or {},
                    "android": {
                        "priority": "high",
                        "notification": {
                            "channel_id": "riis_alerts",
                            "priority": "high",
                        }
                    }
                }
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    fcm_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                results.append(resp.json())

        return {
            "status": "sent",
            "channel": "push",
            "token_count": len(tokens),
            "results": results,
        }
    except Exception as e:
        return {"status": "error", "channel": "push", "error": str(e)}


async def _get_fcm_token():
    """Get Firebase access token from service account."""
    try:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            settings.firebase_credentials_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception as e:
        print(f"[RIIS-Alerting] FCM token error: {e}")
        return None


# ── Subscriber Management ───────────────────────────────────────────────────
def add_subscriber(phone: str = None, token: str = None, name: str = ""):
    """Add a subscriber for push/SMS alerts."""
    sub = {
        "id": len(_subscribers) + 1,
        "phone": phone,
        "push_token": token,
        "name": name,
        "created_at": datetime.utcnow().isoformat(),
    }
    _subscribers.append(sub)
    return sub


def get_subscribers():
    return _subscribers


def remove_subscriber(sub_id: int):
    global _subscribers
    _subscribers = [s for s in _subscribers if s["id"] != sub_id]


# ── Broadcast Alert ─────────────────────────────────────────────────────────
async def broadcast_alert(
    severity: str,
    title: str,
    body: str,
    area: str = "General",
    channels: list = None,
) -> dict:
    """Broadcast an alert to all subscribers via specified channels."""
    channels = channels or ["web"]
    results = {}
    message = f"RIIS Alert [{severity.upper()}] — {area}\n\n{title}\n\n{body}"

    for channel in channels:
        if channel == "sms":
            phone_subs = [s for s in _subscribers if s.get("phone")]
            sms_results = []
            for sub in phone_subs:
                r = await send_sms(sub["phone"], message)
                sms_results.append(r)
            results["sms"] = {
                "sent": len(phone_subs),
                "results": sms_results,
            }

        elif channel == "whatsapp":
            phone_subs = [s for s in _subscribers if s.get("phone")]
            wa_results = []
            for sub in phone_subs:
                r = await send_whatsapp(sub["phone"], message)
                wa_results.append(r)
            results["whatsapp"] = {
                "sent": len(phone_subs),
                "results": wa_results,
            }

        elif channel == "push":
            token_subs = [s for s in _subscribers if s.get("push_token")]
            tokens = [s["push_token"] for s in token_subs]
            r = await send_push(tokens, f"Alert: {title}", body, {"severity": severity, "area": area})
            results["push"] = {
                "sent": len(tokens),
                "result": r,
            }

        elif channel == "web":
            results["web"] = {"status": "delivered", "note": "Web alerts displayed in UI"}

    return {
        "severity": severity,
        "title": title,
        "area": area,
        "channels": channels,
        "results": results,
        "broadcast_at": datetime.utcnow().isoformat(),
    }


# ── Subscription Endpoints ──────────────────────────────────────────────────
def subscribe_phone(phone: str, name: str = "") -> dict:
    for s in _subscribers:
        if s.get("phone") == phone:
            return {"ok": True, "subscriber": s, "message": "Already subscribed"}
    sub = add_subscriber(phone=phone, name=name)
    return {"ok": True, "subscriber": sub}


def subscribe_push(token: str, name: str = "") -> dict:
    for s in _subscribers:
        if s.get("push_token") == token:
            return {"ok": True, "subscriber": s, "message": "Already subscribed"}
    sub = add_subscriber(token=token, name=name)
    return {"ok": True, "subscriber": sub}
