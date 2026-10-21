# TubeScribe 🚀

TubeScribe is an end-to-end full-stack AI application that automatically transforms any YouTube video or playlist into clean, highly structured, professional Markdown study notes. Built with a high-performance FastAPI backend, Google Gemini AI, Supabase storage, and a built-in modern web frontend.

---

## 🏗️ Architecture Overview

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
