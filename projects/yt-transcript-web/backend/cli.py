"""CLI bridge for YT-Transcript using click.

Provides command-line access to transcript extraction and summarization.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

import click

from app import __version__
from app.transcript_service import (
    TranscriptError,
    fetch_transcript,
    to_markdown,
    to_plain_text,
    analyze_transcript,
)


@click.group()
@click.version_option(version=__version__, prog_name="yt-transcript-cli")
def cli() -> None:
    """YT-Transcript CLI — Extract and summarize YouTube transcripts."""
    pass


@cli.command()
@click.argument("url")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["txt-timestamps", "txt-clean", "md", "json"], case_sensitive=False),
    default="txt-timestamps",
    help="Output format: txt-timestamps, txt-clean, md, or json.",
)
@click.option(
    "--language",
    "-l",
    "languages",
    multiple=True,
    help="Preferred language codes (e.g., en, de). Can be repeated.",
)
def extract(url: str, fmt: str, languages: tuple[str, ...]) -> None:
    """Extract transcript from a YouTube video URL.

    URL must be a valid YouTube video URL (watch, shorts, embed, or youtu.be).
    """
    lang_list = list(languages) if languages else None
    try:
        video_id, segments = fetch_transcript(url, languages=lang_list)
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
    elif fmt == "txt-clean":
        output = "\n".join(seg.text for seg in segments)
    else:  # txt-timestamps (default)
        output = to_plain_text(segments)

    click.echo(output)


@cli.command()
@click.argument("url")
@click.option(
    "--type",
    "analysis_type",
    type=click.Choice(["summary", "action_points", "next_steps", "professional-edit"], case_sensitive=False),
    default="summary",
    help="Analysis type.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["txt", "md"], case_sensitive=False),
    default="txt",
    help="Output format: txt or md.",
)
def analyze(url: str, analysis_type: str, fmt: str) -> None:
    """Analyze a YouTube video transcript using AI.

    Supported types: summary, action_points, next_steps, professional-edit.
    """
    try:
        video_id, segments = fetch_transcript(url)
    except TranscriptError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    result = analyze_transcript(segments, analysis_type)

    if fmt == "md":
        header = analysis_type.replace("_", " ").replace("-", " ").title()
        output = f"# {header}\n\n{result}"
    else:  # txt
        output = result

    click.echo(output)


if __name__ == "__main__":
    cli()
