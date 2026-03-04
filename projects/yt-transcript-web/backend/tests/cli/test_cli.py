"""Tests for CLI bridge (backend/cli.py)."""
from __future__ import annotations

import json
import pytest
from click.testing import CliRunner

pytest.importorskip("click")

from cli import cli


class TestCLIExtract:
    """Tests for the 'extract' command."""

    def test_extract_plain_with_timestamps(self, mock_yt_api):
        """Extract with --format plain --timestamps should include timestamps."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "plain", "--timestamps"])
        assert result.exit_code == 0
        assert "[00:00]" in result.output
        assert "Never gonna give you up" in result.output

    def test_extract_plain_no_timestamps(self, mock_yt_api):
        """Extract with --format plain --no-timestamps should omit timestamps."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "plain", "--no-timestamps"])
        assert result.exit_code == 0
        assert "[00:00]" not in result.output
        assert "Never gonna give you up" in result.output

    def test_extract_markdown(self, mock_yt_api):
        """Extract with --format md should produce markdown."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "md"])
        assert result.exit_code == 0
        assert "# Transcript" in result.output
        assert "**00:00**" in result.output

    def test_extract_json(self, mock_yt_api):
        """Extract with --format json should produce valid JSON with segments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert len(data["segments"]) > 0
        assert data["segments"][0]["text"] == "Never gonna give you up"

    def test_extract_invalid_url(self):
        """Extract with invalid URL should exit with error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.google.com"])
        assert result.exit_code == 1
        assert "Error:" in result.output


class TestCLISummary:
    """Tests for the 'summary' command."""

    def test_summary_plain(self, mock_yt_api):
        """Summary with --format plain should output summary text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "plain"])
        assert result.exit_code == 0
        assert "Never gonna give you up" in result.output

    def test_summary_markdown(self, mock_yt_api):
        """Summary with --format md should include heading."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "md"])
        assert result.exit_code == 0
        assert "# Summary:" in result.output

    def test_summary_json(self, mock_yt_api):
        """Summary with --format json should produce valid JSON."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert "summary" in data
        assert "segments_used" in data

    def test_summary_limit(self, mock_yt_api):
        """Summary with --limit N should use N segments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--limit", "2", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["segments_used"] == 2


class TestCLIHelp:
    """Tests for CLI help and version."""

    def test_version(self):
        """--version should show version info."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "yt-transcript-cli" in result.output

    def test_extract_help(self):
        """extract --help should show usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "--help"])
        assert result.exit_code == 0
        assert "Extract transcript" in result.output
        assert "--format" in result.output
        assert "--timestamps" in result.output

    def test_summary_help(self):
        """summary --help should show usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "--help"])
        assert result.exit_code == 0
        assert "Summarize" in result.output
        assert "--limit" in result.output
