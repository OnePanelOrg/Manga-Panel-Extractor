from dotenv import load_dotenv
import os
import mysql.connector

load_dotenv()

def connect_to_database():
    try:
        db = mysql.connector.connect(
            host=os.environ['DATABASE_HOST'],
            user=os.environ['DATABASE_USER'],
            password=os.environ['DATABASE_PASSWORD'],
            database=os.environ['DATABASE_NAME']
        )
        return db
    except mysql.connector.Error as err:
        if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
            print("Database does not exist")
        else:
            print(err)
        return None

def save_feedback(chapter_hash, rating, comment):
    db = connect_to_database()
    cursor = db.cursor()

    # Ensure rating is an integer and within 0-5
    if not isinstance(rating, int) or rating < 0 or rating > 5:
        raise ValueError("Rating must be an integer between 0 and 5")

    # Ensure comment is a string
    if not isinstance(comment, str):
        raise ValueError("Comment must be a string")

    query = "INSERT INTO feedback (chapter_hash, rating, comment) VALUES (%s, %s, %s)"
    values = (chapter_hash, rating, comment)

    cursor.execute(query, values)
    db.commit()

    print(f"Feedback saved | {chapter_hash} :: {rating}, {comment}")

    cursor.close()
    db.close()
