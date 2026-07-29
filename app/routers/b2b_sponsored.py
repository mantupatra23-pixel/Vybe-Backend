from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/api/v1/monetization/b2b", tags=["B2B & Sponsored Revenue"])

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class SponsoredChallengeRequest(BaseModel):
    brand_name: str
    hashtag: str
    sponsor_banner_url: str
    campaign_budget: float

@router.post("/create-sponsored-challenge")
def create_sponsored_challenge(payload: SponsoredChallengeRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sponsored_challenges (
                        id SERIAL PRIMARY KEY,
                        brand_name TEXT NOT NULL,
                        hashtag TEXT UNIQUE NOT NULL,
                        sponsor_banner_url TEXT NOT NULL,
                        campaign_budget FLOAT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO sponsored_challenges (brand_name, hashtag, sponsor_banner_url, campaign_budget)
                    VALUES (%s, %s, %s, %s);
                """, (payload.brand_name, payload.hashtag, payload.sponsor_banner_url, payload.campaign_budget))
                conn.commit()
            conn.close()
            return {"success": True, "message": f"Sponsored Campaign #{payload.hashtag} is Live!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/active-sponsored-campaigns")
def get_active_campaigns():
    try:
        conn = get_db_connection()
        if not conn:
            return {"campaigns": []}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sponsored_challenges ORDER BY created_at DESC;")
            campaigns = cur.fetchall()
        conn.close()
        return {"success": True, "campaigns": campaigns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/affiliate-leads/{topic_tag}")
def get_affiliate_course_recommendations(topic_tag: str):
    affiliate_links = {
        "python": {"course": "Complete Python Masterclass", "link": "https://coursera.org/affiliate-python", "commission": "15%"},
        "ai": {"course": "Groq & Llama-3 AI Development", "link": "https://udemy.com/affiliate-ai", "commission": "20%"},
        "cloud": {"course": "DevOps & Cloud Architecture", "link": "https://cloud.engine/affiliate-devops", "commission": "25%"}
    }
    
    clean_tag = topic_tag.replace("#", "").lower()
    recommended = affiliate_links.get(clean_tag, {
        "course": "Explore Premium Tech Courses",
        "link": "https://vybe.ai/learn-pro",
        "commission": "10%"
    })
    
    return {"success": True, "recommendation": recommended}
