import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import quote

import requests
import stripe
from fastapi import HTTPException


ACTIVE_SUBSCRIPTION_STATUSES = {"active"}
COMPLIMENTARY_SUBSCRIPTION_STATUS = "complimentary"
COMPLIMENTARY_PRO_EMAILS = frozenset({"vincenzocassaro1@gmail.com"})
SUBSCRIPTION_REQUIRED = "subscription_required"
CLERK_API_URL = "https://api.clerk.com/v1"
CLERK_REQUEST_TIMEOUT = 5


@dataclass(frozen=True)
class SubscriptionState:
    active: bool
    status: Optional[str]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _configure_stripe() -> None:
    stripe.api_key = _required_env("STRIPE_SECRET_KEY")


def _stripe_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail="Stripe billing is temporarily unavailable. Please try again.",
    )


@lru_cache(maxsize=1024)
def _get_clerk_user(clerk_user_id: str) -> dict:
    response = requests.get(
        f"{CLERK_API_URL}/users/{quote(clerk_user_id, safe='')}",
        headers={"Authorization": f"Bearer {_required_env('CLERK_SECRET_KEY')}"},
        timeout=CLERK_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def has_complimentary_access(clerk_user_id: str) -> bool:
    if not COMPLIMENTARY_PRO_EMAILS or not os.environ.get("CLERK_SECRET_KEY", "").strip():
        return False

    try:
        user = _get_clerk_user(clerk_user_id)
    except (requests.RequestException, RuntimeError, ValueError):
        return False

    primary_email_id = user.get("primary_email_address_id")
    primary_email = next(
        (
            email
            for email in user.get("email_addresses", [])
            if email.get("id") == primary_email_id
        ),
        None,
    )
    if not primary_email:
        return False

    verification = primary_email.get("verification") or {}
    email_address = str(primary_email.get("email_address", "")).strip().casefold()
    return (
        verification.get("status") == "verified"
        and email_address in COMPLIMENTARY_PRO_EMAILS
    )


def _customer_query(clerk_user_id: str) -> str:
    escaped = clerk_user_id.replace("\\", "\\\\").replace("'", "\\'")
    return f"metadata['clerk_user_id']:'{escaped}'"


def find_customer(clerk_user_id: str):
    _configure_stripe()
    try:
        customers = stripe.Customer.search(
            query=_customer_query(clerk_user_id),
            limit=1,
        )
    except stripe.StripeError as error:
        raise _stripe_error(error) from error
    return customers.data[0] if customers.data else None


def get_or_create_customer(clerk_user_id: str):
    customer = find_customer(clerk_user_id)
    if customer:
        return customer

    try:
        return stripe.Customer.create(
            metadata={"clerk_user_id": clerk_user_id},
            idempotency_key=f"onepanel-customer-{clerk_user_id}",
        )
    except stripe.StripeError as error:
        raise _stripe_error(error) from error


def get_subscription_state(clerk_user_id: str) -> SubscriptionState:
    if has_complimentary_access(clerk_user_id):
        return SubscriptionState(
            active=True,
            status=COMPLIMENTARY_SUBSCRIPTION_STATUS,
        )

    customer = find_customer(clerk_user_id)
    if not customer:
        return SubscriptionState(active=False, status=None)

    try:
        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=100,
        )
    except stripe.StripeError as error:
        raise _stripe_error(error) from error

    statuses = [subscription.status for subscription in subscriptions.auto_paging_iter()]
    active_status = next(
        (status for status in statuses if status in ACTIVE_SUBSCRIPTION_STATUSES),
        None,
    )
    return SubscriptionState(
        active=active_status is not None,
        status=active_status or (statuses[0] if statuses else None),
    )


def require_active_subscription(clerk_user_id: str) -> None:
    if not get_subscription_state(clerk_user_id).active:
        raise HTTPException(
            status_code=402,
            detail={
                "code": SUBSCRIPTION_REQUIRED,
                "message": "An active OnePanel Pro subscription is required.",
            },
        )


def _validated_price_id() -> str:
    _configure_stripe()
    price_id = _required_env("STRIPE_PRICE_ID")
    try:
        price = stripe.Price.retrieve(price_id)
    except stripe.StripeError as error:
        raise _stripe_error(error) from error

    recurring = getattr(price, "recurring", None)
    valid = (
        price.active
        and price.currency == "eur"
        and price.unit_amount == 499
        and price.type == "recurring"
        and recurring
        and recurring.interval == "month"
        and recurring.interval_count == 1
    )
    if not valid:
        raise HTTPException(
            status_code=503,
            detail=(
                "The Stripe price is misconfigured. Expected an active "
                "€4.99 EUR monthly recurring price."
            ),
        )
    return price_id


def create_checkout_url(clerk_user_id: str) -> str:
    if get_subscription_state(clerk_user_id).active:
        raise HTTPException(
            status_code=409,
            detail="You already have an active subscription.",
        )

    customer = get_or_create_customer(clerk_user_id)
    frontend_url = _required_env("FRONTEND_URL").rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            customer=customer.id,
            client_reference_id=clerk_user_id,
            mode="subscription",
            line_items=[{"price": _validated_price_id(), "quantity": 1}],
            metadata={"clerk_user_id": clerk_user_id},
            subscription_data={"metadata": {"clerk_user_id": clerk_user_id}},
            success_url=f"{frontend_url}/?checkout=success",
            cancel_url=f"{frontend_url}/?checkout=cancelled",
        )
    except stripe.StripeError as error:
        raise _stripe_error(error) from error
    if not session.url:
        raise HTTPException(status_code=502, detail="Stripe returned no checkout URL.")
    return session.url


def create_portal_url(clerk_user_id: str) -> str:
    customer = find_customer(clerk_user_id)
    if not customer:
        raise HTTPException(status_code=404, detail="No billing account was found.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer.id,
            return_url=_required_env("FRONTEND_URL").rstrip("/"),
        )
    except stripe.StripeError as error:
        raise _stripe_error(error) from error
    return session.url
