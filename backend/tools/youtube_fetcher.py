"""
YouTube Data API v3 + transcript fetcher.
Used by the CorpusBuilderAgent to collect Business Insider documentary data.
"""

import asyncio
import re
from typing import Optional

import structlog
from googleapiclient.discovery import build
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

from backend.config import settings

log = structlog.get_logger(__name__)

# BI documentaries are 5–20 minutes long
_MIN_DURATION_SECONDS = 300
_MAX_DURATION_SECONDS = 1200


def _parse_iso_duration(duration: str) -> int:
    """Convert ISO 8601 duration string (e.g. PT10M30S) to total seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeFetcher:
    """
    Wraps the YouTube Data API v3 and youtube-transcript-api.

    Example::

        fetcher = YouTubeFetcher()
        videos = await fetcher.get_channel_videos(max_results=30)
        transcript = await fetcher.get_transcript(videos[0]["id"])
    """

    def __init__(self) -> None:
        if not settings.youtube_api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not set in environment")
        # Build is synchronous — done once at init
        self._service = build("youtube", "v3", developerKey=settings.youtube_api_key)

    def _resolve_channel_id_sync(self, identifier: str) -> str:
        """
        Resolve a channel identifier to a channel ID.
        Handles both raw IDs (UC...) and @handles.
        Synchronous — call via run_in_executor.
        """
        if not identifier.startswith("@"):
            return identifier  # already a channel ID

        handle = identifier.lstrip("@")
        resp = self._service.channels().list(
            part="id",
            forHandle=handle,
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Could not resolve YouTube handle '{identifier}' to a channel ID")
        return items[0]["id"]

    async def resolve_channel_identifier(self, identifier: str) -> str:
        """Async wrapper around handle resolution."""
        if not identifier.startswith("@"):
            return identifier
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._resolve_channel_id_sync, identifier)

    async def get_channel_videos(
        self,
        channel_id: Optional[str] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Fetch video metadata from a channel, filtered to documentary-length content.
        Returns videos ordered by view count (most successful first).

        Args:
            channel_id: YouTube channel ID or @handle. Defaults to BI channel from config.
            max_results: Maximum number of qualifying videos to return.

        Returns:
            List of dicts with id, title, description, view_count, like_count, duration_seconds.
        """
        raw_identifier = channel_id or settings.bi_channel_id
        channel_id = await self.resolve_channel_identifier(raw_identifier)
        loop = asyncio.get_event_loop()

        def _fetch() -> list[dict]:
            results: list[dict] = []
            page_token: Optional[str] = None

            while len(results) < max_results:
                # Search for videos in the channel
                search_resp = self._service.search().list(
                    part="id,snippet",
                    channelId=channel_id,
                    type="video",
                    maxResults=50,
                    pageToken=page_token,
                    order="viewCount",
                ).execute()

                video_ids = [
                    item["id"]["videoId"]
                    for item in search_resp.get("items", [])
                ]
                if not video_ids:
                    break

                # Fetch full details including duration + statistics
                details_resp = self._service.videos().list(
                    part="contentDetails,statistics,snippet",
                    id=",".join(video_ids),
                ).execute()

                for item in details_resp.get("items", []):
                    duration = _parse_iso_duration(
                        item["contentDetails"]["duration"]
                    )
                    if not (_MIN_DURATION_SECONDS <= duration <= _MAX_DURATION_SECONDS):
                        continue
                    results.append({
                        "id": item["id"],
                        "title": item["snippet"]["title"],
                        "description": item["snippet"].get("description", ""),
                        "view_count": int(item["statistics"].get("viewCount", 0)),
                        "like_count": int(item["statistics"].get("likeCount", 0)),
                        "duration_seconds": duration,
                    })
                    if len(results) >= max_results:
                        break

                page_token = search_resp.get("nextPageToken")
                if not page_token:
                    break

            return results

        log.info("youtube_fetcher.get_videos.start", channel_id=channel_id)
        videos = await loop.run_in_executor(None, _fetch)
        log.info("youtube_fetcher.get_videos.complete", count=len(videos))
        return videos

    async def get_transcript(self, video_id: str) -> Optional[str]:
        """
        Fetch the English transcript for a YouTube video.

        Returns:
            Full transcript as a single string, or None if unavailable.
        """
        loop = asyncio.get_event_loop()

        def _fetch() -> Optional[str]:
            try:
                entries = YouTubeTranscriptApi.get_transcript(
                    video_id, languages=["en", "en-US", "en-GB"]
                )
                return " ".join(e["text"] for e in entries)
            except (TranscriptsDisabled, NoTranscriptFound):
                return None
            except Exception as exc:
                log.warning("youtube_fetcher.transcript_failed", video_id=video_id, error=str(exc))
                return None

        return await loop.run_in_executor(None, _fetch)

    async def get_transcripts_batch(
        self, video_ids: list[str], concurrency: int = 5
    ) -> dict[str, Optional[str]]:
        """Fetch transcripts for multiple videos with concurrency control."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch_one(vid: str) -> tuple[str, Optional[str]]:
            async with semaphore:
                transcript = await self.get_transcript(vid)
                return vid, transcript

        pairs = await asyncio.gather(*[_fetch_one(vid) for vid in video_ids])
        return dict(pairs)
