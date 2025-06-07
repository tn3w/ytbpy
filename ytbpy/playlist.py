import re
import json
from urllib.parse import urlparse, parse_qs

from .utils import fetch_url, get_thumbnail_urls, extract_initial_data


def extract_playlist_id(url_or_id):
    """Extract playlist ID from YouTube URL or return ID if already provided"""
    if not url_or_id:
        return None

    if re.match(r"^[A-Za-z0-9_-]+$", url_or_id) and not "/" in url_or_id:
        return url_or_id

    try:
        parsed_url = urlparse(url_or_id)
        if "youtube.com" in parsed_url.netloc:
            query_params = parse_qs(parsed_url.query)
            if "list" in query_params:
                return query_params["list"][0]
    except Exception:
        pass

    return None


def _extract_playlist_metadata(initial_data):
    """Extract metadata about the playlist itself"""
    try:
        sidebar = initial_data.get("sidebar", {}).get("playlistSidebarRenderer", {})
        primary_info = sidebar.get("items", [])[0].get(
            "playlistSidebarPrimaryInfoRenderer", {}
        )

        playlist_info = {}

        title_runs = primary_info.get("title", {}).get("runs", [])
        if title_runs:
            playlist_info["title"] = "".join(run.get("text", "") for run in title_runs)

        stats = primary_info.get("stats", [])
        for stat in stats:
            if "runs" in stat:
                stat_text = "".join(run.get("text", "") for run in stat.get("runs", []))
                if "video" in stat_text.lower():
                    video_count_match = re.search(r"(\d+(?:,\d+)*)", stat_text)
                    if video_count_match:
                        playlist_info["video_count"] = int(
                            video_count_match.group(1).replace(",", "")
                        )
            elif "simpleText" in stat:
                stat_text = stat.get("simpleText", "")
                if "view" in stat_text.lower():
                    view_count_match = re.search(r"(\d+(?:,\d+)*)", stat_text)
                    if view_count_match:
                        playlist_info["view_count"] = int(
                            view_count_match.group(1).replace(",", "")
                        )
                elif "updated" in stat_text.lower() or "last" in stat_text.lower():
                    playlist_info["last_updated"] = stat_text

        description = primary_info.get("description", {}).get("runs", [])
        if description:
            playlist_info["description"] = "".join(
                run.get("text", "") for run in description
            )
        elif "simpleText" in primary_info.get("description", {}):
            playlist_info["description"] = primary_info["description"]["simpleText"]

        if "description" not in playlist_info or not playlist_info["description"]:
            header = initial_data.get("header", {}).get("playlistHeaderRenderer", {})
            if header:
                header_description = header.get("description", {})
                if "runs" in header_description:
                    playlist_info["description"] = "".join(
                        run.get("text", "") for run in header_description["runs"]
                    )
                elif "simpleText" in header_description:
                    playlist_info["description"] = header_description["simpleText"]

        if "description" not in playlist_info:
            playlist_info["description"] = ""

        privacy_status = primary_info.get("privacyText", {}).get("simpleText", "")
        if privacy_status:
            playlist_info["privacy"] = privacy_status

        playlist_thumbnails = (
            primary_info.get("thumbnailRenderer", {})
            .get("playlistVideoThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )
        if playlist_thumbnails:
            playlist_info["thumbnails"] = playlist_thumbnails

        owner_runs = (
            sidebar.get("items", [])[1]
            .get("playlistSidebarSecondaryInfoRenderer", {})
            .get("videoOwner", {})
            .get("videoOwnerRenderer", {})
            .get("title", {})
            .get("runs", [])
        )
        if owner_runs:
            playlist_info["owner"] = owner_runs[0].get("text", "")
            navigation_endpoint = owner_runs[0].get("navigationEndpoint", {})
            browse_id = navigation_endpoint.get("browseEndpoint", {}).get("browseId")
            if browse_id:
                playlist_info["owner_id"] = browse_id
                playlist_info["owner_url"] = (
                    f"https://www.youtube.com/channel/{browse_id}"
                )

        return playlist_info
    except Exception:
        return {}


def _extract_continuation_token_from_command_executor(endpoint):
    """Extract continuation token from commandExecutorCommand structure"""
    if "commandExecutorCommand" not in endpoint:
        return None

    try:
        commands = endpoint["commandExecutorCommand"].get("commands", [])
        for command in commands:
            if "continuationCommand" in command:
                return command["continuationCommand"].get("token")
    except Exception as e:
        print(f"Error extracting from commandExecutorCommand: {e}")

    return None


def _extract_continuation_token(initial_data):
    """Extract continuation token from playlist data"""
    try:
        contents = (
            initial_data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])[0]
            .get("itemSectionRenderer", {})
            .get("contents", [])[0]
            .get("playlistVideoListRenderer", {})
            .get("contents", [])
        )

        for item in contents:
            if "continuationItemRenderer" in item:
                continuation_renderer = item["continuationItemRenderer"]

                if "continuation" in continuation_renderer:
                    return continuation_renderer["continuation"]

                if "continuationEndpoint" in continuation_renderer:
                    endpoint = continuation_renderer["continuationEndpoint"]

                    executor_token = _extract_continuation_token_from_command_executor(
                        endpoint
                    )
                    if executor_token:
                        return executor_token

                    if "continuationCommand" in endpoint:
                        cmd = endpoint["continuationCommand"]
                        if isinstance(cmd, dict) and "token" in cmd:
                            return cmd["token"]

                    if "commandMetadata" in endpoint:
                        metadata = endpoint["commandMetadata"]
                        if "webCommandMetadata" in metadata:
                            web_cmd = metadata["webCommandMetadata"]
                            if "url" in web_cmd:
                                url = web_cmd["url"]
                                if "&continuation=" in url:
                                    return url.split("&continuation=")[1]

                    if "token" in endpoint:
                        return endpoint["token"]

                    if "browseEndpoint" in endpoint:
                        browse = endpoint["browseEndpoint"]
                        if "params" in browse:
                            return browse["params"]

        header = initial_data.get("header", {}).get("playlistHeaderRenderer", {})
        playlist_actions = header.get("playlistActions", [])
        for action in playlist_actions:
            if "menuAction" in action:
                menu_service = action.get("menuAction", {}).get(
                    "menuServiceItemRenderer", {}
                )
                command = menu_service.get("serviceEndpoint", {}).get(
                    "continuationCommand", {}
                )
                token = command.get("token")
                if token:
                    return token

        browse_contents = initial_data.get("contents", {}).get(
            "twoColumnBrowseResultsRenderer", {}
        )
        secondary_contents = browse_contents.get("secondaryContents", {})
        secondary_renderer = secondary_contents.get("secondaryContents", {})
        continuation_items = secondary_renderer.get("continuationItemRenderer", {})
        if continuation_items and "continuationEndpoint" in continuation_items:
            endpoint = continuation_items["continuationEndpoint"]
            if "continuationCommand" in endpoint:
                return endpoint["continuationCommand"].get("token")

        return None
    except Exception as e:
        print(f"Error extracting continuation token: {e}")
        return None


def _extract_playlist_videos(initial_data, max_results=50):
    """Extract videos from playlist initial data"""
    videos = []
    continuation_token = None

    try:
        playlist_contents = (
            initial_data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])[0]
            .get("itemSectionRenderer", {})
            .get("contents", [])[0]
            .get("playlistVideoListRenderer", {})
            .get("contents", [])
        )

        for item in playlist_contents:
            if "continuationItemRenderer" in item:
                continuation_renderer = item["continuationItemRenderer"]

                if "continuation" in continuation_renderer:
                    continuation_token = continuation_renderer["continuation"]
                    continue

                if "continuationEndpoint" in continuation_renderer:
                    endpoint = continuation_renderer["continuationEndpoint"]

                    executor_token = _extract_continuation_token_from_command_executor(
                        endpoint
                    )
                    if executor_token:
                        continuation_token = executor_token
                        continue

                    try:
                        if "continuationCommand" in endpoint:
                            cmd = endpoint["continuationCommand"]
                            if isinstance(cmd, dict) and "token" in cmd:
                                continuation_token = cmd["token"]
                                continue
                    except Exception:
                        pass

                    try:
                        if "commandMetadata" in endpoint:
                            metadata = endpoint["commandMetadata"]
                            if "webCommandMetadata" in metadata:
                                web_cmd = metadata["webCommandMetadata"]
                                if "url" in web_cmd:
                                    url = web_cmd["url"]
                                    if "&continuation=" in url:
                                        continuation_token = url.split(
                                            "&continuation="
                                        )[1]
                                        continue
                    except Exception:
                        pass

                    try:
                        if "token" in endpoint:
                            continuation_token = endpoint["token"]
                            continue
                    except Exception:
                        pass

                    try:
                        if "browseEndpoint" in endpoint:
                            browse = endpoint["browseEndpoint"]
                            if "params" in browse:
                                continuation_token = browse["params"]
                                continue
                    except Exception:
                        pass
                continue

            if len(videos) >= max_results:
                break

            video_renderer = item.get("playlistVideoRenderer", {})
            if not video_renderer:
                continue

            video_id = video_renderer.get("videoId")
            if not video_id:
                continue

            video_info = {
                "video_id": video_id,
                "thumbnails": get_thumbnail_urls(video_id),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "index": video_renderer.get("index", {}).get("simpleText", ""),
            }

            title_runs = video_renderer.get("title", {}).get("runs", [])
            if title_runs:
                video_info["title"] = "".join(run.get("text", "") for run in title_runs)

            length_text = video_renderer.get("lengthText", {}).get("simpleText", "")
            if length_text:
                video_info["duration"] = length_text
                time_parts = length_text.split(":")
                duration_seconds = 0
                if len(time_parts) == 3:
                    duration_seconds = (
                        int(time_parts[0]) * 3600
                        + int(time_parts[1]) * 60
                        + int(time_parts[2])
                    )
                elif len(time_parts) == 2:
                    duration_seconds = int(time_parts[0]) * 60 + int(time_parts[1])
                elif len(time_parts) == 1:
                    duration_seconds = int(time_parts[0])
                video_info["duration_seconds"] = duration_seconds

            video_meta_text = []

            video_info_runs = video_renderer.get("videoInfo", {}).get("runs", [])
            if video_info_runs:
                video_meta_text.append(
                    "".join(run.get("text", "") for run in video_info_runs)
                )

            byline_text = video_renderer.get("byline", {}).get("simpleText", "")
            if byline_text:
                video_meta_text.append(byline_text)

            accessibility_label = (
                video_renderer.get("accessibility", {})
                .get("accessibilityData", {})
                .get("label", "")
            )
            if accessibility_label:
                video_meta_text.append(accessibility_label)

            for meta_text in video_meta_text:
                view_match = re.search(r"(\d+(?:,\d+)*)\s+views?", meta_text)
                if view_match and "view_count" not in video_info:
                    video_info["view_count"] = int(view_match.group(1).replace(",", ""))

                relative_match = re.search(r"(\d+\s+\w+\s+ago)", meta_text)
                if relative_match and "published_date" not in video_info:
                    video_info["published_date"] = relative_match.group(1)

            description_snippet = video_renderer.get("descriptionSnippet", {})
            if description_snippet:
                if "simpleText" in description_snippet:
                    video_info["description"] = description_snippet["simpleText"]
                elif "runs" in description_snippet:
                    video_info["description"] = "".join(
                        run.get("text", "") for run in description_snippet["runs"]
                    )

            badges = video_renderer.get("badges", [])
            if badges:
                badge_labels = []
                for badge in badges:
                    if "metadataBadgeRenderer" in badge:
                        label = badge["metadataBadgeRenderer"].get("label", "")
                        if label:
                            badge_labels.append(label)
                if badge_labels:
                    video_info["badges"] = badge_labels

            short_byline_text = video_renderer.get("shortBylineText", {}).get(
                "runs", []
            )
            if short_byline_text:
                video_info["channel_name"] = short_byline_text[0].get("text", "")
                navigation_endpoint = short_byline_text[0].get("navigationEndpoint", {})
                browse_id = navigation_endpoint.get("browseEndpoint", {}).get(
                    "browseId"
                )
                if browse_id:
                    video_info["channel_id"] = browse_id
                    video_info["channel_url"] = (
                        f"https://www.youtube.com/channel/{browse_id}"
                    )

            videos.append(video_info)
    except Exception as e:
        print(f"Error extracting playlist videos: {e}")

    if continuation_token is None and len(videos) < max_results:
        continuation_token = _extract_continuation_token(initial_data)

    return videos, continuation_token


def _fetch_continuation_page(continuation_token, timeout=10, debug=False):
    """Fetch the next page of playlist videos using the continuation token"""
    if not continuation_token:
        return [], None

    continuation_url = "https://www.youtube.com/youtubei/v1/browse?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

    headers = {
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": "2.20200720.00.00",
        "Content-Type": "application/json",
    }

    data = {
        "context": {
            "client": {"clientName": "WEB", "clientVersion": "2.20200720.00.00"}
        },
        "continuation": continuation_token,
    }

    response = fetch_url(
        continuation_url,
        timeout=timeout,
        method="POST",
        headers=headers,
        json_data=data,
    )

    if not response:
        return [], None

    try:
        response_data = json.loads(response)

        continuation_items = None
        next_continuation = None

        if (
            "onResponseReceivedActions" in response_data
            and response_data["onResponseReceivedActions"]
        ):
            first_action = response_data["onResponseReceivedActions"][0]
            if "appendContinuationItemsAction" in first_action:
                continuation_items = first_action["appendContinuationItemsAction"].get(
                    "continuationItems", []
                )

                for item in continuation_items:
                    if "continuationItemRenderer" in item:
                        if "continuationEndpoint" in item["continuationItemRenderer"]:
                            endpoint = item["continuationItemRenderer"][
                                "continuationEndpoint"
                            ]
                            token = _extract_continuation_token_from_command_executor(
                                endpoint
                            )
                            if token:
                                next_continuation = token
                            elif "continuationCommand" in endpoint:
                                next_continuation = endpoint["continuationCommand"].get(
                                    "token"
                                )

                if continuation_items and not next_continuation and debug:
                    print("Found items but no continuation token - likely last page")

        if not continuation_items:
            return [], None

        videos = []

        for item in continuation_items:
            if "continuationItemRenderer" in item:
                continue

            video_renderer = item.get("playlistVideoRenderer", {})
            if not video_renderer:
                continue

            video_id = video_renderer.get("videoId")
            if not video_id:
                continue

            video_info = {
                "video_id": video_id,
                "thumbnails": get_thumbnail_urls(video_id),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "index": video_renderer.get("index", {}).get("simpleText", ""),
            }

            title_runs = video_renderer.get("title", {}).get("runs", [])
            if title_runs:
                video_info["title"] = "".join(run.get("text", "") for run in title_runs)

            length_text = video_renderer.get("lengthText", {}).get("simpleText", "")
            if length_text:
                video_info["duration"] = length_text
                time_parts = length_text.split(":")
                duration_seconds = 0
                if len(time_parts) == 3:
                    duration_seconds = (
                        int(time_parts[0]) * 3600
                        + int(time_parts[1]) * 60
                        + int(time_parts[2])
                    )
                elif len(time_parts) == 2:
                    duration_seconds = int(time_parts[0]) * 60 + int(time_parts[1])
                elif len(time_parts) == 1:
                    duration_seconds = int(time_parts[0])
                video_info["duration_seconds"] = duration_seconds

            video_meta_text = []

            video_info_runs = video_renderer.get("videoInfo", {}).get("runs", [])
            if video_info_runs:
                video_meta_text.append(
                    "".join(run.get("text", "") for run in video_info_runs)
                )

            byline_text = video_renderer.get("byline", {}).get("simpleText", "")
            if byline_text:
                video_meta_text.append(byline_text)

            accessibility_label = (
                video_renderer.get("accessibility", {})
                .get("accessibilityData", {})
                .get("label", "")
            )
            if accessibility_label:
                video_meta_text.append(accessibility_label)

            for meta_text in video_meta_text:
                view_match = re.search(r"(\d+(?:,\d+)*)\s+views?", meta_text)
                if view_match and "view_count" not in video_info:
                    video_info["view_count"] = int(view_match.group(1).replace(",", ""))

                relative_match = re.search(r"(\d+\s+\w+\s+ago)", meta_text)
                if relative_match and "published_date" not in video_info:
                    video_info["published_date"] = relative_match.group(1)

            description_snippet = video_renderer.get("descriptionSnippet", {})
            if description_snippet:
                if "simpleText" in description_snippet:
                    video_info["description"] = description_snippet["simpleText"]
                elif "runs" in description_snippet:
                    video_info["description"] = "".join(
                        run.get("text", "") for run in description_snippet["runs"]
                    )

            badges = video_renderer.get("badges", [])
            if badges:
                badge_labels = []
                for badge in badges:
                    if "metadataBadgeRenderer" in badge:
                        label = badge["metadataBadgeRenderer"].get("label", "")
                        if label:
                            badge_labels.append(label)
                if badge_labels:
                    video_info["badges"] = badge_labels

            short_byline_text = video_renderer.get("shortBylineText", {}).get(
                "runs", []
            )
            if short_byline_text:
                video_info["channel_name"] = short_byline_text[0].get("text", "")
                navigation_endpoint = short_byline_text[0].get("navigationEndpoint", {})
                browse_id = navigation_endpoint.get("browseEndpoint", {}).get(
                    "browseId"
                )
                if browse_id:
                    video_info["channel_id"] = browse_id
                    video_info["channel_url"] = (
                        f"https://www.youtube.com/channel/{browse_id}"
                    )

            videos.append(video_info)

        return videos, next_continuation

    except Exception as e:
        print(f"Error parsing playlist continuation: {e}")
        return [], None


def get_playlist_info(url_or_id, max_results=50, timeout=10, debug=False):
    """Get information about a YouTube playlist and its videos with minimal requests

    Args:
        url_or_id: YouTube playlist URL or ID
        max_results: Maximum number of videos to retrieve
        timeout: Request timeout in seconds
        debug: Enable debug output for response structures

    Returns:
        Dictionary with playlist information and videos
    """
    playlist_id = extract_playlist_id(url_or_id)
    if not playlist_id:
        return {"error": "Invalid YouTube playlist ID or URL"}

    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    html_content = fetch_url(playlist_url, timeout=timeout)
    if not html_content:
        return {"error": "Failed to fetch playlist data"}

    initial_data = extract_initial_data(html_content)
    if not initial_data:
        return {"error": "Failed to extract playlist data"}

    playlist_info = {"playlist_id": playlist_id, "playlist_url": playlist_url}

    metadata = _extract_playlist_metadata(initial_data)
    playlist_info.update(metadata)

    videos, continuation_token = _extract_playlist_videos(initial_data, max_results)
    all_videos = videos.copy()
    page_count = 1

    if debug:
        print(
            f"First page: {len(videos)} videos, continuation token: {bool(continuation_token)}"
        )

    while continuation_token and len(all_videos) < max_results and page_count < 20:
        next_page_videos, next_continuation = _fetch_continuation_page(
            continuation_token, timeout, debug=debug
        )

        if not next_page_videos:
            if debug:
                print(f"No videos found on page {page_count + 1}")
            break

        if debug:
            print(
                f"Page {page_count + 1}: {len(next_page_videos)} videos, next token: {bool(next_continuation)}"
            )

        all_videos.extend(next_page_videos[: max_results - len(all_videos)])
        continuation_token = next_continuation
        page_count += 1

        if not continuation_token:
            break

    playlist_info["videos_count"] = len(all_videos)
    playlist_info["pages_fetched"] = page_count
    playlist_info["videos"] = all_videos[:max_results]

    if (
        "video_count" in playlist_info
        and playlist_info["video_count"] > playlist_info["videos_count"]
    ):
        playlist_info["total_videos"] = playlist_info["video_count"]
        if debug:
            print(
                f"Got {playlist_info['videos_count']} videos out of {playlist_info['video_count']} total"
            )

    return playlist_info
