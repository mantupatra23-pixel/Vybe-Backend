import os
import boto3
import json
import psycopg2
import httpx
import tempfile
import redis
from typing import List, Optional
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from gtts import gTTS

load_dotenv()

app = FastAPI(title="Vybe Master Enterprise Engine v6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Environment Variables & Configuration
# ------------------------------------------------------------------
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "vybe-videos")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# ------------------------------------------------------------------
# Redis Initialization
# ------------------------------------------------------------------
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL)
    except Exception as e:
        print(f"Redis Setup Notice: {e}")

# ------------------------------------------------------------------
# DB & Cloud Connections
# ------------------------------------------------------------------
def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

s3_client = None
if R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY:
    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

# ------------------------------------------------------------------
# WebSocket Broadcast Manager
# ------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

ws_manager = ConnectionManager()

# ------------------------------------------------------------------
# Pydantic Request Models
# ------------------------------------------------------------------
class CreatorWalletRequest(BaseModel):
    creator_name: str
    adsense_id: str
    upi_id: str

class TipRequest(BaseModel):
    creator_name: str
    tipper_name: str
    amount: float

class UploadRequest(BaseModel):
    file_name: str
    title: str
    tags: str = ""
    creator_name: str = "Vybe Creator"
    audio_track: str = "Original Sound"
    content_type: str = "video/mp4"

class CommentRequest(BaseModel):
    video_id: int
    user_name: str
    comment_text: str

class ScoreUpdate(BaseModel):
    user_name: str
    xp_gained: int

class ScriptRequest(BaseModel):
    topic: str

class CaptionRequest(BaseModel):
    video_title: str

class PollVoteRequest(BaseModel):
    video_id: int
    option_index: int
    user_name: str

class VideoAnalyticsEvent(BaseModel):
    video_id: int
    watch_time_seconds: float
    total_duration_seconds: float
    completed_loop: bool = False
    quick_skip: bool = False

# ------------------------------------------------------------------
# Cache Utility
# ------------------------------------------------------------------
def clear_feed_cache():
    if redis_client:
        try:
            redis_client.delete("cached_video_feed")
        except Exception as e:
            print(f"Redis Cache Clear Error: {e}")

# ------------------------------------------------------------------
# Startup Database Migrations & Tables Setup
# ------------------------------------------------------------------
@app.on_event("startup")
def setup_tables_and_seed():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    tags TEXT,
                    cdn_url TEXT NOT NULL,
                    views INT DEFAULT 0,
                    likes INT DEFAULT 0,
                    creator_name TEXT DEFAULT 'Vybe Creator',
                    audio_track TEXT DEFAULT 'Original Sound',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS creator_wallets (
                    id SERIAL PRIMARY KEY,
                    creator_name TEXT UNIQUE NOT NULL,
                    adsense_id TEXT DEFAULT '',
                    upi_id TEXT DEFAULT '',
                    total_earnings FLOAT DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS tips (
                    id SERIAL PRIMARY KEY,
                    creator_name TEXT NOT NULL,
                    tipper_name TEXT NOT NULL,
                    amount FLOAT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS quizzes (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id),
                    question TEXT NOT NULL,
                    options JSONB NOT NULL,
                    correct_index INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS polls (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id),
                    question TEXT NOT NULL,
                    options JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS poll_votes (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id),
                    user_name TEXT NOT NULL,
                    option_index INT NOT NULL,
                    UNIQUE(video_id, user_name)
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id),
                    user_name TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audio_library (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    audio_url TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leaderboard (
                    id SERIAL PRIMARY KEY,
                    user_name TEXT UNIQUE NOT NULL,
                    xp INT DEFAULT 0,
                    quizzes_solved INT DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS video_analytics (
                    video_id INT PRIMARY KEY REFERENCES videos(id),
                    total_watch_time FLOAT DEFAULT 0.0,
                    watch_count INT DEFAULT 0,
                    completion_count INT DEFAULT 0,
                    quick_skips INT DEFAULT 0,
                    algo_score FLOAT DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    target_user TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    notification_type TEXT DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

            # Seed sample data if empty
            cur.execute("SELECT COUNT(*) FROM audio_library;")
            if cur.fetchone()["count"] == 0:
                sample_audios = [
                    ("Lofi Beats - Chill Tech", "NCS", "https://assets.mixkit.co/music/preview/mixkit-tech-house-vibes-130.mp3"),
                    ("Upbeat Cyberpunk Vibe", "RoyaltyFree", "https://assets.mixkit.co/music/preview/mixkit-hip-hop-02-738.mp3")
                ]
                for title, artist, url in sample_audios:
                    cur.execute("INSERT INTO audio_library (title, artist, audio_url) VALUES (%s, %s, %s);", (title, artist, url))
                conn.commit()

            conn.close()

# ------------------------------------------------------------------
# WebSockets Real-time Stream
# ------------------------------------------------------------------
@app.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# ------------------------------------------------------------------
# ALL CORE API ENDPOINTS
# ------------------------------------------------------------------
@app.get("/")
def health_check():
    return {
        "status": "ok",
        "system": "Vybe Enterprise Master Engine v6.0",
        "features": [
            "TikTok Recommendation Engine",
            "Creator & Founder Monetization",
            "Groq AI Script Copilot",
            "Smart Dynamic Captions",
            "Interactive Quiz & Poll Timers",
            "Upstash Redis Caching & WebSockets"
        ]
    }

# OTA Version Control
@app.get("/api/v1/app/latest-version")
def get_latest_app_version():
    return {
        "success": True,
        "latest_version": "1.0.2",
        "build_number": 2,
        "release_notes": "Master v6.0 with TikTok AI & Real-time Gamification",
        "download_url": "https://github.com/mantu-patra/Vybe/releases"
    }

# Video Feed (Database + Redis Cache)
@app.get("/api/v1/videos/feed")
def get_video_feed():
    if redis_client:
        try:
            cached = redis_client.get("cached_video_feed")
            if cached:
                return {"success": True, "source": "redis", "videos": json.loads(cached)}
        except Exception as e:
            print(f"Redis Cache Hit Notice: {e}")

    try:
        conn = get_db_connection()
        if not conn:
            return {"videos": []}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT v.*, COALESCE(w.adsense_id, '') as adsense_id 
                FROM videos v 
                LEFT JOIN creator_wallets w ON v.creator_name = w.creator_name 
                ORDER BY v.created_at DESC;
            """)
            videos = cur.fetchall()
            conn.close()

            for video in videos:
                if "created_at" in video:
                    video["created_at"] = str(video["created_at"])

            if redis_client:
                try:
                    redis_client.setex("cached_video_feed", 60, json.dumps(videos))
                except Exception:
                    pass

            return {"success": True, "source": "neon_db", "videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# TikTok Smart Recommendation Engine
@app.get("/api/v1/recommendation/smart-feed")
def get_tiktok_smart_feed():
    try:
        conn = get_db_connection()
        if not conn:
            return {"videos": []}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT v.*, COALESCE(a.algo_score, 0) as score,
                       COALESCE(w.adsense_id, '') as adsense_id,
                       COALESCE(w.upi_id, '') as creator_upi
                FROM videos v 
                LEFT JOIN video_analytics a ON v.id = a.video_id 
                LEFT JOIN creator_wallets w ON v.creator_name = w.creator_name
                ORDER BY score DESC, v.created_at DESC;
            """)
            feed = cur.fetchall()
            conn.close()

            for video in feed:
                if "created_at" in video:
                    video["created_at"] = str(video["created_at"])

            return {"success": True, "feed_type": "tiktok_algo", "videos": feed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Track TikTok Watch Behavior
@app.post("/api/v1/recommendation/track-engagement")
def track_engagement_event(payload: VideoAnalyticsEvent):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                is_completed = 1 if payload.completed_loop else 0
                is_skip = 1 if payload.quick_skip else 0

                cur.execute("""
                    INSERT INTO video_analytics (video_id, total_watch_time, watch_count, completion_count, quick_skips, algo_score)
                    VALUES (%s, %s, 1, %s, %s, %s)
                    ON CONFLICT (video_id) 
                    DO UPDATE SET 
                        total_watch_time = video_analytics.total_watch_time + EXCLUDED.total_watch_time,
                        watch_count = video_analytics.watch_count + 1,
                        completion_count = video_analytics.completion_count + EXCLUDED.completion_count,
                        quick_skips = video_analytics.quick_skips + EXCLUDED.quick_skips,
                        algo_score = video_analytics.algo_score + EXCLUDED.algo_score;
                """, (payload.video_id, payload.watch_time_seconds, is_completed, is_skip, (10 if payload.completed_loop else (-5 if payload.quick_skip else 2))))
                conn.commit()
                conn.close()
            return {"success": True, "message": "Engagement metrics logged"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Creator AI Script Assistant (Groq Copilot)
@app.post("/api/v1/smart/generate-script")
def generate_ai_script(payload: ScriptRequest):
    if not GROQ_API_KEY:
        return {
            "success": True,
            "script_data": {
                "hook": f"Here is what you need to know about {payload.topic}!",
                "body": "Micro learning helps you master skills fast in 30 seconds.",
                "cta": "Tap follow for daily lessons!",
                "tags": f"#{payload.topic.replace(' ', '')} #tech #ai"
            }
        }
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        prompt = f"Write a 30-second short script about {payload.topic} with hook, body, cta, and tags."
        res = httpx.post(url, headers=headers, json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }, timeout=15.0)

        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            return {"success": True, "script_data": {"hook": "AI Script", "body": content, "cta": "Follow for daily lessons", "tags": f"#{payload.topic}"}}
    except Exception as e:
        print(f"Groq Script Error: {e}")

    return {"success": True, "script_data": {"hook": "Did you know this?", "body": f"Check out this breakdown on {payload.topic}.", "cta": "Like and share with friends!", "tags": f"#{payload.topic}"}}

# Smart AI Captions Engine
@app.post("/api/v1/smart/auto-subtitles")
def generate_auto_subtitles(payload: CaptionRequest):
    return {
        "success": True,
        "captions": [
            {"start": 0.0, "end": 2.0, "text": f"Welcome to {payload.video_title}!"},
            {"start": 2.0, "end": 5.0, "text": "Powered by Vybe AI Automation Platform 🚀"}
        ]
    }

# Cloudflare R2 Upload Presigned URL Generator
@app.post("/api/v1/videos/generate-upload-url")
async def generate_upload_url(payload: UploadRequest):
    try:
        if not s3_client:
            raise HTTPException(status_code=500, detail="R2 Client Misconfigured")

        object_name = f"videos/{payload.file_name}"
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": object_name},
            ExpiresIn=900
        )
        public_cdn_url = f"{R2_PUBLIC_DOMAIN.rstrip('/')}/{object_name}" if R2_PUBLIC_DOMAIN else f"https://pub-{R2_ACCOUNT_ID}.r2.dev/{object_name}"

        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO videos (title, tags, cdn_url, creator_name, audio_track)
                    VALUES (%s, %s, %s, %s, %s);
                """, (payload.title, payload.tags, public_cdn_url, payload.creator_name, payload.audio_track))
                conn.commit()
                conn.close()

        clear_feed_cache()
        await ws_manager.broadcast({"type": "NEW_VIDEO", "title": payload.title, "creator": payload.creator_name})

        return {"success": True, "upload_url": presigned_url, "cdn_url": public_cdn_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Creator Wallet & AdSense Setup
@app.post("/api/v1/creator/wallet/update")
def update_creator_wallet(payload: CreatorWalletRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO creator_wallets (creator_name, adsense_id, upi_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (creator_name)
                    DO UPDATE SET adsense_id = EXCLUDED.adsense_id, upi_id = EXCLUDED.upi_id;
                """, (payload.creator_name, payload.adsense_id, payload.upi_id))
                conn.commit()
                conn.close()
            return {"success": True, "message": "Creator Monetization Updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/creator/wallet/{creator_name}")
def get_creator_wallet(creator_name: str):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM creator_wallets WHERE creator_name = %s;", (creator_name,))
                wallet = cur.fetchone()
                conn.close()
                return {"success": True, "wallet": wallet or {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Direct Tipping Engine
@app.post("/api/v1/creator/tip")
async def tip_creator(payload: TipRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO tips (creator_name, tipper_name, amount) VALUES (%s, %s, %s);",
                            (payload.creator_name, payload.tipper_name, payload.amount))
                cur.execute("""
                    INSERT INTO creator_wallets (creator_name, total_earnings)
                    VALUES (%s, %s)
                    ON CONFLICT (creator_name)
                    DO UPDATE SET total_earnings = creator_wallets.total_earnings + EXCLUDED.total_earnings;
                """, (payload.creator_name, payload.amount))

                cur.execute("""
                    INSERT INTO notifications (target_user, title, message, notification_type)
                    VALUES (%s, 'Super Tip Received! ⚡', %s, 'tip');
                """, (payload.creator_name, f"@{payload.tipper_name} tipped you ${payload.amount}!"))

                conn.commit()
                conn.close()

        await ws_manager.broadcast({"type": "NEW_TIP", "message": f"{payload.tipper_name} tipped ${payload.amount}!"})
        return {"success": True, "message": f"Successfully tipped ${payload.amount}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Social Features (Likes, Views, Comments)
@app.post("/api/v1/videos/{video_id}/like")
async def like_video(video_id: int):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE videos SET likes = likes + 1 WHERE id = %s RETURNING likes, title;", (video_id,))
                res = cur.fetchone()
                conn.commit()
                conn.close()
                clear_feed_cache()
                await ws_manager.broadcast({"type": "LIKE", "video_id": video_id})
                return {"success": True, "likes": res["likes"] if res else 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/videos/{video_id}/comments")
def get_comments(video_id: int):
    try:
        conn = get_db_connection()
        if not conn:
            return {"comments": []}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM comments WHERE video_id = %s ORDER BY created_at DESC;", (video_id,))
            comments = cur.fetchall()
            conn.close()
            return {"success": True, "comments": comments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/videos/comments/add")
async def add_comment(payload: CommentRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO comments (video_id, user_name, comment_text) VALUES (%s, %s, %s);",
                            (payload.video_id, payload.user_name, payload.comment_text))
                conn.commit()
                conn.close()
                await ws_manager.broadcast({"type": "NEW_COMMENT", "video_id": payload.video_id})
                return {"success": True, "message": "Comment added"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Poll System
@app.post("/api/v1/polls/vote")
async def vote_poll(payload: PollVoteRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO poll_votes (video_id, user_name, option_index)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (video_id, user_name)
                    DO UPDATE SET option_index = EXCLUDED.option_index;
                """, (payload.video_id, payload.user_name, payload.option_index))

                cur.execute("""
                    SELECT option_index, COUNT(*) as count 
                    FROM poll_votes WHERE video_id = %s GROUP BY option_index;
                """, (payload.video_id,))
                stats = cur.fetchall()
                conn.commit()
                conn.close()
                return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Quizzes & Audio Library
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

@app.get("/api/v1/audio/library")
def get_audio_library():
    try:
        conn = get_db_connection()
        if not conn:
            return {"tracks": []}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM audio_library ORDER BY id DESC;")
            tracks = cur.fetchall()
            conn.close()
            return {"success": True, "tracks": tracks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Gamification Leaderboard
@app.post("/api/v1/user/score")
async def update_user_score(payload: ScoreUpdate):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO leaderboard (user_name, xp, quizzes_solved)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (user_name)
                    DO UPDATE SET xp = leaderboard.xp + EXCLUDED.xp, quizzes_solved = leaderboard.quizzes_solved + 1;
                """, (payload.user_name, payload.xp_gained))
                conn.commit()
                conn.close()

                await ws_manager.broadcast({"type": "LEADERBOARD_UPDATE", "user": payload.user_name})
                return {"success": True, "message": "XP updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/leaderboard")
def get_leaderboard():
    try:
        conn = get_db_connection()
        if not conn:
            return {"leaderboard": []}
        with conn.cursor() as cur:
            cur.execute("SELECT user_name, xp, quizzes_solved FROM leaderboard ORDER BY xp DESC LIMIT 50;")
            ranks = cur.fetchall()
            conn.close()
            return {"success": True, "leaderboard": ranks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Activity Center / Notifications API
@app.get("/api/v1/notifications/{user_handle}")
def get_notifications(user_handle: str):
    conn = get_db_connection()
    if not conn:
        return {"success": True, "notifications": []}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM notifications WHERE target_user = %s ORDER BY created_at DESC LIMIT 20;", (user_handle,))
            notes = cur.fetchall()
            conn.close()
            return {"success": True, "notifications": notes}
    except Exception:
        if conn:
            conn.close()
        return {"success": True, "notifications": []}