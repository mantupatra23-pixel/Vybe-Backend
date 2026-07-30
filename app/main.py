import os
import boto3
import json
import psycopg2
import httpx
import tempfile
import redis
from typing import List
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from gtts import gTTS

load_dotenv()

app = FastAPI(title="Vybe Master Enterprise Engine", version="6.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Environment Variables & Configuration
# ---------------------------------------------------------
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "vybe-videos")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# Redis Initialization
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        print(f"Redis Setup Notice: {e}")

# DB & Cloud Connections
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

INITIAL_SEEDS = [
    {
        "title": "What is Artificial Intelligence in 30 Seconds?",
        "tags": "#ai #tech #future",
        "cdn_url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
        "creator": "AI Academy",
        "audio": "Original Sound - AI Academy"
    }
]

# WebSocket Broadcast Manager
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

# Pydantic Request Models
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

class PollVoteRequest(BaseModel):
    video_id: int
    option_index: int
    user_name: str

class CaptionRequest(BaseModel):
    video_title: str

class VideoAnalyticsEvent(BaseModel):
    video_id: int
    watch_time_seconds: float
    total_duration_seconds: float
    completed_loop: bool = False
    quick_skip: bool = False

# Cache Utility
def clear_feed_cache():
    if redis_client:
        try:
            redis_client.delete("cached_video_feed")
        except Exception as e:
            print(f"Redis Cache Clear Error: {e}")

# Startup Database Migrations & Tables Setup
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
                    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    options JSONB NOT NULL,
                    correct_index INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
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
                    video_id INT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
                    total_watch_time FLOAT DEFAULT 0.0,
                    watch_count INT DEFAULT 0,
                    completion_count INT DEFAULT 0,
                    quick_skips INT DEFAULT 0,
                    algo_score FLOAT DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS poll_votes (
                    id SERIAL PRIMARY KEY,
                    video_id INT NOT NULL,
                    option_index INT NOT NULL,
                    user_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM audio_library;")
            if cur.fetchone()["count"] == 0:
                sample_audios = [
                    ("Lofi Beats - Chill Tech", "NCS Music", "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"),
                    ("Upbeat Cyberpunk Vibe", "RoyaltyFree", "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3")
                ]
                for title, artist, url in sample_audios:
                    cur.execute("INSERT INTO audio_library (title, artist, audio_url) VALUES (%s, %s, %s);", (title, artist, url))
                conn.commit()

        conn.close()

# ---------------------------------------------------------
# WebSockets Real-time Stream
# ---------------------------------------------------------
@app.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# ---------------------------------------------------------
# ALL CORE API ENDPOINTS
# ---------------------------------------------------------

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "system": "Vybe Enterprise Master Engine v6.0 Active!",
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
        "latest_version": "1.0.1",
        "build_number": 2,
        "release_notes": "Master v6.0 with TikTok Algorithm, Creator Monetization, and Smart AI Tools!",
        "download_url": "https://github.com/mantupatra23-pixel/Vybe/releases/latest/download/Vybe-APK.apk"
    }

# Video Feed (Database + Redis Cache)
@app.get("/api/v1/videos/feed")
def get_video_feed():
    if redis_client:
        try:
            cached = redis_client.get("cached_video_feed")
            if cached:
                return {"success": True, "source": "redis_cache", "videos": json.loads(cached)}
        except Exception as e:
            print(f"Redis Cache Hit Notice: {e}")

    try:
        conn = get_db_connection()
        if not conn:
            return {"videos": []}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT v.*, COALESCE(w.adsense_id, '') as creator_adsense_id, COALESCE(w.upi_id, '') as creator_upi_id
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
            except Exception as e:
                print(f"Redis Set Cache Notice: {e}")

        return {"success": True, "source": "database", "videos": videos}
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
                       COALESCE(w.adsense_id, '') as creator_adsense_id, 
                       COALESCE(w.upi_id, '') as creator_upi_id
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

        return {"success": True, "feed_type": "tiktok_smart_algorithm", "videos": feed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Track TikTok Watch Behavior
@app.post("/api/v1/recommendation/track-engagement")
def track_engagement_event(payload: VideoAnalyticsEvent):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                is_completed = 1 if (payload.completed_loop or (payload.total_duration_seconds > 0 and payload.watch_time_seconds >= payload.total_duration_seconds * 0.8)) else 0
                is_skip = 1 if payload.quick_skip else 0

                cur.execute("""
                    INSERT INTO video_analytics (video_id, total_watch_time, watch_count, completion_count, quick_skips)
                    VALUES (%s, %s, 1, %s, %s)
                    ON CONFLICT (video_id)
                    DO UPDATE SET 
                        total_watch_time = video_analytics.total_watch_time + EXCLUDED.total_watch_time,
                        watch_count = video_analytics.watch_count + 1,
                        completion_count = video_analytics.completion_count + EXCLUDED.completion_count,
                        quick_skips = video_analytics.quick_skips + EXCLUDED.quick_skips;
                """, (payload.video_id, payload.watch_time_seconds, is_completed, is_skip))

                cur.execute("""
                    UPDATE video_analytics
                    SET algo_score = (total_watch_time * 3.0) + (completion_count * 5.0) - (quick_skips * 2.0)
                    WHERE video_id = %s;
                """, (payload.video_id,))
                conn.commit()
            conn.close()
            return {"success": True, "message": "Metric recorded!"}
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
                "body": "Micro learning helps you master skills in 30 seconds every day.",
                "cta": "Tap follow for daily lessons!",
                "tags": f"#{payload.topic.replace(' ', '')} #learning #tech"
            }
        }

    prompt = f"Write a 30-second short script about '{payload.topic}'. Return ONLY raw JSON with keys 'hook', 'body', 'cta', 'tags'."
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
            return {"success": True, "script_data": json.loads(content)}
    except Exception as e:
        print(f"Groq Script Error: {e}")

    return {
        "success": True,
        "script_data": {
            "hook": f"Did you know this about {payload.topic}?",
            "body": "Check out this 30-second breakdown!",
            "cta": "Like and share with friends!",
            "tags": f"#{payload.topic.replace(' ', '')} #tech"
        }
    }

# Smart AI Captions Engine
@app.post("/api/v1/smart/auto-subtitles")
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

# Interactive Poll Voting System
@app.post("/api/v1/smart/poll/vote")
def vote_on_poll(payload: PollVoteRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO poll_votes (video_id, option_index, user_name) VALUES (%s, %s, %s);",
                            (payload.video_id, payload.option_index, payload.user_name))
                conn.commit()

                cur.execute("SELECT option_index, COUNT(*) as count FROM poll_votes WHERE video_id = %s GROUP BY option_index;", (payload.video_id,))
                rows = cur.fetchall()
                total_votes = sum(r["count"] for r in rows)
                stats = {r["option_index"]: round((r["count"] / total_votes) * 100, 1) for r in rows}

            conn.close()
            return {"success": True, "total_votes": total_votes, "percentages": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Cloudflare R2 Upload Presigned URL Generator
@app.post("/api/v1/videos/generate-upload-url")
async def generate_upload_url(payload: UploadRequest):
    try:
        object_name = f"videos/{payload.file_name}"
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": object_name, "ContentType": payload.content_type},
            ExpiresIn=900
        )
        public_cdn_url = f"{R2_PUBLIC_DOMAIN.rstrip('/')}/{object_name}"

        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO videos (title, tags, cdn_url, creator_name, audio_track) VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                    (payload.title, payload.tags, public_cdn_url, payload.creator_name, payload.audio_track)
                )
                conn.commit()
            conn.close()

        clear_feed_cache()
        await ws_manager.broadcast({"type": "NEW_VIDEO", "message": f"New lesson: {payload.title}", "cdn_url": public_cdn_url})

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
            clear_feed_cache()
            return {"success": True, "message": "AdSense & Wallet Config Saved!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/creator/wallet/{creator_name}")
def get_creator_wallet(creator_name: str):
    try:
        conn = get_db_connection()
        if not conn:
            return {"wallet": {}}
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM creator_wallets WHERE creator_name = %s;", (creator_name,))
            wallet = cur.fetchone()
        conn.close()
        return {"success": True, "wallet": wallet or {"adsense_id": "", "upi_id": "", "total_earnings": 0.0}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Direct Tipping Engine
@app.post("/api/v1/creator/tip")
async def tip_creator(payload: TipRequest):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO tips (creator_name, tipper_name, amount) VALUES (%s, %s, %s);", (payload.creator_name, payload.tipper_name, payload.amount))
                cur.execute("""
                    INSERT INTO creator_wallets (creator_name, total_earnings)
                    VALUES (%s, %s)
                    ON CONFLICT (creator_name)
                    DO UPDATE SET total_earnings = creator_wallets.total_earnings + EXCLUDED.total_earnings;
                """, (payload.creator_name, payload.amount))
                conn.commit()
            conn.close()

            await ws_manager.broadcast({
                "type": "NEW_TIP",
                "message": f"{payload.tipper_name} tipped ₹{payload.amount} to @{payload.creator_name}! ⚡"
            })
            return {"success": True, "message": f"Successfully tipped ₹{payload.amount}!"}
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
                updated_likes = res["likes"]
                title = res["title"]
                conn.commit()
            conn.close()
            clear_feed_cache()
            await ws_manager.broadcast({"type": "LIKE_UPDATE", "message": f"Someone liked '{title}'!", "video_id": video_id, "likes": updated_likes})
            return {"success": True, "likes": updated_likes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/videos/{video_id}/view")
def increment_view(video_id: int):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE videos SET views = views + 1 WHERE id = %s;", (video_id,))
                conn.commit()
            conn.close()
            return {"success": True}
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
                cur.execute("INSERT INTO comments (video_id, user_name, comment_text) VALUES (%s, %s, %s);", (payload.video_id, payload.user_name, payload.comment_text))
                conn.commit()
            conn.close()
            await ws_manager.broadcast({"type": "NEW_COMMENT", "message": f"{payload.user_name} commented: {payload.comment_text}", "video_id": payload.video_id})
            return {"success": True, "message": "Comment posted!"}
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
            cur.execute("SELECT * FROM audio_library;")
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
                    DO UPDATE SET xp = leaderboard.xp + %s, quizzes_solved = leaderboard.quizzes_solved + 1;
                """, (payload.user_name, payload.xp_gained, payload.xp_gained))
                conn.commit()
            conn.close()

            await ws_manager.broadcast({"type": "LEADERBOARD_UPDATE", "message": f"{payload.user_name} earned +{payload.xp_gained} XP! ⚡"})
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
