import os
import re
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
from google import genai
from supabase import create_client, Client

app = FastAPI(
    title="TubeScribe API",
    description="Convert YouTube Videos & Playlists into Structured AI Study Notes",
    version="2.0.0"
)

# Enable CORS for Lovable and external frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Initialize Google Gemini Client (New Official SDK)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 2. Initialize Supabase Client Safely (Optional Persistence Layer)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY and "your_" not in SUPABASE_URL:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ Supabase initialization skipped: {e}")


# ----------------- DATA MODELS -----------------
class GenerateRequest(BaseModel):
    url: Optional[str] = None
    video_id: Optional[str] = None  # Kept for backward compatibility with your old Lovable frontend
    max_playlist_videos: int = 8    # Safety cap so 100-video playlists don't timeout
    force_regenerate: bool = False  # If False, returns cached notes from Supabase if available


# ----------------- HELPER FUNCTIONS -----------------
def extract_youtube_info(raw_input: str, max_videos: int = 8) -> dict:
    """
    Detects whether input is a YouTube Playlist or Single Video.
    Extracts video IDs and titles quickly using yt-dlp flat extraction (no video download).
    """
    raw_input = raw_input.strip()

    # Check if raw 11-character video ID was passed directly
    if re.match(r"^[a-zA-Z0-9_-]{11}$", raw_input):
        raw_input = f"https://www.youtube.com/watch?v={raw_input}"

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(raw_input, download=False)

            # Case A: It is a Playlist
            if info.get("_type") == "playlist" or "entries" in info:
                entries = [e for e in info.get("entries", []) if e and e.get("id")]
                selected_entries = entries[:max_videos]
                return {
                    "source_type": "playlist",
                    "source_id": info.get("id", "playlist"),
                    "title": info.get("title", "YouTube Playlist"),
                    "total_videos_in_playlist": len(entries),
                    "videos": [
                        {"id": e["id"], "title": e.get("title", f"Video {idx+1}")}
                        for idx, e in enumerate(selected_entries)
                    ],
                }

            # Case B: Single Video
            vid_id = info.get("id")
            return {
                "source_type": "video",
                "source_id": vid_id,
                "title": info.get("title", f"YouTube Video ({vid_id})"),
                "total_videos_in_playlist": 1,
                "videos": [{"id": vid_id, "title": info.get("title", vid_id)}],
            }

    except Exception:
        # Fallback regex parser if yt-dlp metadata lookup is blocked
        vid_match = re.search(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", raw_input)
        if vid_match:
            vid_id = vid_match.group(1)
            return {
                "source_type": "video",
                "source_id": vid_id,
                "title": f"YouTube Video ({vid_id})",
                "total_videos_in_playlist": 1,
                "videos": [{"id": vid_id, "title": f"Video {vid_id}"}],
            }
        raise ValueError("Could not parse a valid YouTube Video or Playlist URL.")


def fetch_single_transcript(video_id: str) -> str:
    """Fetches transcript using youtube-transcript-api v1.0+ with language fallback."""
    ytt_api = YouTubeTranscriptApi()
    try:
        # Try English or Hindi first
        transcript_list = ytt_api.fetch(video_id, languages=["en", "en-US", "en-GB", "hi"])
    except Exception:
        # Fallback: grab whatever transcript language is available
        transcript_Index = ytt_api.list(video_id)
        first_available = next(iter(transcript_Index))
        transcript_list = first_available.fetch()

    text = " ".join(
        chunk.text if hasattr(chunk, "text") else chunk.get("text", "")
        for chunk in transcript_list
    )
    return text.strip()


# ----------------- API ENDPOINTS -----------------
@app.get("/")
def health_check():
    return {
        "status": "running",
        "service": "TubeScribe v2.0 (Video + Playlist Engine)",
        "gemini_configured": bool(GEMINI_API_KEY),
        "supabase_configured": bool(supabase),
        "ui_url": "http://127.0.0.1:8000/app",
    }


@app.post("/api/process")
async def generate_notes(request: GenerateRequest):
    if not gemini_client:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is missing in your .env file. Get one from https://aistudio.google.com/apikey"
        )

    target_url = request.url or request.video_id
    if not target_url:
        raise HTTPException(status_code=400, detail="Please provide a YouTube video or playlist URL.")

    # 1. Extract Video / Playlist Metadata
    try:
        media_info = extract_youtube_info(target_url, max_videos=request.max_playlist_videos)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    source_id = media_info["source_id"]
    source_type = media_info["source_type"]
    title = media_info["title"]

    # 2. Check Supabase Cache (Unless force_regenerate is True)
    if supabase and not request.force_regenerate:
        try:
            existing = (
                supabase.table("youtube_notes")
                .select("*")
                .eq("video_id", source_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if existing.data:
                cached_row = existing.data[0]
                return {
                    "status": "success",
                    "cached": True,
                    "message": "Loaded existing notes instantaneously from Supabase cache!",
                    "video_id": source_id,
                    "source_type": source_type,
                    "title": cached_row.get("title", title),
                    "content": cached_row["content"],
                }
        except Exception:
            pass  # Continue to fresh generation if cache lookup fails

    # 3. Fetch Transcripts (For Single Video OR Multiple Videos in Playlist)
    compiled_transcripts = []
    skipped_videos = []

    for idx, vid in enumerate(media_info["videos"], start=1):
        try:
            t_text = fetch_single_transcript(vid["id"])
            if t_text:
                compiled_transcripts.append(
                    f"--- VIDEO {idx}: {vid['title']} (ID: {vid['id']}) ---\n{t_text}"
                )
        except Exception as e:
            skipped_videos.append(f"{vid['title']} ({vid['id']})")

    if not compiled_transcripts:
        raise HTTPException(
            status_code=400,
            detail="Could not extract transcripts. Ensure the video(s) have captions/subtitles enabled."
        )

    full_transcript_payload = "\n\n".join(compiled_transcripts)

    # 4. Generate Structured Study Notes with Gemini 2.5 Flash
    if source_type == "playlist":
        prompt = f"""
        You are an elite technical educator and note-taker.
        Below are the transcripts from the YouTube Playlist: "{title}" ({len(compiled_transcripts)} videos processed).

        Generate a comprehensive, master Markdown Study Guide with:
        1. **Executive Summary & Playlist Roadmap**: High-level synthesis of what the entire playlist teaches.
        2. **Module-by-Module Breakdown**: For each video, create a dedicated section with its title, core concepts, technical definitions, code/formulas mentioned, and bulleted key takeaways.
        3. **Master Cheat Sheet & Actionable Summary**: Consolidated glossary and revision checklist at the end.

        TRANSCRIPTS:
        {full_transcript_payload[:400000]}
        """
    else:
        prompt = f"""
        You are an expert technical note-taker. Generate clean, highly structured Markdown study notes for the YouTube video "{title}".
        Include:
        1. **TL;DR Executive Summary** (3-4 sentences)
        2. **Core Concepts & Detailed Breakdown** (with clear H2/H3 headings and bullet points)
        3. **Key Formulas, Code Snippets, or Frameworks Mentioned** (if applicable)
        4. **Key Takeaways & Action Items**

        TRANSCRIPT:
        {full_transcript_payload[:400000]}
        """

    try:
        ai_response = gemini_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
        )
        notes_content = ai_response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini generation failed: {str(e)}")

    # 5. Save to Supabase (Graceful Handling)
    saved_to_db = False
    if supabase:
        try:
            supabase.table("youtube_notes").insert({
                "video_id": source_id,
                "title": title,
                "source_type": source_type,
                "content": notes_content,
            }).execute()
            saved_to_db = True
        except Exception:
            # Fallback if user's table only has video_id and content columns
            try:
                supabase.table("youtube_notes").insert({
                    "video_id": source_id,
                    "content": notes_content,
                }).execute()
                saved_to_db = True
            except Exception as db_err:
                print(f"⚠️ Supabase insert warning: {db_err}")

    return {
        "status": "success",
        "cached": False,
        "saved_to_supabase": saved_to_db,
        "message": f"Successfully generated notes for {len(compiled_transcripts)} video(s)!",
        "video_id": source_id,
        "source_type": source_type,
        "title": title,
        "videos_processed": len(compiled_transcripts),
        "videos_skipped": skipped_videos,
        "content": notes_content,
    }


@app.get("/api/notes")
def list_saved_notes():
    """Fetches saved notes history from Supabase for the frontend library."""
    if not supabase:
        return {"notes": [], "message": "Supabase is not configured."}
    try:
        res = (
            supabase.table("youtube_notes")
            .select("*")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        return {"notes": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Serve Built-In Frontend at /app
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/app")
    def serve_frontend():
        return FileResponse("static/index.html")