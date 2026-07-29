from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/api/v1/monetization/founder", tags=["Founder Monetization"])

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class SubscriptionRequest(BaseModel):
    user_name: str
    plan_type: str

@router.get("/ad-config")
def get_platform_ad_config():
    return {
        "success": True,
        "ad_frequency": 4,
        "admob_app_id": "ca-app-pub-3940256099942544~3347511713",
        "native_ad_unit_id": "ca-app-pub-3940256099942544/2247696110"
    }

@router.post("/subscribe-pro")
def subscribe_vybe_pro(payload: SubscriptionRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id SERIAL PRIMARY KEY,
                        user_name TEXT UNIQUE NOT NULL,
                        plan_type TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO subscriptions (user_name, plan_type, is_active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (user_name)
                    DO UPDATE SET plan_type = EXCLUDED.plan_type, is_active = TRUE;
                """, (payload.user_name, payload.plan_type))
                conn.commit()
            conn.close()
            return {"success": True, "message": f"Successfully upgraded {payload.user_name} to Vybe Pro Pass! 💎"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/calculate-tip-split")
def calculate_tip_split(gross_amount: float):
    founder_commission = round(gross_amount * 0.20, 2)
    creator_payout = round(gross_amount * 0.80, 2)
    return {
        "gross_amount": gross_amount,
        "founder_commission_20_percent": founder_commission,
        "creator_payout_80_percent": creator_payout
    }
