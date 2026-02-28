"""Stripe billing: checkout, portal, webhooks.

Adapted from mysecond.app server.py:720-877.
"""
from __future__ import annotations

from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.db.models import Subscription, User
from app.db.session import get_db

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _init_stripe() -> None:
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    _init_stripe()

    # Retrieve or create Stripe customer
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    customer_id = sub.stripe_customer_id if sub else None

    if not customer_id:
        customer = stripe.Customer.create(
            metadata={"user_id": str(user.id), "email": user.email},
        )
        customer_id = customer.id
        # Persist immediately so webhooks can map customer → user
        stmt = pg_insert(Subscription).values(
            user_id=user.id,
            stripe_customer_id=customer_id,
            plan="free",
            status="pending",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"stripe_customer_id": customer_id},
        )
        await db.execute(stmt)
        await db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        client_reference_id=str(user.id),
        payment_method_types=["card"],
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.app_url}/account?stripe=success",
        cancel_url=f"{settings.app_url}/account",
    )
    return {"url": session.url}


# ---------------------------------------------------------------------------
# Portal
# ---------------------------------------------------------------------------


@router.post("/create-portal-session")
async def create_portal_session(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    _init_stripe()

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No billing record found")

    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{settings.app_url}/account",
    )
    return {"url": portal.url}


# ---------------------------------------------------------------------------
# Webhook (no auth — called by Stripe servers)
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    _init_stripe()

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    await _handle_stripe_event(event, db)
    return {"received": True}


async def _handle_stripe_event(event: dict, db: AsyncSession) -> None:
    """Handle Stripe webhook events. Mirrors chess app _handle_stripe_event."""
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id_str = obj.get("client_reference_id")
        customer_id = obj.get("customer")
        sub_id = obj.get("subscription")
        if user_id_str and customer_id:
            await _upsert_subscription(
                db,
                user_id_str=user_id_str,
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                plan="pro",
                status="active",
                current_period_end=None,
            )

    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        sub = obj
        customer_id = sub["customer"]
        sub_id = sub["id"]
        status = sub["status"]
        plan = "pro" if (
            status in ("active", "trialing")
            and etype != "customer.subscription.deleted"
        ) else "free"
        period_ts = sub.get("current_period_end")
        period_end = (
            datetime.fromtimestamp(period_ts, tz=timezone.utc) if period_ts else None
        )

        # Look up user by customer ID
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            await _upsert_subscription(
                db,
                user_id_str=str(existing.user_id),
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                plan=plan,
                status=status,
                current_period_end=period_end,
            )

    elif etype == "invoice.payment_failed":
        customer_id = obj["customer"]
        sub_id = obj.get("subscription")
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            await _upsert_subscription(
                db,
                user_id_str=str(existing.user_id),
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                plan="free",
                status="past_due",
                current_period_end=None,
            )


async def _upsert_subscription(
    db: AsyncSession,
    *,
    user_id_str: str,
    stripe_customer_id: str,
    stripe_subscription_id: str | None,
    plan: str,
    status: str,
    current_period_end: datetime | None,
) -> None:
    import uuid
    user_id = uuid.UUID(user_id_str)

    stmt = pg_insert(Subscription).values(
        user_id=user_id,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        plan=plan,
        status=status,
        current_period_end=current_period_end,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stmt.excluded.stripe_subscription_id,
            "plan": plan,
            "status": status,
            "current_period_end": stmt.excluded.current_period_end,
            "updated_at": datetime.now(tz=timezone.utc),
        },
    )
    await db.execute(stmt)

    # Also update denormalized plan on user
    from app.db.models import User as UserModel
    from sqlalchemy import update
    await db.execute(
        update(UserModel).where(UserModel.id == user_id).values(plan=plan)
    )
    await db.commit()
