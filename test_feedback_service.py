import os
import unittest
from unittest.mock import MagicMock, patch

import mysql.connector

from feedback_service import DatabaseConnectionError, save_feedback


class FeedbackServiceTests(unittest.TestCase):
    @patch("feedback_service.mysql.connector.connect")
    def test_save_feedback_inserts_and_closes_resources(self, connect):
        db = MagicMock()
        cursor = db.cursor.return_value
        connect.return_value = db

        with patch.dict(
            os.environ,
            {
                "DATABASE_HOST": "mysql.internal",
                "DATABASE_USER": "app",
                "DATABASE_PASSWORD": "secret",
                "DATABASE_NAME": "railway",
            },
        ):
            save_feedback("chapter-hash", 5, "Useful extraction")

        cursor.execute.assert_called_once_with(
            "INSERT INTO feedback (chapter_hash, rating, comment) VALUES (%s, %s, %s)",
            ("chapter-hash", 5, "Useful extraction"),
        )
        db.commit.assert_called_once_with()
        cursor.close.assert_called_once_with()
        db.close.assert_called_once_with()

    @patch("feedback_service.mysql.connector.connect")
    def test_save_feedback_raises_clear_connection_error(self, connect):
        connect.side_effect = mysql.connector.Error("connection refused")

        with patch.dict(
            os.environ,
            {
                "DATABASE_HOST": "mysql.internal",
                "DATABASE_USER": "app",
                "DATABASE_PASSWORD": "secret",
                "DATABASE_NAME": "railway",
            },
        ):
            with self.assertRaisesRegex(
                DatabaseConnectionError,
                "Unable to connect to the feedback database: connection refused",
            ):
                save_feedback("chapter-hash", 5, "Useful extraction")

    @patch("feedback_service.mysql.connector.connect")
    def test_invalid_feedback_does_not_open_connection(self, connect):
        with self.assertRaisesRegex(
            ValueError, "Rating must be an integer between 0 and 5"
        ):
            save_feedback("chapter-hash", 6, "Invalid rating")

        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
