
import os
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = quote_plus(os.getenv("DB_PASSWORD", ""))
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "marketplace_seller_pipeline")

if not DB_USER or not DB_PASSWORD:
    raise ValueError("Database credentials are missing. Check your .env file.")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False
)


def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT DATABASE()"))
            print("Connected to database:", result.scalar())
    except Exception as error:
        print("Database connection failed:", error)


if __name__ == "__main__":
    test_connection()
