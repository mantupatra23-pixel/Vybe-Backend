import os
import boto3
import json
import psycopg2
import httpx
import tempfile
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from gtts import gTTS

load_dotenv()

app = FastAPI(title="Vybe Autonomous AI & Gamification Engine", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credentials
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "vybe-videos")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

s3_client = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

class ScoreUpdate(BaseModel):
    user_name: str
    xp_gained: int

@app.on_event("startup")
def setup_tables():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    tags TEXT,
                    cdn_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS quizzes (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    options JSONB NOT NULL,
                    correct_index INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leaderboard (
                    id SERIAL PRIMARY KEY,
                    user_name TEXT UNIQUE NOT NULL,
                    xp INT DEFAULT 0,
                    quizzes_solved INT DEFAULT 0
                );
            """)
            conn.commit()
        conn.close()

def generate_ai_quiz_groq(title: str, tags: str):
    if not GROQ_API_KEY:
        return [{
            "question": f"What is the main topic of '{title}'?",
            "options": [title, "General Tech Concept", "Trivia", "Overview"],
            "correct_index": 0
        }]

    prompt = f"""
    Generate exactly 2 multiple-choice questions based on: "{title}" with tags "{tags}".
    Respond ONLY in raw JSON array format without markdown syntax:
    [
        {{
            "question": "Sample Question?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_index": 0
        }}
    ]
    """
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5
        }
        res = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
    except Exception as e:
        print(f"Groq API Error: {e}")

    return [{
        "question": f"What is explained in '{title}'?",
        "options": [title, "Basic Intro", "Advanced Concept", "Overview"],
        "correct_index": 0
    }]

# Autonomous Video Creator Logic
def generate_auto_video_job(topic: str):
    try:
        file_name = f"auto_{int(os.getpid())}_{topic.replace(' ', '_')}.mp3"
        object_key = f"videos/{file_name}"

        # 1. Generate Voiceover using gTTS
        tts = gTTS(text=f"Welcome to today's micro lesson on {topic}. AI technology is evolving rapidly. Stay tuned for quick quizzes!", lang='en')
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tts.save(tmp.name)
            
            # 2. Direct Upload Audio/Video stream to R2
            s3_client.upload_file(tmp.name, R2_BUCKET_NAME, object_key, ExtraArgs={"ContentType": "audio/mpeg"})
            os.remove(tmp.name)

        public_cdn_url = f"{R2_PUBLIC_DOMAIN.rstrip('/')}/{object_key}"

        # 3. Insert into Database & Generate AI Quiz
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO videos (title, tags, cdn_url) VALUES (%s, %s, %s) RETURNING id;",
                    (f"AI Lesson: {topic.title()}", "#auto #ai #learning", public_cdn_url)
                )
                video_id = cur.fetchone()["id"]
                quiz_items = generate_ai_quiz_groq(topic, "#auto #ai")
                for item in quiz_items:
                    cur.execute(
                        "INSERT INTO quizzes (video_id, question, options, correct_index) VALUES (%s, %s, %s, %s);",
                        (video_id, item["question"], json.dumps(item["options"]), item.get("correct_index", 0))
                    )
                conn.commit()
            conn.close()
    except Exception as e:
        print(f"Auto-video generation error: {e}")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Vybe AI Generator & Gamification Engine Active!"}

@app.post("/api/v1/admin/trigger-auto-video")
def trigger_auto_video(topic: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(generate_auto_video_job, topic)
    return {"success": True, "message": f"Autonomous video generation started for '{topic}'"}

@app.get("/api/v1/videos/feed")
def get_video_feed():
    try:
        conn = get_db_connection()
        if not conn:
            return {"videos": []}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM videos ORDER BY created_at DESC;")
            videos = cur.fetchall()
        conn.close()
        return {"success": True, "videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/quizzes/{video_id}")
def get_quizzes_for_video(video_id: int):
    try:
        conn = get_db_connection()
        if not conn:
            return {"quizzes": []}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quizzes WHERE video_id = %s;", (video_id,))
            quizzes = cur.fetchall()
        conn.close()
        return {"success": True, "quizzes": quizzes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Leaderboard & XP APIs
@app.post("/api/v1/user/score")
def update_user_score(payload: ScoreUpdate):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO leaderboard (user_name, xp, quizzes_solved)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (user_name)
                    DO UPDATE SET xp = leaderboard.xp + %s, quizzes_solved = leaderboard.quizzes_solved + 1;
                """, (payload.user_name, payload.xp_gained, payload.xp_gained))
                conn.commit()
            conn.close()
            return {"success": True, "message": "XP updated successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/leaderboard")
def get_leaderboard():
    try:
        conn = get_db_connection()
        if not conn:
            return {"leaderboard": []}
        with conn.cursor() as cur:
            cur.execute("SELECT user_name, xp, quizzes_solved FROM leaderboard ORDER BY xp DESC LIMIT 20;")
            ranks = cur.fetchall()
        conn.close()
        return {"success": True, "leaderboard": ranks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
