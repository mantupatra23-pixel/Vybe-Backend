from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/monetization/ads", tags=["1A - In-Feed Ads Engine"])

class AdUnitConfig(BaseModel):
    admob_app_id: str
    banner_unit_id: str
    interstitial_unit_id: str

@router.get("/config")
def get_ad_config():
    return {
        "success": True,
        "ad_frequency_interval": 4, # Render native ad every 4 video scrolls
        "admob": {
            "app_id": "ca-app-pub-3940256099942544~3347511713",
            "banner_unit_id": "ca-app-pub-3940256099942544/6300978111"
        }
    }
