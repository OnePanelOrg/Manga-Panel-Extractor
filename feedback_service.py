from dotenv import load_dotenv
import os
import mysql.connector

load_dotenv()


class DatabaseConnectionError(RuntimeError):
    """Raised when the feedback database cannot be reached."""


def connect_to_database():
    try:
        return mysql.connector.connect(
            host=os.environ['DATABASE_HOST'],
            user=os.environ['DATABASE_USER'],
            password=os.environ['DATABASE_PASSWORD'],
            database=os.environ['DATABASE_NAME']
        )
    except mysql.connector.Error as err:
        raise DatabaseConnectionError(
            f"Unable to connect to the feedback database: {err}"
        ) from err


def save_feedback(chapter_hash, rating, comment):
    # Ensure rating is an integer and within 0-5
    if not isinstance(rating, int) or rating < 0 or rating > 5:
        raise ValueError("Rating must be an integer between 0 and 5")

    # Ensure comment is a string
    if not isinstance(comment, str):
        raise ValueError("Comment must be a string")

    db = connect_to_database()
    cursor = db.cursor()

    query = "INSERT INTO feedback (chapter_hash, rating, comment) VALUES (%s, %s, %s)"
    values = (chapter_hash, rating, comment)

    cursor.execute(query, values)
    db.commit()

    cursor.close()
    db.close()
