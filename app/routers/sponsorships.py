from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/b2b/sponsorships", tags=["2A - Brand Sponsored Challenges"])

@router.get("/active-campaigns")
def get_sponsored_campaigns():
    return {
        "success": True,
        "campaigns": [
            {
                "brand_name": "Google Cloud India",
                "hashtag": "#BuildWithAI",
                "banner_url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerBlazes.jpg",
                "reward_pool": "₹50,000 + Swag Kits",
                "action_url": "https://cloud.google.com"
            }
        ]
    }
