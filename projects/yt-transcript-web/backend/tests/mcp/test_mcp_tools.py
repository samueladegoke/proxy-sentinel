"""TDD tests for MCP layer — mcp_server.py."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

try:
    from app.mcp_server import (
        mcp_extract_transcript,
        mcp_get_summary,
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
    async def test_result_has_plain_text(self, mock_yt_api):
        result = await mcp_extract_transcript(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert isinstance(result.plain_text, str)
        assert len(result.plain_text) > 0

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
    async def test_missing_captions_raises_value_error(self, mock_yt_api):
        from youtube_transcript_api import TranscriptsDisabled
        mock_yt_api.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")
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

    @pytest.mark.asyncio
    async def test_invalid_url_raises(self):
        with pytest.raises((ValueError, Exception)):
            await mcp_get_summary(url="not-a-url")
