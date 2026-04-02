"""
Billing & Subscription Routes (Stripe)
"""

import asyncio
import uuid as uuid_module
from datetime import datetime, timezone
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator
from loguru import logger
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.core.config import settings

router = APIRouter()


@lru_cache(maxsize=1)
def _init_stripe():
    """Initialisiert Stripe einmalig und cached das Modul-Objekt."""
    if not settings.stripe_api_key:
        return None
    import stripe as _s
    _s.api_key = settings.stripe_api_key
    return _s


def get_stripe():
    s = _init_stripe()
    if s is None:
        raise HTTPException(status_code=503, detail="Stripe nicht konfiguriert")
    return s


@router.get("/subscription")
async def get_subscription(
    current_user: User = Depends(get_current_user),
):
    """Gibt aktuelles Abonnement zurück."""
    return {
        "tier": current_user.subscription_tier or "free",
        "expires_at": current_user.subscription_expires.isoformat()
        if current_user.subscription_expires
        else None,
        "stripe_customer_id": current_user.stripe_customer_id,
    }


class CreateCheckoutRequest(BaseModel):
    price_id: str
    success_url: str = "/settings?success=true"
    cancel_url: str = "/settings?canceled=true"

    @field_validator("price_id")
    @classmethod
    def validate_price_id(cls, v: str) -> str:
        allowed = {
            settings.stripe_price_pro_monthly,
            settings.stripe_price_pro_yearly,
        } - {""}
        if allowed and v not in allowed:
            raise ValueError("Ungültige Price-ID")
        return v

    @field_validator("success_url", "cancel_url")
    @classmethod
    def validate_relative_url(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("URL muss relativ sein (mit / beginnen)")
        return v


@router.post("/checkout")
async def create_checkout_session(
    body: CreateCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Erstellt Stripe Checkout Session."""
    stripe = get_stripe()

    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=current_user.email,
            metadata={"user_id": str(current_user.id)},
        )
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        await db.flush()

    try:
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": body.price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{settings.frontend_url}{body.success_url}",
            cancel_url=f"{settings.frontend_url}{body.cancel_url}",
            metadata={"user_id": str(current_user.id)},
        )
        return {"url": session.url}
    except Exception as e:
        logger.warning(f"Stripe checkout error | user={current_user.id} | error={e}")
        raise HTTPException(status_code=400, detail="Checkout konnte nicht erstellt werden")


@router.post("/portal")
async def create_customer_portal(
    current_user: User = Depends(get_current_user),
):
    """Öffnet Stripe Customer Portal."""
    stripe = get_stripe()

    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Kein Stripe-Kunde gefunden.")

    try:
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=current_user.stripe_customer_id,
            return_url=f"{settings.frontend_url}/einstellungen",
        )
        return {"url": session.url}
    except Exception as e:
        logger.warning(f"Stripe portal error | user={current_user.id} | error={e}")
        raise HTTPException(status_code=400, detail="Kundenportal konnte nicht geöffnet werden")


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Verarbeitet Stripe Webhooks."""
    stripe = get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = await asyncio.to_thread(
            stripe.Webhook.construct_event,
            payload, sig_header, settings.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    if event["type"] == "checkout.session.completed":
        # Nur das Tier setzen; subscription_expires kommt via customer.subscription.created/updated
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        if user_id:
            try:
                user_uuid = uuid_module.UUID(user_id)
            except (ValueError, AttributeError):
                return {"ok": True}
            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()
            if user:
                user.subscription_tier = "pro"
                await db.commit()

    elif event["type"] in ("customer.subscription.created", "customer.subscription.updated"):
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            sub_status = subscription.get("status")
            if sub_status in ("active", "trialing"):
                user.subscription_tier = "pro"
                period_end = subscription.get("current_period_end")
                if period_end:
                    user.subscription_expires = datetime.fromtimestamp(
                        period_end, tz=timezone.utc
                    )
            else:
                # past_due, canceled, unpaid, paused → Zugriff entziehen
                user.subscription_tier = "free"
                user.subscription_expires = None
            await db.commit()

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.subscription_tier = "free"
            user.subscription_expires = None
            await db.commit()

    return {"ok": True}
