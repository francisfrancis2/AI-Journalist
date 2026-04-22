"""
YouTube Data API v3 + transcript fetcher.
Used by the CorpusBuilderAgent to collect documentary data.
"""

import asyncio
import http.cookiejar
import os
import re
import tempfile
from typing import Optional

import requests
import structlog
from googleapiclient.discovery import build

from backend.config import settings

log = structlog.get_logger(__name__)

# Documentaries are typically 5–60 minutes long
_MIN_DURATION_SECONDS = 300
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


def _resolve_cookies_path() -> Optional[str]:
    """Return a usable cookies file path, writing inline content to a temp file if needed."""
    path = settings.youtube_cookies_path
    if path and os.path.exists(path):
        return path

    content = settings.youtube_cookies_content
    if content:
        # Write inline content to a temp file so MozillaCookieJar can load it.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="yt_cookies_", delete=False
        )
        tmp.write(content)
        tmp.flush()
        tmp.close()
        log.info("youtube_fetcher.cookies_written_from_env", path=tmp.name)
        return tmp.name

    return None


def _build_http_session() -> requests.Session:
    """Build a requests.Session with YouTube cookies if configured."""
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    cookies_path = _resolve_cookies_path()
    if cookies_path:
        jar = http.cookiejar.MozillaCookieJar(cookies_path)
        try:
            jar.load()
            session.cookies = jar
            log.info("youtube_fetcher.cookies_loaded", path=cookies_path)
        except Exception as exc:
            log.warning("youtube_fetcher.cookies_load_failed", path=cookies_path, error=str(exc))
    return session


def _fetch_transcript_sync(video_id: str, session: requests.Session) -> Optional[str]:
    """Fetch transcript using youtube-transcript-api v1.x with cookie session."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import IpBlocked, NoTranscriptFound, TranscriptsDisabled

    try:
        api = YouTubeTranscriptApi(http_client=session)
        transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(s.text for s in transcript.snippets)
    except IpBlocked:
        log.warning(
            "youtube_fetcher.ip_blocked",
            video_id=video_id,
            hint="IP is blocked by YouTube. Run corpus build from Fly.io or wait for the ban to expire.",
        )
        raise
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception as exc:
        log.warning("youtube_fetcher.transcript_error", video_id=video_id, error=str(exc)[:200])
        return None


class YouTubeFetcher:
    """
    Wraps the YouTube Data API v3 and youtube-transcript-api v1.x.

    Example::

        fetcher = YouTubeFetcher()
        videos = await fetcher.get_channel_videos(max_results=30)
        transcript = await fetcher.get_transcript(videos[0]["id"])
    """

    def __init__(self) -> None:
        if not settings.youtube_api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not set in environment")
        self._service = build("youtube", "v3", developerKey=settings.youtube_api_key)
        self._session = _build_http_session()

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

    async def get_channel_videos(
        self,
        channel_id: Optional[str] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Fetch video metadata from a channel, filtered to documentary-length content.
        Returns videos ordered by view count (most successful first).
        """
        raw_identifier = channel_id or settings.bi_channel_id
        channel_id = await self.resolve_channel_identifier(raw_identifier)
        loop = asyncio.get_event_loop()

        def _fetch() -> list[dict]:
            results: list[dict] = []
            page_token: Optional[str] = None

            while len(results) < max_results:
                search_resp = self._service.search().list(
                    part="id,snippet",
                    channelId=channel_id,
                    type="video",
                    maxResults=50,
                    pageToken=page_token,
                    order="viewCount",
                ).execute()

                video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
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
        Returns None on unavailable transcripts; raises IpBlocked if the IP is banned.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _fetch_transcript_sync, video_id, self._session
        )

    async def get_transcripts_batch(
        self, video_ids: list[str], concurrency: int = 1
    ) -> dict[str, Optional[str]]:
        """Fetch transcripts sequentially with a delay to avoid rate limits."""
        results: dict[str, Optional[str]] = {}
        for vid in video_ids:
            try:
                results[vid] = await self.get_transcript(vid)
            except Exception:
                results[vid] = None
            await asyncio.sleep(2.0)
        return results
