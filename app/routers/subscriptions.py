from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.database import get_db_connection

router = APIRouter(prefix="/api/v1/monetization/subscriptions", tags=["1B - Vybe Pro Pass"])

class SubscribeRequest(BaseModel):
    user_name: str
    plan_type: str = "monthly" # monthly / yearly

@router.get("/plans")
def get_plans():
    return {
        "plans": [
            {"id": "pro_monthly", "name": "Vybe Pro Monthly", "price": 99, "currency": "INR", "perks": ["Ad-Free Feed", "2x Quiz XP", "Blue Tick Badge"]},
            {"id": "pro_yearly", "name": "Vybe Pro Annual", "price": 999, "currency": "INR", "perks": ["Ad-Free Feed", "2x Quiz XP", "Priority Creator Uploads"]}
        ]
    }

@router.post("/upgrade")
def upgrade_subscription(payload: SubscribeRequest):
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO leaderboard (user_name, xp)
                VALUES (%s, 500)
                ON CONFLICT (user_name) DO UPDATE SET xp = leaderboard.xp + 500;
            """, (payload.user_name,))
            conn.commit()
        conn.close()
        return {"success": True, "message": f"Welcome {payload.user_name} to Vybe Pro! +500 XP Awarded."}
    raise HTTPException(status_code=500, detail="Database Error")
