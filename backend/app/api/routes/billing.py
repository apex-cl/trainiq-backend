"""
Billing & Subscription Routes (Stripe)
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.core.config import settings

router = APIRouter()


def get_stripe():
    """Gibt Stripe-Instanz zurück."""
    if not settings.stripe_api_key:
        raise HTTPException(status_code=503, detail="Stripe nicht konfiguriert")
    import stripe

    stripe.api_key = settings.stripe_api_key
    return stripe


@router.get("/subscription")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
        customer = stripe.Customer.create(
            email=current_user.email,
            metadata={"user_id": str(current_user.id)},
        )
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        await db.flush()

    try:
        session = stripe.checkout.Session.create(
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
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portal")
async def create_customer_portal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Öffnet Stripe Customer Portal."""
    stripe = get_stripe()

    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Kein Stripe-Kunde gefunden.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=f"{settings.frontend_url}/einstellungen",
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Verarbeitet Stripe Webhooks."""
    stripe = get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        if user_id:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.subscription_tier = "pro"
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

    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            status = subscription.get("status")
            if status == "active":
                user.subscription_tier = "pro"
            else:
                user.subscription_tier = "free"
            await db.commit()

    return {"ok": True}
