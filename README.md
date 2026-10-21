# TubeScribe 

TubeScribe is an end-to-end full-stack AI application that automatically transforms any YouTube video or playlist into clean, highly structured, professional Markdown study notes. Built with a high-performance FastAPI backend, Google Gemini AI, Supabase storage, and a built-in modern web frontend.

---

##  Architecture Overview

```text
[ YouTube URL / Playlist ] 
       │
       ▼
[ yt-dlp Metadata & youtube-transcript-api ] (Extracts clean text / multi-video chunks)
       │
       ▼
[ Google Gemini 2.5 Flash / 3.8 Flash ] (1M token window context -> Generates Structured Markdown)
       │
       ▼
[ Supabase PostgreSQL ] (Caches notes & maintains user study library with RLS security)
       │
       ▼
[ Built-In Web Dashboard (/app) ] (1-click Copy Markdown, Download .md, & History Sidebar)
```

## Tech Stack
```
Backend Framework: FastAPI (Python)

AI Engine: Google Gemini (google-genai, gemini-2.5-flash / gemini-3.8-flash)

Transcript Extraction: youtube-transcript-api & yt-dlp

Database & Caching: Supabase (PostgreSQL with Row Level Security)

Frontend: HTML5, Tailwind CSS (via CDN), Markdown parser (marked.js)
