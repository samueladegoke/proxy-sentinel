"""Pytest fixtures for yt-transcript-web tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


@dataclass 
class MockSnippet:
    """Mock transcript snippet matching FetchedTranscriptSnippet interface."""
    start: float
    duration: float
    text: str


class MockFetchedTranscript:
    """Mock fetched transcript that iterates over snippets."""
    def __init__(self, snippets):
        self._snippets = snippets
        self.language_code = "en"
        self.is_generated = False
    
    def __iter__(self):
        return iter(self._snippets)
    
    def to_raw_data(self):
        return [{"start": s.start, "duration": s.duration, "text": s.text} for s in self._snippets]


@pytest.fixture(autouse=True)
def mock_youtube_api():
    """Automatically mock YouTubeTranscriptApi for all tests."""
    mock_snippets = [
        MockSnippet(start=0.0, duration=5.0, text="Never gonna give you up"),
        MockSnippet(start=5.0, duration=5.0, text="Never gonna let you down"),
        MockSnippet(start=10.0, duration=5.0, text="Never gonna run around and desert you"),
    ]
    mock_transcript = MockFetchedTranscript(mock_snippets)
    
    mock_api = MagicMock()
    mock_api.fetch = MagicMock(return_value=mock_transcript)
    
    with patch("app.transcript_service.YouTubeTranscriptApi") as mock_class:
        mock_class.return_value = mock_api
        yield mock_api


@pytest.fixture
def mock_yt_api(mock_youtube_api):
    """Alias for mock_youtube_api.fetch for backward compatibility with tests."""
    return mock_youtube_api.fetch


@pytest.fixture
def mock_yt_api_empty():
    """Mock returning empty transcript."""
    mock_api = MagicMock()
    mock_api.fetch = MagicMock(return_value=MockFetchedTranscript([]))
    
    with patch("app.transcript_service.YouTubeTranscriptApi") as mock_class:
        mock_class.return_value = mock_api
        yield mock_api


@pytest.fixture
def sample_video_id():
    """Sample YouTube video ID for testing."""
    return "dQw4w9WgXcQ"


@pytest.fixture
def sample_transcript_segments():
    """Sample transcript segments for testing."""
    return [
        {"start": 0.0, "duration": 5.0, "text": "First segment of the video."},
        {"start": 5.0, "duration": 5.0, "text": "Second segment of the video."},
        {"start": 10.0, "duration": 5.0, "text": "Third segment of the video."},
    ]
