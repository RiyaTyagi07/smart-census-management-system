import sqlite3
from pathlib import Path


# ---------------------------------------------------------
# DATABASE PATH
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "census.db"


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)

    # Rows ko dictionary-like access dene ke liye
    connection.row_factory = sqlite3.Row

    # Foreign key support
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ---------------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------------

def initialize_database():

    connection = get_connection()

    # -----------------------------------------------------
    # USERS TABLE
    # -----------------------------------------------------

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # CENSUS RECORDS TABLE
    # -----------------------------------------------------

    connection.execute("""
        CREATE TABLE IF NOT EXISTS census_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            occupation TEXT NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    connection.commit()
    connection.close()


# ---------------------------------------------------------
# RUN DIRECTLY
# ---------------------------------------------------------

if __name__ == "__main__":

    initialize_database()

    print("Database initialized successfully.")
    print(f"Database location: {DATABASE_PATH}")