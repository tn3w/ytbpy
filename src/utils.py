import re
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import socket
from datetime import datetime
from typing import Optional


def get_thumbnail_urls(video_id):
    """Generate thumbnail URLs for a YouTube video"""
    base_url = f"https://img.youtube.com/vi/{video_id}"
    return {
        "default": {"url": f"{base_url}/default.jpg", "width": 120, "height": 90},
        "medium": {"url": f"{base_url}/mqdefault.jpg", "width": 320, "height": 180},
        "high": {"url": f"{base_url}/hqdefault.jpg", "width": 480, "height": 360},
        "standard": {"url": f"{base_url}/sddefault.jpg", "width": 640, "height": 480},
        "maxres": {
            "url": f"{base_url}/maxresdefault.jpg",
            "width": 1280,
            "height": 720,
        },
    }


def fetch_url(url, headers=None, timeout=5, method="GET", json_data=None):
    """Fetch content from a URL"""
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }

    try:
        data = None
        if json_data:
            data = json.dumps(json_data).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"

        req = Request(url, headers=headers, method=method, data=data)
        with urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (URLError, HTTPError, socket.timeout):
        return None


def extract_json_data(html_content, pattern):
    """Helper to extract JSON data using regex pattern"""
    if not html_content:
        return None

    match = re.search(pattern, html_content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def extract_initial_data(html_content):
    """Extract initial data from HTML content"""
    return extract_json_data(html_content, r"ytInitialData\s*=\s*({.+?});</script>")


def parse_duration_to_seconds(duration_text):
    """Parse duration text to seconds"""
    if not duration_text:
        return None

    parts = duration_text.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    if len(parts) == 2:
        minutes, seconds = int(parts[0]), int(parts[1])
        return minutes * 60 + seconds
    if len(parts) == 1:
        return int(parts[0])
    return None


def parse_iso8601_date(date_string: str) -> Optional[int]:
    """Parse ISO 8601 date to timestamp."""
    return int(datetime.fromisoformat(date_string).timestamp()) if date_string else None


def parse_view_count(view_count_text: str) -> Optional[int]:
    """Convert view count text like '1,072,836,095 views' to integer."""
    if not view_count_text:
        return None

    view_count_text = view_count_text.replace("views", "").strip()

    try:
        return int(view_count_text.replace(",", ""))
    except (ValueError, TypeError):
        return None
