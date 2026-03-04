"""Data models for YT-Transcript."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TranscriptSegment:
    """Represents a single segment of a YouTube transcript."""
    start: float
    duration: float
    text: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "start": self.start,
            "duration": self.duration,
            "text": self.text,
        }


@dataclass
class TranscriptResult:
    """Result of transcript extraction."""
    video_id: str
    segments: list[TranscriptSegment]
    title: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "video_id": self.video_id,
            "title": self.title,
            "segments": [seg.to_dict() for seg in self.segments],
        }


@dataclass
class MCPTranscriptResult:
    """Structured result for MCP transcript tools."""
    video_id: str
    transcript: str
    summary: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "video_id": self.video_id,
            "transcript": self.transcript,
            "summary": self.summary,
            "error": self.error,
        }
