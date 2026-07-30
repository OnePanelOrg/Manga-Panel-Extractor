import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

import auth_service


class AuthServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def setUp(self):
        auth_service._jwks_client.cache_clear()
        self.environment = patch.dict(
            os.environ,
            {
                "CLERK_ISSUER": "https://clerk.example",
                "CLERK_AUTHORIZED_PARTIES": "http://localhost:3000",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        auth_service._jwks_client.cache_clear()

    def _token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "https://clerk.example",
            "sub": "user_123",
            "iat": now,
            "exp": now + 60,
            "azp": "http://localhost:3000",
            "sts": "active",
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    @patch("auth_service._jwks_client")
    def test_valid_session_returns_clerk_user_id(self, jwks_client):
        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = SimpleNamespace(
            key=self.private_key.public_key(),
        )
        jwks_client.return_value = client

        self.assertEqual(
            auth_service.verify_session_token(self._token()),
            "user_123",
        )

    @patch("auth_service._jwks_client")
    def test_rejects_wrong_authorized_party(self, jwks_client):
        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = SimpleNamespace(
            key=self.private_key.public_key(),
        )
        jwks_client.return_value = client

        with self.assertRaises(HTTPException) as raised:
            auth_service.verify_session_token(
                self._token(azp="https://attacker.example"),
            )
        self.assertEqual(raised.exception.status_code, 401)

    def test_requires_bearer_token(self):
        with self.assertRaises(HTTPException) as raised:
            auth_service.require_user(None)
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.detail["code"],
            auth_service.SIGN_IN_REQUIRED,
        )

    def test_optional_user_permits_missing_token(self):
        self.assertIsNone(auth_service.optional_user(None))

    @patch("auth_service.verify_session_token", return_value="user_123")
    def test_optional_user_validates_token_when_present(self, verify):
        self.assertEqual(
            auth_service.optional_user("Bearer session-token"),
            "user_123",
        )
        verify.assert_called_once_with("session-token")

    def test_optional_user_rejects_malformed_token(self):
        with self.assertRaises(HTTPException) as raised:
            auth_service.optional_user("Basic credentials")
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.detail["code"],
            auth_service.SIGN_IN_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
