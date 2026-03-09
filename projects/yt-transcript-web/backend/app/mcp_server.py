"""MCP Tool definitions for YouTube Transcript service."""
from __future__ import annotations

from dataclasses import dataclass

from .transcript_service import (
    TranscriptError,
    fetch_transcript,
    to_markdown,
    to_plain_text,
    analyze_transcript,
)


@dataclass
class MCPTranscriptResult:
    video_id: str
    txt_timestamps: str
    txt_clean: str
    markdown: str
    segment_count: int


async def mcp_extract_transcript(url: str, languages: list[str] | None = None) -> MCPTranscriptResult:
    """MCP tool: Extract transcript from a YouTube URL."""
    try:
        video_id, segments = fetch_transcript(url, languages=languages)
    except TranscriptError as exc:
        msg = str(exc)
        if "captions" in msg.lower() or "disabled" in msg.lower():
            raise ValueError(f"No captions available: {msg}") from exc
        raise ValueError(f"Invalid YouTube URL or unavailable video: {msg}") from exc

    return MCPTranscriptResult(
        video_id=video_id,
        txt_timestamps=to_plain_text(segments),
        txt_clean="\n".join(seg.text for seg in segments),
        markdown=to_markdown(segments),
        segment_count=len(segments),
    )


async def mcp_analyze_video(url: str, analysis_type: str = "summary") -> dict:
    """MCP tool: Analyze a YouTube video using AI."""
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as exc:
        raise ValueError(str(exc)) from exc

    analysis = analyze_transcript(segments, analysis_type)
    return {
        "video_id": video_id,
        "analysis_type": analysis_type,
        "result": analysis
    }


async def mcp_get_summary(url: str, limit: int = 5) -> dict:
    """MCP tool: Get extractive summary from a YouTube transcript."""
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as exc:
        raise ValueError(str(exc)) from exc

    if not segments:
        return {"video_id": video_id, "summary": "", "segments_used": 0}

    summary_segments = segments[:limit]
    summary = " ".join(seg.text for seg in summary_segments)
    return {"video_id": video_id, "summary": summary, "segments_used": len(summary_segments)}


async def mcp_get_ai_summary(url: str) -> dict:
    """MCP tool: Get AI-generated summary from a YouTube transcript."""
    return await mcp_analyze_video(url, "summary")
