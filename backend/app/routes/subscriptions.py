"""Subscription routes — SMS/push subscription for alerts."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.alerting import (
    subscribe_phone, subscribe_push, get_subscribers,
    remove_subscriber, is_twilio_configured, is_firebase_configured
)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class PhoneSubscribe(BaseModel):
    phone: str
    name: str = ""


class PushSubscribe(BaseModel):
    token: str
    name: str = ""


@router.post("/phone")
async def sub_phone(body: PhoneSubscribe):
    return subscribe_phone(body.phone, body.name)


@router.post("/push")
async def sub_push(body: PushSubscribe):
    return subscribe_push(body.token, body.name)


@router.get("/")
async def list_subs():
    return {
        "subscribers": get_subscribers(),
        "twilio_configured": is_twilio_configured(),
        "firebase_configured": is_firebase_configured(),
    }


@router.delete("/{sub_id}")
async def unsub(sub_id: int):
    remove_subscriber(sub_id)
    return {"ok": True}
