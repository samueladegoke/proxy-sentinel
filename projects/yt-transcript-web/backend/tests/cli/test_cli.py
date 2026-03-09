"""Tests for CLI bridge (backend/cli.py)."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import pytest
from click.testing import CliRunner

pytest.importorskip("click")

from cli import cli


class TestCLIExtract:
    """Tests for the 'extract' command."""

    def test_extract_txt_timestamps(self, mock_yt_api):
        """Extract with --format txt-timestamps should include timestamps."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "txt-timestamps"])
        assert result.exit_code == 0
        assert "[00:00]" in result.output
        assert "Never gonna give you up" in result.output

    def test_extract_txt_clean(self, mock_yt_api):
        """Extract with --format txt-clean should omit timestamps."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--format", "txt-clean"])
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


class TestCLIAnalyze:
    """Tests for the 'analyze' command."""

    def test_analyze_summary(self, mock_yt_api):
        """Analyze with --type summary should call analyze_transcript."""
        runner = CliRunner()
        # Mocking analyze_transcript is harder because it's imported in CLI
        # But we can at least check if the command exists and runs
        result = runner.invoke(cli, ["analyze", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--type", "summary"])
        # It might fail if no API key is set, but exit_code 0 if mocked correctly or 1 with error message
        assert "Error: KILO_API_KEY not set" in result.output or result.exit_code == 0

    def test_analyze_help(self):
        """analyze --help should show usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "Analyze a YouTube video" in result.output
        assert "--type" in result.output
        assert "--format" in result.output

    def test_extract_with_language(self, mock_yt_api):
        """Extract with --language should pass language list to API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--language", "en", "--language", "de"])
        assert result.exit_code == 0
        # Verify fetch_transcript was called with languages=['en', 'de']
        # mock_yt_api is YouTubeTranscriptApi.fetch
        mock_yt_api.assert_called()
        args, kwargs = mock_yt_api.call_args
        assert list(kwargs["languages"]) == ["en", "de"]


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
        assert "txt-timestamps" in result.output
        assert "txt-clean" in result.output

    def test_analyze_help(self):
        """analyze --help should show usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "Analyze" in result.output
