"""
YouTube Data API v3 + transcript fetcher.
Used by the CorpusBuilderAgent to collect documentary data.
"""

import asyncio
import os
import re
import tempfile
from typing import Optional

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
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="yt_cookies_", delete=False
        )
        tmp.write(content)
        tmp.flush()
        tmp.close()
        log.info("youtube_fetcher.cookies_written_from_env", path=tmp.name)
        return tmp.name

    return None


def _fetch_transcript_sync(video_id: str) -> Optional[str]:
    """Fetch transcript via yt-dlp subtitle extraction."""
    import yt_dlp

    cookies_path = _resolve_cookies_path()

    ydl_opts: dict = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "json3",
        "outtmpl": "%(id)s",
        "quiet": True,
        "no_warnings": True,
        "logger": _YtDlpLogger(),
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts["paths"] = {"home": tmpdir}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=True,
                )
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "subtitles" in msg or "no subtitles" in msg or "caption" in msg:
                return None
            log.warning("youtube_fetcher.transcript_error", video_id=video_id, error=str(exc)[:300])
            return None
        except Exception as exc:
            log.warning("youtube_fetcher.transcript_error", video_id=video_id, error=str(exc)[:300])
            return None

        # yt-dlp writes subtitle files; find and parse the first .json3 file
        for fname in os.listdir(tmpdir):
            if fname.endswith(".json3"):
                fpath = os.path.join(tmpdir, fname)
                try:
                    return _parse_json3_subtitles(fpath)
                except Exception as exc:
                    log.warning("youtube_fetcher.subtitle_parse_error", video_id=video_id, error=str(exc))
                    return None

        # Fall back to VTT if json3 wasn't written
        for fname in os.listdir(tmpdir):
            if fname.endswith(".vtt"):
                fpath = os.path.join(tmpdir, fname)
                try:
                    return _parse_vtt(fpath)
                except Exception as exc:
                    log.warning("youtube_fetcher.vtt_parse_error", video_id=video_id, error=str(exc))
                    return None

    return None


def _parse_json3_subtitles(path: str) -> str:
    """Extract plain text from a yt-dlp json3 subtitle file."""
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    parts = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = seg.get("utf8", "").strip()
            if text and text != "\n":
                parts.append(text)
    return " ".join(parts)


def _parse_vtt(path: str) -> str:
    """Extract plain text from a WebVTT subtitle file."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Strip VTT header, timestamps, and tags
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        # Remove inline tags like <00:00:00.000>, <c>, </c>
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)
    return " ".join(lines)


class _YtDlpLogger:
    def debug(self, msg: str) -> None:
        pass
    def warning(self, msg: str) -> None:
        log.debug("yt_dlp.warning", msg=msg)
    def error(self, msg: str) -> None:
        log.warning("yt_dlp.error", msg=msg)


class YouTubeFetcher:
    """
    Wraps the YouTube Data API v3 and yt-dlp for transcript extraction.

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
        Fetch the English transcript for a YouTube video via yt-dlp.
        Returns None if no subtitles are available.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_transcript_sync, video_id)

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
