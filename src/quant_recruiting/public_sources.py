"""Conservative normalizers for public discussion, video, and GitHub data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    text: str


def youtube_video_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and parsed.hostname.endswith("youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        match = re.match(r"/(?:shorts|embed)/([^/]+)", parsed.path)
        return match.group(1) if match else None
    return None


def normalize_youtube_metadata(payload: dict[str, Any], url: str) -> dict[str, Any]:
    return {
        "video_id": youtube_video_id(url),
        "url": url,
        "title": payload.get("title"),
        "channel": payload.get("author_name") or payload.get("channel"),
        "description": payload.get("description"),
        "published_at": payload.get("published_at"),
        "duration_seconds": payload.get("duration_seconds"),
        "thumbnail_url": payload.get("thumbnail_url"),
        "transcript_available": bool(payload.get("transcript")),
    }


def normalize_transcript(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        start = float(segment.get("start", 0))
        minutes, seconds = divmod(int(start), 60)
        hours, minutes = divmod(minutes, 60)
        timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        text = " ".join(str(segment.get("text", "")).split())
        if text:
            lines.extend([f"## {timestamp}", text, ""])
    return "\n".join(lines).strip() + "\n"


def normalize_reddit_payload(payload: dict[str, Any], *, max_comments: int = 10) -> dict[str, Any]:
    post = payload.get("post", payload)
    comments = payload.get("comments", [])
    return {
        "url": post.get("url") or post.get("permalink"),
        "subreddit": post.get("subreddit") or post.get("community"),
        "title": post.get("title"),
        "created_at": post.get("created_utc") or post.get("created_at"),
        "author": post.get("author"),
        "body": post.get("selftext") or post.get("body") or "",
        "score": post.get("score"),
        "comments": [
            {
                "author": item.get("author"),
                "body": item.get("body", ""),
                "score": item.get("score"),
            }
            for item in comments[:max_comments]
            if isinstance(item, dict)
        ],
        "claim_type_default": "anecdote",
        "source_quality_default": "low",
    }


def normalize_github_payload(
    payload: dict[str, Any], url: str, readme: str | None = None
) -> dict[str, Any]:
    owner_value = payload.get("owner")
    owner: dict[str, Any] = owner_value if isinstance(owner_value, dict) else {}
    return {
        "url": url,
        "owner": owner.get("login"),
        "repo": payload.get("name"),
        "description": payload.get("description"),
        "readme": readme,
        "topics": payload.get("topics", []),
        "primary_language": payload.get("language"),
        "stars": payload.get("stargazers_count"),
        "forks": payload.get("forks_count"),
        "updated_at": payload.get("updated_at"),
        "license": (payload.get("license") or {}).get("spdx_id")
        if isinstance(payload.get("license"), dict)
        else None,
        "official_ownership": "unverified",
    }
