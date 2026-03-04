"""FastAPI backend for YT-Transcript Web (v1.0.0)."""
from __future__ import annotations

import json
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .transcript_service import (
    TranscriptError,
    TranscriptSegment,
    fetch_transcript,
    to_markdown,
    to_plain_text,
)

load_dotenv()

app = FastAPI(
    title="YT-Transcript API",
    description="Extract and summarize YouTube video transcripts.",
    version="1.0.0",
)

# CORS Configuration
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000,https://yt-transcript-web.pages.dev",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscriptRequest(BaseModel):
    """Request model for transcript extraction."""
    url: str
    languages: Optional[list[str]] = None


class TranscriptResponse(BaseModel):
    """Response model for transcript extraction."""
    video_id: str
    segments: list[dict]
    title: Optional[str] = None


class SummaryResponse(BaseModel):
    """Response model for summary extraction."""
    video_id: str
    summary: str
    segments_used: int


@app.get("/")
def read_root():
    """Root endpoint."""
    return {"status": "ok", "version": "1.0.0", "service": "yt-transcript-web"}


@app.get("/api/transcript")
def get_transcript(
    url: str = Query(..., description="YouTube video URL"),
    languages: Optional[str] = Query(None, description="Comma-separated language codes"),
):
    """Extract transcript from a YouTube video."""
    lang_list = languages.split(",") if languages else None
    try:
        video_id, segments = fetch_transcript(url, languages=lang_list)
    except TranscriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "video_id": video_id,
        "segments": [seg.to_dict() for seg in segments],
    }


@app.get("/api/summary")
def get_summary(
    url: str = Query(..., description="YouTube video URL"),
    limit: int = Query(5, ge=1, le=20, description="Number of segments to summarize"),
):
    """Generate a summary from a YouTube transcript."""
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summary_segments = segments[:limit]
    summary_text = " ".join(seg.text for seg in summary_segments)

    return {
        "video_id": video_id,
        "summary": summary_text,
        "segments_used": len(summary_segments),
    }


@app.post("/api/transcript")
def post_transcript(request: TranscriptRequest):
    """Extract transcript via POST (for complex requests)."""
    try:
        video_id, segments = fetch_transcript(request.url, languages=request.languages)
    except TranscriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "video_id": video_id,
        "segments": [seg.to_dict() for seg in segments],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
