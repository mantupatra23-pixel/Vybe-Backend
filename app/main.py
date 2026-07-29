import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Vybe API Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# R2 Credentials
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "vybe-videos")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "")

# Neon Database Connection
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
            """)
            conn.commit()
        conn.close()

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Vybe FastAPI Engine Live with Neon Postgres!"}

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

        # Save metadata to Neon DB
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO videos (title, tags, cdn_url) VALUES (%s, %s, %s)",
                    (payload.title, payload.tags, public_cdn_url)
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
