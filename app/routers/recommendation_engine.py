from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/api/v1/recommendation", tags=["TikTok Algorithm Engine"])

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db_connection():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class VideoAnalyticsEvent(BaseModel):
    video_id: int
    watch_time_seconds: float
    total_duration_seconds: float
    completed_loop: bool = False
    quick_skip: bool = False

# TikTok Analytics Ingestion Endpoint
@router.post("/track-engagement")
def track_engagement_event(payload: VideoAnalyticsEvent):
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                # Ensure analytics table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS video_analytics (
                        video_id INT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
                        total_watch_time FLOAT DEFAULT 0.0,
                        watch_count INT DEFAULT 0,
                        completion_count INT DEFAULT 0,
                        quick_skips INT DEFAULT 0,
                        algo_score FLOAT DEFAULT 0.0
                    );
                """)
                
                # Calculate Watch Completion Ratio
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

                # Recalculate Algorithm Score (TikTok Mathematical Model)
                # Formula: (Watch Time * 3) + (Completions * 5) - (Quick Skips * 2)
                cur.execute("""
                    UPDATE video_analytics
                    SET algo_score = (total_watch_time * 3.0) + (completion_count * 5.0) - (quick_skips * 2.0)
                    WHERE video_id = %s;
                """, (payload.video_id,))

                conn.commit()
            conn.close()
            return {"success": True, "message": "Engagement metric registered successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# TikTok Smart Feed Endpoint (Mix of High Score + Cold-Start Discovery)
@router.get("/smart-feed")
def get_tiktok_smart_feed():
    try:
        conn = get_db_connection()
        if not conn:
            return {"videos": []}
        with conn.cursor() as cur:
            # 1. Top 70% High Scoring Viral Videos
            cur.execute("""
                SELECT v.*, COALESCE(a.algo_score, 0) as score,
                       COALESCE(w.adsense_id, '') as creator_adsense_id, 
                       COALESCE(w.upi_id, '') as creator_upi_id
                FROM videos v
                LEFT JOIN video_analytics a ON v.id = a.video_id
                LEFT JOIN creator_wallets w ON v.creator_name = w.creator_name
                ORDER BY score DESC, v.created_at DESC
                LIMIT 20;
            """)
            viral_videos = cur.fetchall()

            # 2. 30% Cold-Start Exploration Test Batch (New Creators)
            cur.execute("""
                SELECT v.*, 0 as score,
                       COALESCE(w.adsense_id, '') as creator_adsense_id, 
                       COALESCE(w.upi_id, '') as creator_upi_id
                FROM videos v
                LEFT JOIN creator_wallets w ON v.creator_name = w.creator_name
                WHERE v.id NOT IN (SELECT video_id FROM video_analytics)
                ORDER BY v.created_at DESC
                LIMIT 10;
            """)
            new_videos = cur.fetchall()

        conn.close()

        # Combine and Shuffle Feed
        combined_feed = viral_videos + new_videos
        for video in combined_feed:
            if "created_at" in video:
                video["created_at"] = str(video["created_at"])

        return {"success": True, "feed_type": "tiktok_smart_algorithm", "videos": combined_feed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
