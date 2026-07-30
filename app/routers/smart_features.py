from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import json
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/api/v1/smart", tags=["Smart Features Engine"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class ScriptRequest(BaseModel):
    topic: str

class PollVoteRequest(BaseModel):
    video_id: int
    option_index: int
    user_name: str

class CaptionRequest(BaseModel):
    video_title: str

# 1. Creator AI Script Assistant (Groq Copilot)
@router.post("/generate-script")
def generate_ai_script(payload: ScriptRequest):
    if not GROQ_API_KEY:
        return {
            "success": True,
            "script": f"Hook: Did you know this about {payload.topic}?\nBody: Here are 2 key things you must know...\nCTA: Follow for more micro lessons!",
            "tags": f"#{payload.topic.replace(' ', '')} #learning #tech"
        }

    prompt = f"""
    You are a viral short-video script writer. Write a 30-second script for a video about "{payload.topic}".
    Respond ONLY in valid JSON format with keys "hook", "body", "cta", and "tags" (space separated hashtags).
    """

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        res = httpx.post(url, headers=headers, json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }, timeout=15.0)

        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)
            return {"success": True, "script_data": data}
    except Exception as e:
        print(f"Groq Script Error: {e}")

    return {
        "success": True,
        "script_data": {
            "hook": f"Here is what you need to know about {payload.topic}!",
            "body": "Keep learning every day with quick 30-second micro lessons.",
            "cta": "Tap follow and test your knowledge in the quiz below!",
            "tags": f"#{payload.topic.replace(' ', '')} #ai #tech"
        }
    }

# 2. AI Auto-Subtitles / Smart Captions
@router.post("/auto-subtitles")
def generate_auto_subtitles(payload: CaptionRequest):
    words = payload.video_title.split()
    subtitles = []
    start_time = 0.0

    for i, word in enumerate(words):
        end_time = round(start_time + 0.4, 2)
        subtitles.append({
            "id": i + 1,
            "word": word,
            "start": start_time,
            "end": end_time
        })
        start_time = end_time

    return {"success": True, "subtitles": subtitles}

# 3. Live Interactive Polls & Voting System
@router.post("/poll/vote")
def vote_on_poll(payload: PollVoteRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS poll_votes (
                        id SERIAL PRIMARY KEY,
                        video_id INT NOT NULL,
                        option_index INT NOT NULL,
                        user_name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("INSERT INTO poll_votes (video_id, option_index, user_name) VALUES (%s, %s, %s);",
                            (payload.video_id, payload.option_index, payload.user_name))
                conn.commit()

                # Calculate Percentage Breakdown
                cur.execute("SELECT option_index, COUNT(*) as count FROM poll_votes WHERE video_id = %s GROUP BY option_index;", (payload.video_id,))
                rows = cur.fetchall()
                total_votes = sum(r["count"] for r in rows)
                stats = {r["option_index"]: round((r["count"] / total_votes) * 100, 1) for r in rows}

            conn.close()
            return {"success": True, "total_votes": total_votes, "percentages": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
