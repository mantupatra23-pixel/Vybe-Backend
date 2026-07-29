from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.database import get_db_connection

router = APIRouter(prefix="/api/v1/monetization/tips", tags=["1C - Micro-transaction Tipping"])

class TipRequest(BaseModel):
    creator_name: str
    tipper_name: str
    gross_amount: float

@router.post("/process")
def process_tip_split(payload: TipRequest):
    platform_cut = payload.gross_amount * 0.15  # 15% Founder Revenue
    creator_net = payload.gross_amount * 0.85    # 85% Creator Earnings
    
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tips (creator_name, tipper_name, amount) VALUES (%s, %s, %s);",
                (payload.creator_name, payload.tipper_name, creator_net)
            )
            cur.execute("""
                INSERT INTO creator_wallets (creator_name, total_earnings)
                VALUES (%s, %s)
                ON CONFLICT (creator_name)
                DO UPDATE SET total_earnings = creator_wallets.total_earnings + EXCLUDED.total_earnings;
            """, (payload.creator_name, creator_net))
            conn.commit()
        conn.close()
        return {
            "success": True,
            "gross_amount": payload.gross_amount,
            "creator_net_credited": creator_net,
            "platform_commission_fee": platform_cut
        }
    raise HTTPException(status_code=500, detail="Transaction Failed")
