from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/b2b/affiliate", tags=["2B - AI Course & Lead Gen"])

@router.get("/recommendations/{topic}")
def get_course_leads(topic: str):
    return {
        "topic": topic,
        "affiliate_cards": [
            {
                "title": f"Mastering {topic.title()} - Zero to Hero",
                "provider": "Udemy Pro",
                "price": "₹499",
                "affiliate_url": f"https://www.udemy.com/course/sample/?ref=vybe_platform",
                "commission_rate": "20%"
            }
        ]
    }
