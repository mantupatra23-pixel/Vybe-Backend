import os
import boto3
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Vybe AI & API Engine", version="1.0.0")

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

class UploadRequest(BaseModel):
    file_name: str
    title: str
    tags: str = ""
    content_type: str = "video/mp4"

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
            """)
            conn.commit()
        conn.close()

# Mock AI Quiz Generator (Template for LLM API integration)
def generate_ai_quiz(title: str, tags: str):
    return [
        {
            "question": f"What is the primary topic covered in '{title}'?",
            "options": [title, "General Tech Concept", "Random Trivia", "Advanced Mathematics"],
            "correct_index": 0
        },
        {
            "question": f"Which tag best classifies this short lesson?",
            "options": ["#entertainment", tags if tags else "#learning", "#news", "#gaming"],
            "correct_index": 1
        }
    ]

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Vybe AI Backend is Live!"}

@app.post("/api/v1/videos/generate-upload-url")
def generate_upload_url(payload: UploadRequest):
    try:
        object_name = f"videos/{payload.file_name}"
        
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": R2_BUCKET_NAME,
                "Key": object_name,
                "ContentType": payload.content_type,
            },
            ExpiresIn=900,
        )
        
        public_cdn_url = f"{R2_PUBLIC_DOMAIN.rstrip('/')}/{object_name}"

        # Save metadata & Auto-generate Quiz
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO videos (title, tags, cdn_url) VALUES (%s, %s, %s) RETURNING id;",
                    (payload.title, payload.tags, public_cdn_url)
                )
                video_id = cur.fetchone()["id"]

                # Auto Generate AI Quiz Questions
                quiz_items = generate_ai_quiz(payload.title, payload.tags)
                for item in quiz_items:
                    cur.execute(
                        "INSERT INTO quizzes (video_id, question, options, correct_index) VALUES (%s, %s, %s, %s);",
                        (video_id, item["question"], json.dumps(item["options"]), item["correct_index"])
                    )
                conn.commit()
            conn.close()

        return {
            "success": True,
            "upload_url": presigned_url,
            "file_path": object_name,
            "cdn_url": public_cdn_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
