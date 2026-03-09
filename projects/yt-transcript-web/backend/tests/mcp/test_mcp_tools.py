"""TDD tests for MCP layer — mcp_server.py."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

# Import MockFetchedTranscript from conftest
from tests.conftest import MockFetchedTranscript

try:
    from app.mcp_server import (
        mcp_extract_transcript,
        mcp_get_summary,
        mcp_analyze_video,
        MCPTranscriptResult,
    )
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not MCP_AVAILABLE,
    reason="MCP server not yet implemented — RED phase"
)


class TestMCPExtractTool:
    """mcp_extract_transcript(url) → MCPTranscriptResult"""

    @pytest.mark.asyncio
    async def test_valid_url_returns_result_object(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert isinstance(result, MCPTranscriptResult)

    @pytest.mark.asyncio
    async def test_result_has_video_id(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert result.video_id == "dQw4w9WgXcQ"

    @pytest.mark.asyncio
    async def test_result_has_txt_timestamps(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert isinstance(result.txt_timestamps, str)
        assert len(result.txt_timestamps) > 0

    @pytest.mark.asyncio
    async def test_result_has_txt_clean(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert isinstance(result.txt_clean, str)
        assert "[00:00]" not in result.txt_clean

    @pytest.mark.asyncio
    async def test_result_has_markdown(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert "## Transcript" in result.markdown

    @pytest.mark.asyncio
    async def test_invalid_url_raises_value_error(self):
        """MCP tools should raise ValueError, not RuntimeError, for bad input."""
        with pytest.raises(ValueError, match="Invalid YouTube URL"):
            await mcp_extract_transcript(url="https://google.com")

    @pytest.mark.asyncio
    async def test_missing_captions_raises_value_error(self):
        """MCP tools should raise ValueError when captions are disabled."""
        from youtube_transcript_api import TranscriptsDisabled
        with patch("app.transcript_service.YouTubeTranscriptApi") as mock_class:
            mock_api = MagicMock()
            mock_api.fetch.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")
            mock_class.return_value = mock_api
            with pytest.raises(ValueError, match="captions"):
                await mcp_extract_transcript(
                    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                )


class TestMCPSummaryTool:
    """mcp_get_summary(url) → dict"""

    @pytest.mark.asyncio
    async def test_returns_summary_dict(self, mock_yt_api):
        result = await mcp_get_summary(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert "summary" in result
        assert "video_id" in result
        assert "segments_used" in result

    @pytest.mark.asyncio
    async def test_summary_with_limit(self, mock_yt_api):
        result = await mcp_get_summary(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            limit=2
        )
        assert result["segments_used"] == 2

    @pytest.mark.asyncio
    async def test_summary_empty_segments(self):
        """Summary should raise ValueError when no transcript segments available."""
        with patch("app.transcript_service.YouTubeTranscriptApi") as mock_class:
            mock_api = MagicMock()
            mock_api.fetch.return_value = MockFetchedTranscript([])
            mock_class.return_value = mock_api
            with pytest.raises(ValueError, match="No transcript"):
                await mcp_get_summary(
                    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                )

    @pytest.mark.asyncio
    async def test_invalid_url_raises(self):
        with pytest.raises((ValueError, Exception)):
            await mcp_get_summary(url="not-a-url")


class TestMCPAnalyzeTool:
    """mcp_analyze_video(url) → dict"""

    @pytest.mark.asyncio
    async def test_returns_analyze_dict(self, mock_yt_api):
        # We don't have KILO_API_KEY set, so it might return error string in 'result'
        result = await mcp_analyze_video(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert "result" in result
        assert "video_id" in result
        assert "analysis_type" in result
