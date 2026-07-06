import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import billing_service


class BillingServiceTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "STRIPE_SECRET_KEY": "sk_test_example",
                "STRIPE_PRICE_ID": "price_monthly",
                "FRONTEND_URL": "http://localhost:3000",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    @patch("billing_service.stripe.Price.retrieve")
    def test_accepts_exact_monthly_price(self, retrieve):
        retrieve.return_value = SimpleNamespace(
            active=True,
            currency="eur",
            unit_amount=499,
            type="recurring",
            recurring=SimpleNamespace(interval="month", interval_count=1),
        )

        self.assertEqual(billing_service._validated_price_id(), "price_monthly")

    @patch("billing_service.stripe.Price.retrieve")
    def test_rejects_wrong_price_amount(self, retrieve):
        retrieve.return_value = SimpleNamespace(
            active=True,
            currency="eur",
            unit_amount=999,
            type="recurring",
            recurring=SimpleNamespace(interval="month", interval_count=1),
        )

        with self.assertRaises(HTTPException) as raised:
            billing_service._validated_price_id()
        self.assertEqual(raised.exception.status_code, 503)

    @patch("billing_service._validated_price_id", return_value="price_monthly")
    @patch("billing_service.get_or_create_customer")
    @patch("billing_service.get_subscription_state")
    @patch("billing_service.stripe.checkout.Session.create")
    def test_checkout_has_no_trial(
        self,
        create_session,
        subscription_state,
        get_customer,
        _price,
    ):
        subscription_state.return_value = billing_service.SubscriptionState(
            active=False,
            status=None,
        )
        get_customer.return_value = SimpleNamespace(id="cus_123")
        create_session.return_value = SimpleNamespace(
            url="https://checkout.stripe.com/test",
        )

        url = billing_service.create_checkout_url("user_123")

        self.assertEqual(url, "https://checkout.stripe.com/test")
        arguments = create_session.call_args.kwargs
        self.assertEqual(arguments["mode"], "subscription")
        self.assertNotIn("trial_period_days", arguments["subscription_data"])
        self.assertEqual(arguments["line_items"][0]["price"], "price_monthly")

    @patch("billing_service.find_customer")
    def test_no_customer_is_not_subscribed(self, find_customer):
        find_customer.return_value = None

        state = billing_service.get_subscription_state("user_123")

        self.assertFalse(state.active)
        self.assertIsNone(state.status)

    @patch("billing_service.find_customer")
    @patch("billing_service.stripe.Subscription.list")
    def test_active_subscription_grants_access(self, list_subscriptions, find_customer):
        find_customer.return_value = SimpleNamespace(id="cus_123")
        result = MagicMock()
        result.auto_paging_iter.return_value = iter(
            [SimpleNamespace(status="active")],
        )
        list_subscriptions.return_value = result

        state = billing_service.get_subscription_state("user_123")

        self.assertTrue(state.active)
        self.assertEqual(state.status, "active")


if __name__ == "__main__":
    unittest.main()
