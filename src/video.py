import re
from urllib.parse import urlparse, parse_qs
from datetime import timedelta
import json
from typing import Any, Optional, Dict, List

from .utils import (
    fetch_url,
    get_thumbnail_urls,
    parse_duration_to_seconds,
    parse_iso8601_date,
    parse_view_count,
)

INNERTUBE_PAYLOAD_BASE: dict[str, Any] = {
    "context": {
        "client": {
            "clientName": "WEB",
            "clientVersion": "2.20220502.01.00",
            "hl": "en",
        }
    }
}

INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"


def is_valid_video_id(video_id: str) -> bool:
    """Check if a string is a valid YouTube video ID"""
    if not video_id:
        return False
    return re.match(r"^[A-Za-z0-9_-]{11}$", video_id) is not None


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube video ID from URL or return ID if already provided"""
    if not url_or_id or is_valid_video_id(url_or_id):
        return url_or_id

    parsed_url = urlparse(url_or_id)

    if "youtube.com" in parsed_url.netloc:
        if "watch" in parsed_url.path:
            video_id = parse_qs(parsed_url.query).get("v", [None])[0]
            return video_id if video_id and is_valid_video_id(video_id) else None
        if "embed" in parsed_url.path:
            path_parts = parsed_url.path.split("/")
            video_id = path_parts[2] if len(path_parts) > 2 else None
            return video_id if video_id and is_valid_video_id(video_id) else None
        if "shorts" in parsed_url.path:
            path_parts = parsed_url.path.split("/")
            video_id = path_parts[2] if len(path_parts) > 2 else None
            return video_id if video_id and is_valid_video_id(video_id) else None
    elif "youtu.be" in parsed_url.netloc:
        path_parts = parsed_url.path.split("/")
        video_id = path_parts[1] if len(path_parts) > 1 else None
        return video_id if video_id and is_valid_video_id(video_id) else None

    return None


def get_video_info(url_or_id: str, timeout: int = 5) -> Dict[str, Any]:
    """Get video information using YouTube's InnerTube API without an API key"""
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"error": "Invalid YouTube video ID or URL"}

    video_info = {
        "video_id": video_id,
        "thumbnails": get_thumbnail_urls(video_id),
    }

    inner_tube_payload = INNERTUBE_PAYLOAD_BASE.copy()
    inner_tube_payload["videoId"] = video_id

    try:
        player_url = (
            f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_API_KEY}"
        )
        player_data = fetch_url(
            player_url, method="POST", json_data=inner_tube_payload, timeout=timeout
        )

        if player_data:
            player_response = json.loads(player_data)

            video_details = player_response.get("videoDetails", {})
            microformat = player_response.get("microformat", {}).get(
                "playerMicroformatRenderer", {}
            )

            if video_details:
                length_seconds = int(video_details.get("lengthSeconds", 0))
                views_count = None
                if "viewCount" in video_details:
                    try:
                        views_count = int(video_details["viewCount"])
                    except (ValueError, TypeError):
                        pass

                video_info.update(
                    {
                        "video_id": video_details.get("videoId"),
                        "title": video_details.get("title"),
                        "duration": (
                            str(timedelta(seconds=length_seconds))
                            if length_seconds
                            else None
                        ),
                        "duration_seconds": length_seconds,
                        "views_count": views_count,
                        "description": video_details.get("shortDescription"),
                        "channel_id": video_details.get("channelId"),
                        "author_name": video_details.get("author"),
                        "is_live": bool(video_details.get("isLiveContent", False)),
                        "is_private": bool(video_details.get("isPrivate", False)),
                        "keywords": video_details.get("keywords", []),
                    }
                )

            if microformat:
                likes_count = None
                if "likeCount" in microformat:
                    likes_count = parse_view_count(microformat["likeCount"])

                publish_date = parse_iso8601_date(microformat.get("publishDate"))
                upload_date = parse_iso8601_date(microformat.get("uploadDate"))

                video_info.update(
                    {
                        "publish_date_text": microformat.get("publishDate"),
                        "publish_date": publish_date,
                        "upload_date_text": microformat.get("uploadDate"),
                        "upload_date": upload_date,
                        "category": microformat.get("category"),
                        "family_friendly": bool(microformat.get("isFamilySafe", False)),
                        "available_countries": microformat.get(
                            "availableCountries", []
                        ),
                        "owner_channel_name": microformat.get("ownerChannelName"),
                        "likes_count": likes_count,
                    }
                )

            chapters = []
            if "endscreen" in player_response and "elements" in player_response.get(
                "endscreen", {}
            ).get("endscreenRenderer", {}):
                for element in (
                    player_response.get("endscreen", {})
                    .get("endscreenRenderer", {})
                    .get("elements", [])
                ):
                    element_renderer = element.get("endscreenElementRenderer", {})
                    if element_renderer.get("style") == "VIDEO":
                        title = element_renderer.get("title", {}).get("simpleText", "")
                        try:
                            start_ms = int(element_renderer.get("startMs", 0))
                            start_seconds = start_ms / 1000
                            start_time_formatted = str(
                                timedelta(seconds=int(start_seconds))
                            )
                            chapters.append(
                                {
                                    "title": title,
                                    "time_start_seconds": start_seconds,
                                    "time_start_formatted": start_time_formatted,
                                }
                            )
                        except (ValueError, TypeError):
                            pass

            if chapters:
                video_info["chapters"] = chapters

            if "streamingData" in player_response:
                formats = []
                for fmt in player_response.get("streamingData", {}).get("formats", []):
                    format_data = {
                        "itag": fmt.get("itag"),
                        "url": fmt.get("url"),
                        "mimeType": fmt.get("mimeType", ""),
                        "width": int(fmt.get("width", 0)) if fmt.get("width") else None,
                        "height": (
                            int(fmt.get("height", 0)) if fmt.get("height") else None
                        ),
                        "quality": fmt.get("quality"),
                        "qualityLabel": fmt.get("qualityLabel"),
                    }

                    if "bitrate" in fmt:
                        try:
                            format_data["bitrate"] = int(fmt["bitrate"])
                        except (ValueError, TypeError):
                            format_data["bitrate"] = None

                    if "contentLength" in fmt:
                        try:
                            format_data["content_length"] = int(fmt["contentLength"])
                        except (ValueError, TypeError):
                            format_data["content_length"] = None

                    if "approxDurationMs" in fmt:
                        try:
                            duration_ms = int(fmt["approxDurationMs"])
                            format_data["duration_seconds"] = duration_ms / 1000
                        except (ValueError, TypeError):
                            format_data["duration_seconds"] = None

                    formats.append(format_data)

                if formats:
                    video_info["formats"] = formats
    except Exception as e:
        video_info["error"] = f"Error fetching video information: {str(e)}"

    return video_info


def get_video_info_oembed(url_or_id: str, timeout: int = 5) -> Dict[str, Any]:
    """Alternative function to get video info using YouTube's API endpoints without API key"""
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"error": "Invalid YouTube video ID or URL"}

    video_info = {
        "video_id": video_id,
        "thumbnails": get_thumbnail_urls(video_id),
    }

    try:
        oembed_url = (
            "https://www.youtube.com/oembed?url="
            f"http://www.youtube.com/watch?v={video_id}&format=json"
        )
        oembed_data = fetch_url(oembed_url, timeout=timeout)
        if oembed_data:
            oembed_response = json.loads(oembed_data)
            for key in ["title", "author_name", "author_url"]:
                if key not in video_info or not video_info[key]:
                    if key in oembed_response:
                        video_info[key] = oembed_response[key]
    except Exception:
        pass

    return video_info


def get_related_videos(url_or_id: str, timeout: int = 5) -> List[Dict[str, Any]]:
    """Get related videos for a YouTube video"""
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"error": "Invalid YouTube video ID or URL"}

    inner_tube_payload = INNERTUBE_PAYLOAD_BASE.copy()
    inner_tube_payload["videoId"] = video_id

    related_videos = []
    try:
        next_url = f"https://www.youtube.com/youtubei/v1/next?key={INNERTUBE_API_KEY}"
        next_data = fetch_url(
            next_url, method="POST", json_data=inner_tube_payload, timeout=timeout
        )
        if next_data:
            next_response = json.loads(next_data)

            secondary_results = (
                next_response.get("contents", {})
                .get("twoColumnWatchNextResults", {})
                .get("secondaryResults", {})
            )

            if secondary_results:
                items = secondary_results.get("secondaryResults", {}).get("results", [])
                for item in items:
                    compact_video = item.get("compactVideoRenderer", {})
                    if not compact_video:
                        continue

                    rel_video_id = compact_video.get("videoId")
                    if not rel_video_id:
                        continue

                    title = ""
                    title_runs = compact_video.get("title", {}).get("runs", [])
                    if title_runs:
                        title = "".join([run.get("text", "") for run in title_runs])
                    else:
                        title = compact_video.get("title", {}).get("simpleText", "")

                    length_text = compact_video.get("lengthText", {}).get(
                        "simpleText", ""
                    )
                    length_seconds = parse_duration_to_seconds(length_text)

                    channel = ""
                    byline = compact_video.get("longBylineText", {}).get("runs", [])
                    if byline:
                        channel = byline[0].get("text", "")

                    views_text = compact_video.get("viewCountText", {}).get(
                        "simpleText", ""
                    )
                    views_count = parse_view_count(views_text)

                    thumbnail_url = ""
                    thumbnails = compact_video.get("thumbnail", {}).get(
                        "thumbnails", []
                    )
                    if thumbnails:
                        thumbnail_url = thumbnails[-1].get("url", "")

                    related_videos.append(
                        {
                            "video_id": rel_video_id,
                            "title": title,
                            "channel": channel,
                            "length_text": length_text,
                            "length": length_seconds,
                            "views_text": views_text,
                            "views": views_count,
                            "thumbnail_url": thumbnail_url
                            or f"https://i.ytimg.com/vi/{rel_video_id}/hqdefault.jpg",
                        }
                    )
    except Exception:
        pass

    return related_videos
