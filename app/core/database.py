import psycopg2
import os
import logging
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    result_summary JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS invalid_rows_s3_key VARCHAR(255);

"""

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        port=os.getenv("POSTGRES_PORT", "5432")
    )

@contextmanager
def get_db_cursor():

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()


def init_db():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        connection.commit()
        cursor.close()
        connection.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise e