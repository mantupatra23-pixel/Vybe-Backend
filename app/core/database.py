import psycopg2
import redis
from psycopg2.extras import RealDictCursor
from app.core.config import settings

redis_client = None
if settings.REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as e:
        print(f"Redis Error: {e}")

def get_db_connection():
    if not settings.DATABASE_URL:
        return None
    return psycopg2.connect(settings.DATABASE_URL, cursor_factory=RealDictCursor)
