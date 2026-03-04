"""MCP Tool definitions for YouTube Transcript service."""
from __future__ import annotations

from dataclasses import dataclass

from .transcript_service import (
    TranscriptError,
    fetch_transcript,
    to_markdown,
    to_plain_text,
)


@dataclass
class MCPTranscriptResult:
    video_id: str
    plain_text: str
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
        plain_text=to_plain_text(segments),
        markdown=to_markdown(segments),
        segment_count=len(segments),
    )


async def mcp_get_summary(url: str) -> dict:
    """MCP tool: Get extractive summary from a YouTube transcript."""
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as exc:
        raise ValueError(str(exc)) from exc

    summary = " ".join(seg.text for seg in segments[:5])
    return {"video_id": video_id, "summary": summary}
