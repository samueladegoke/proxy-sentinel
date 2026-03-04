"""CLI bridge for YT-Transcript using click.

Provides command-line access to transcript extraction and summarization.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

import click

from app.transcript_service import (
    TranscriptError,
    fetch_transcript,
    to_markdown,
    to_plain_text,
)


@click.group()
@click.version_option(version="1.0.0", prog_name="yt-transcript-cli")
def cli() -> None:
    """YT-Transcript CLI — Extract and summarize YouTube transcripts."""
    pass


@cli.command()
@click.argument("url")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["plain", "md", "json"], case_sensitive=False),
    default="plain",
    help="Output format: plain (text), md (markdown), or json.",
)
@click.option(
    "--timestamps/--no-timestamps",
    default=True,
    help="Include timestamps in plain text output. (default: enabled)",
)
def extract(url: str, fmt: str, timestamps: bool) -> None:
    """Extract transcript from a YouTube video URL.

    URL must be a valid YouTube video URL (watch, shorts, embed, or youtu.be).
    """
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if fmt == "json":
        output = json.dumps(
            {
                "video_id": video_id,
                "segments": [
                    {"start": s.start, "duration": s.duration, "text": s.text}
                    for s in segments
                ],
            },
            indent=2,
        )
    elif fmt == "md":
        output = to_markdown(segments, title=f"Transcript: {video_id}")
    else:  # plain
        if timestamps:
            output = to_plain_text(segments)
        else:
            output = "\n".join(seg.text for seg in segments)

    click.echo(output)


@cli.command()
@click.argument("url")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["plain", "md", "json"], case_sensitive=False),
    default="plain",
    help="Output format: plain (text), md (markdown), or json.",
)
@click.option(
    "--limit",
    type=int,
    default=5,
    help="Number of summary sentences to generate. (default: 5)",
)
def summary(url: str, fmt: str, limit: int) -> None:
    """Summarize a YouTube video transcript.

    URL must be a valid YouTube video URL. Outputs a summary of the content.
    """
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Generate summary by taking the first N segments' text
    summary_segments = segments[:limit] if segments else []
    summary_text = " ".join(seg.text for seg in summary_segments)

    if fmt == "json":
        output = json.dumps(
            {"video_id": video_id, "summary": summary_text, "segments_used": limit},
            indent=2,
        )
    elif fmt == "md":
        output = f"# Summary: {video_id}\n\n{summary_text}"
    else:  # plain
        output = summary_text

    click.echo(output)


if __name__ == "__main__":
    cli()
