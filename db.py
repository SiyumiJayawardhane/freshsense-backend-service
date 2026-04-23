import psycopg2
 
from config import DATABASE_URL
 
 
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required in .env")
    return psycopg2.connect(DATABASE_URL)