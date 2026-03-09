"""Core transcript service logic for YT-Transcript (v1.0.0)."""
from __future__ import annotations

import os
import re
from collections import Counter
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    FetchedTranscript,
    FetchedTranscriptSnippet,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)
from .models import TranscriptSegment, MCPTranscriptResult

load_dotenv()

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "is", "it", "that", "this", "was", "are", "be", "have",
    "we", "you", "i", "he", "she", "they", "not", "so", "as", "do", "if", "up",
    "out", "all", "just", "my", "your", "our", "gonna", "never", "around", "make",
    "say", "run", "let", "give",
}

def analyze_transcript(
    segments: list[TranscriptSegment],
    analysis_type: str = "summary",
) -> str:
    """Analyze transcript segments using Kilo model via OpenAI-compatible API."""
    from openai import OpenAI
    
    api_key = os.getenv("KILO_API_KEY")
    base_url = os.getenv("KILO_BASE_URL", "https://api.kilo.ai/api/gateway")
    model = os.getenv("KILO_MODEL", "kilo")  # Using "kilo" as requested
    
    if not api_key:
        return f"Error: KILO_API_KEY not set for analysis type: {analysis_type}"

    client = OpenAI(api_key=api_key, base_url=base_url)
    
    transcript_text = "\n".join([f"[{format_seconds(s.start)}] {s.text}" for s in segments])
    
    prompts = {
        "summary": "Provide a concise summary of the following video transcript:",
        "action_points": "Extract the key action points from the following video transcript:",
        "next_steps": "What are the recommended next steps based on this video transcript?",
        "structured_edit": "Provide a professional structured edit/rewrite of the following video transcript:",
        "professional-edit": "Provide a professional structured edit/rewrite of the following video transcript:",
    }
    
    prompt = prompts.get(analysis_type, prompts["summary"])
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes video transcripts."},
                {"role": "user", "content": f"{prompt}\n\n{transcript_text}"}
            ]
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        return f"Error during AI analysis: {exc}"


class TranscriptError(RuntimeError):
    """Raised when transcript extraction fails for any reason."""
    pass


def parse_video_id(url: str) -> str:
    """Extract the YouTube video ID from any supported URL format."""
    if not url:
        raise TranscriptError("Unable to parse video ID: empty URL")
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise TranscriptError(f"Unable to parse video ID from: {url!r}") from exc

    hostname = parsed.hostname or ""
    is_youtube = hostname in ("youtube.com", "www.youtube.com", "youtu.be", "www.youtu.be", "m.youtube.com")

    if not is_youtube:
        raise TranscriptError(f"Unable to parse video ID: not a YouTube URL: {url!r}")

    # youtu.be/<ID>
    if hostname in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("?")[0].split("/")[0]
        if video_id:
            return video_id
        raise TranscriptError(f"Unable to parse video ID from youtu.be URL: {url!r}")

    path = parsed.path
    # /shorts/<ID> or /embed/<ID>
    path_match = re.match(r"^/(?:shorts|embed)/([^/?&]+)", path)
    if path_match:
        return path_match.group(1)

    # /watch?v=<ID>
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"][0]:
        return qs["v"][0]

    raise TranscriptError(f"Unable to parse video ID from: {url!r}")


def format_seconds(seconds: float | int) -> str:
    """Convert seconds to HH:MM:SS or MM:SS timestamp string."""
    total = max(0, int(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _build_api_client(proxies: dict | None = None):
    """Build a YouTubeTranscriptApi instance with optional proxy config."""
    if proxies:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        import requests
        session = requests.Session()
        session.proxies.update(proxies)
        return YouTubeTranscriptApi(http_client=session)
    return YouTubeTranscriptApi()


def fetch_transcript(
    url: str,
    languages: list[str] | None = None,
) -> tuple[str, list[TranscriptSegment]]:
    """Fetch transcript from YouTube and return (video_id, segments)."""
    video_id = parse_video_id(url)  # raises TranscriptError on bad URL
    
    proxy = os.getenv("YT_PROXY") or None
    proxies = {"https": proxy, "http": proxy} if proxy else None
    default_langs = tuple(languages) if languages else ("en",)

    try:
        api = _build_api_client(proxies)
        fetched: FetchedTranscript = api.fetch(video_id, languages=default_langs)
        raw_snippets = list(fetched)
    except NoTranscriptFound as exc:
        raise TranscriptError(f"No transcript found for {video_id!r}: {exc}") from exc
    except TranscriptsDisabled as exc:
        raise TranscriptError(f"Transcripts are disabled for {video_id!r}: {exc}") from exc
    except VideoUnavailable as exc:
        raise TranscriptError(f"Video unavailable: {video_id!r}: {exc}") from exc
    except YouTubeTranscriptApiException as exc:
        raise TranscriptError(f"YouTube API error for {video_id!r}: {exc}") from exc
    except Exception as exc:
        raise TranscriptError(f"Unexpected error fetching transcript: {exc}") from exc

    segments = [
        TranscriptSegment(
            start=float(snip.start),
            duration=float(snip.duration),
            text=snip.text,
        )
        for snip in raw_snippets
    ]

    # Guard against empty/whitespace-only transcripts
    all_text = " ".join(s.text.strip() for s in segments)
    if not all_text.strip():
        raise TranscriptError("No transcript text found — all segments are empty or whitespace")

    return video_id, segments


def to_plain_text(segments: list[TranscriptSegment]) -> str:
    """Convert transcript segments to timestamped plain text."""
    if not segments:
        return ""
    lines = [f"[{format_seconds(seg.start)}] {seg.text}" for seg in segments]
    return "\n".join(lines)


def _top_keywords(segments: list[TranscriptSegment], n: int = 8) -> list[str]:
    """Extract top-N keywords by frequency, excluding stop words."""
    all_words = re.findall(r"[a-z]+", " ".join(seg.text for seg in segments).lower())
    filtered = [w for w in all_words if w not in _STOP_WORDS and len(w) > 3]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(n)]


def to_markdown(
    segments: list[TranscriptSegment],
    title: str = "YouTube Transcript",
) -> str:
    """Convert transcript segments to structured Markdown."""
    lines: list[str] = []

    # Title
    lines.append(f"# {title}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    if segments:
        intro = " ".join(seg.text for seg in segments[:3])
        lines.append(intro)
    else:
        lines.append("Transcript extracted successfully.")
    lines.append("")

    # Key Takeaways section
    lines.append("## Key Takeaways")
    lines.append("")
    if segments:
        keywords = _top_keywords(segments)
        for kw in keywords:
            lines.append(f"- {kw.capitalize()}")
    else:
        lines.append("- No content available.")
    lines.append("")

    # Transcript section
    lines.append("## Transcript")
    lines.append("")
    for seg in segments:
        ts = format_seconds(seg.start)
        lines.append(f"**{ts}** {seg.text}")

    if not segments:
        lines.append("_No transcript available._")
    lines.append("")

    return "\n".join(lines)
