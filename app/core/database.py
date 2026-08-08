import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

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

try:
    connection = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        port=os.getenv("POSTGRES_PORT", "5432")
    )

    cur = connection.cursor()
    cur.execute(CREATE_TABLE_SQL)
    connection.commit()

    print("Database connection successful!")
    cur.close()
    connection.close()
 
except Exception as e:
    print(f"Database connection failed: {e}")