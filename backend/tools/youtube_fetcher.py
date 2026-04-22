"""
YouTube Data API v3 + transcript fetcher.
Used by the CorpusBuilderAgent to collect documentary data.
"""

import asyncio
import re
from typing import Optional

import requests
import structlog
from googleapiclient.discovery import build

from backend.config import settings

log = structlog.get_logger(__name__)

_SUPADATA_TRANSCRIPT_URL = "https://api.supadata.ai/v1/youtube/transcript"

# Short-form docs (BI, CNBC Make It) can be 3–60 minutes
_MIN_DURATION_SECONDS = 180
_MAX_DURATION_SECONDS = 3600


def _parse_iso_duration(duration: str) -> int:
    """Convert ISO 8601 duration string (e.g. PT10M30S) to total seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _fetch_transcript_sync(video_id: str, retries: int = 3) -> Optional[str]:
    """Fetch transcript from Supadata.ai transcript API with retry on 429."""
    import time

    api_key = settings.supadata_api_key
    if not api_key:
        log.warning("youtube_fetcher.supadata_key_missing", video_id=video_id)
        return None

    delay = 10.0
    for attempt in range(retries):
        try:
            resp = requests.get(
                _SUPADATA_TRANSCRIPT_URL,
                params={"videoId": video_id, "lang": "en"},
                headers={"x-api-key": api_key},
                timeout=30,
            )
        except requests.RequestException as exc:
            log.warning("youtube_fetcher.request_error", video_id=video_id, error=str(exc))
            return None

        if resp.status_code == 404:
            return None

        if resp.status_code == 429:
            if attempt < retries - 1:
                log.warning("youtube_fetcher.rate_limited", video_id=video_id, retry_in=delay)
                time.sleep(delay)
                delay *= 2
                continue
            log.warning("youtube_fetcher.transcript_error", video_id=video_id, status=429)
            return None

        if resp.status_code != 200:
            log.warning("youtube_fetcher.transcript_error", video_id=video_id, status=resp.status_code)
            return None

        data = resp.json()
        segments = data.get("content", [])
        if not segments:
            return None

        return " ".join(s["text"] for s in segments if s.get("text", "").strip())

    return None


class YouTubeFetcher:
    """
    Wraps the YouTube Data API v3 and Supadata.ai for transcript extraction.

    Example::

        fetcher = YouTubeFetcher()
        videos = await fetcher.get_channel_videos(max_results=30)
        transcript = await fetcher.get_transcript(videos[0]["id"])
    """

    def __init__(self) -> None:
        if not settings.youtube_api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not set in environment")
        self._service = build("youtube", "v3", developerKey=settings.youtube_api_key)

    def _resolve_channel_id_sync(self, identifier: str) -> str:
        if not identifier.startswith("@"):
            return identifier

        handle = identifier.lstrip("@")
        resp = self._service.channels().list(part="id", forHandle=handle).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Could not resolve YouTube handle '{identifier}' to a channel ID")
        return items[0]["id"]

    async def resolve_channel_identifier(self, identifier: str) -> str:
        if not identifier.startswith("@"):
            return identifier
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._resolve_channel_id_sync, identifier)

    def _get_uploads_playlist_id_sync(self, channel_id: str) -> str:
        resp = self._service.channels().list(
            part="contentDetails", id=channel_id
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    async def get_channel_videos(
        self,
        channel_id: Optional[str] = None,
        max_results: int = 50,
        order: str = "viewCount",
    ) -> list[dict]:
        """
        Fetch video metadata from a channel's uploads playlist, filtered to
        documentary-length content and sorted by the requested order.
        Uses the uploads playlist (not search) to access all videos, not just top-50.
        """
        if order not in {"viewCount", "date"}:
            raise ValueError("YouTube video order must be 'viewCount' or 'date'")

        raw_identifier = channel_id or settings.bi_channel_id
        channel_id = await self.resolve_channel_identifier(raw_identifier)
        loop = asyncio.get_event_loop()
        playlist_id = await loop.run_in_executor(
            None, self._get_uploads_playlist_id_sync, channel_id
        )

        def _fetch() -> list[dict]:
            candidates: list[dict] = []
            page_token: Optional[str] = None
            # Scan up to 500 recent uploads to find enough qualifying videos
            scan_limit = max(500, max_results * 10)

            while len(candidates) < scan_limit:
                playlist_resp = self._service.playlistItems().list(
                    part="contentDetails",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                ).execute()

                video_ids = [
                    item["contentDetails"]["videoId"]
                    for item in playlist_resp.get("items", [])
                ]
                if not video_ids:
                    break

                details_resp = self._service.videos().list(
                    part="contentDetails,statistics,snippet",
                    id=",".join(video_ids),
                ).execute()

                for item in details_resp.get("items", []):
                    duration = _parse_iso_duration(item["contentDetails"]["duration"])
                    if not (_MIN_DURATION_SECONDS <= duration <= _MAX_DURATION_SECONDS):
                        continue
                    candidates.append({
                        "id": item["id"],
                        "title": item["snippet"]["title"],
                        "description": item["snippet"].get("description", ""),
                        "published_at": item["snippet"].get("publishedAt"),
                        "view_count": int(item["statistics"].get("viewCount", 0)),
                        "like_count": int(item["statistics"].get("likeCount", 0)),
                        "duration_seconds": duration,
                    })

                page_token = playlist_resp.get("nextPageToken")
                if not page_token:
                    break

            if order == "viewCount":
                candidates.sort(key=lambda v: v["view_count"], reverse=True)
            return candidates[:max_results]

        log.info("youtube_fetcher.get_videos.start", channel_id=channel_id, order=order)
        videos = await loop.run_in_executor(None, _fetch)
        log.info("youtube_fetcher.get_videos.complete", count=len(videos), order=order)
        return videos

    async def get_transcript(self, video_id: str) -> Optional[str]:
        """Fetch the English transcript for a YouTube video via Supadata."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_transcript_sync, video_id)

    async def get_transcripts_batch(
        self, video_ids: list[str], concurrency: int = 1
    ) -> dict[str, Optional[str]]:
        """Fetch transcripts sequentially with a short delay to respect rate limits."""
        results: dict[str, Optional[str]] = {}
        for vid in video_ids:
            try:
                results[vid] = await self.get_transcript(vid)
            except Exception:
                results[vid] = None
            await asyncio.sleep(3.0)
        return results
