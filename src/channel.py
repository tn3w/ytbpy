import re
import json
from urllib.parse import urlparse
from datetime import datetime, timedelta

from .utils import fetch_url, get_thumbnail_urls, extract_initial_data


def extract_channel_id_from_input(channel_input):
    """Extract a channel ID from various input formats (ID, username, handle, URL)"""
    if not channel_input:
        return None

    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_input):
        return channel_input

    try:
        parsed_url = urlparse(channel_input)
        if "youtube.com" in parsed_url.netloc:
            path_parts = parsed_url.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] == "channel":
                return path_parts[1]
    except Exception:
        pass

    return None


def _extract_text(data, default=""):
    """Helper to extract text from YouTube data structures"""
    if not data:
        return default

    if isinstance(data, str):
        return data

    if "simpleText" in data:
        return data.get("simpleText", default)

    if "runs" in data:
        return "".join(run.get("text", "") for run in data.get("runs", []))

    if "content" in data:
        return data.get("content", default)

    return default


def _extract_from_dynamic_text(dynamic_text, default=""):
    """Extract text from dynamic text view model"""
    if not dynamic_text:
        return default

    if "text" in dynamic_text and "content" in dynamic_text["text"]:
        return dynamic_text["text"]["content"]

    return default


def _parse_count(text):
    """Parse view/subscriber counts with K/M suffixes"""
    if not text or not isinstance(text, str):
        return 0

    match = re.search(r"([\d\.,]+)([MK]?)", text)
    if not match:
        return 0

    num, unit = match.groups()
    count = float(num.replace(",", ""))
    if unit == "M":
        count *= 1000000
    elif unit == "K":
        count *= 1000
    return int(count)


def _parse_duration(duration_text):
    """Parse duration text (e.g. "12:34") into seconds"""
    if not duration_text:
        return 0

    time_parts = duration_text.split(":")
    if len(time_parts) == 3:
        return int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
    elif len(time_parts) == 2:
        return int(time_parts[0]) * 60 + int(time_parts[1])
    elif len(time_parts) == 1:
        return int(time_parts[0])
    return 0


def _parse_time_ago(time_text):
    """Parse relative time (e.g. "3 weeks ago") into an approximate date"""
    if not time_text or "ago" not in time_text.lower():
        return None

    current_time = datetime.now()
    time_text = time_text.lower()

    number_match = re.search(r"(\d+)\s+(\w+)", time_text)
    if not number_match:
        return None

    number = int(number_match.group(1))
    unit = number_match.group(2).rstrip("s")

    time_units = {
        "second": timedelta(seconds=number),
        "sec": timedelta(seconds=number),
        "minute": timedelta(minutes=number),
        "min": timedelta(minutes=number),
        "hour": timedelta(hours=number),
        "hr": timedelta(hours=number),
        "day": timedelta(days=number),
        "week": timedelta(weeks=number),
        "wk": timedelta(weeks=number),
        "month": timedelta(days=number * 30),
        "mo": timedelta(days=number * 30),
        "year": timedelta(days=number * 365),
        "yr": timedelta(days=number * 365),
    }

    delta = time_units.get(unit)
    if delta:
        return (current_time - delta).strftime("%Y-%m-%d")
    return None


def _extract_video_info(video_renderer):
    """Extract video information from a video renderer object"""
    if not video_renderer:
        return None

    video_id = video_renderer.get("videoId", "")
    if not video_id:
        return None

    video_info = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnails": get_thumbnail_urls(video_id),
        "title": _extract_text(video_renderer.get("title", {})),
    }

    for overlay in video_renderer.get("thumbnailOverlays", []):
        time_renderer = overlay.get("thumbnailOverlayTimeStatusRenderer", {})
        if time_renderer:
            duration_text = _extract_text(time_renderer.get("text", {}))
            if duration_text:
                video_info["duration"] = duration_text
                video_info["duration_seconds"] = _parse_duration(duration_text)

        for key in [
            "thumbnailOverlayToggleButtonRenderer",
            "thumbnailOverlayNowPlayingRenderer",
        ]:
            if key in overlay:
                label = overlay.get(key, {}).get("label", "")
                if label:
                    video_info.setdefault("badges", []).append(label)

    published_time = _extract_text(video_renderer.get("publishedTimeText", {}))
    if published_time:
        video_info["published_time"] = published_time
        approx_date = _parse_time_ago(published_time)
        if approx_date:
            video_info["approximate_upload_date"] = approx_date

    view_count_text = _extract_text(video_renderer.get("viewCountText", {}))
    if view_count_text:
        video_info["view_count_text"] = view_count_text
        if "view" in view_count_text.lower():
            if view_count_text.lower().startswith("no "):
                video_info["views"] = 0
            else:
                video_info["views"] = _parse_count(view_count_text)

    description = video_renderer.get("descriptionSnippet", {})
    if description:
        video_info["description_snippet"] = _extract_text(description)

    for badge in video_renderer.get("badges", []):
        badge_label = badge.get("metadataBadgeRenderer", {}).get("label", "")
        if badge_label:
            video_info.setdefault("badges", []).append(badge_label)

    for badge in video_renderer.get("ownerBadges", []):
        if (
            badge.get("metadataBadgeRenderer", {}).get("style", "")
            == "BADGE_STYLE_TYPE_VERIFIED"
        ):
            video_info["channel_verified"] = True

    return video_info


def extract_channel_metadata(initial_data):
    """Extract metadata about the channel using the new YouTube data structure"""
    channel_info = {}

    try:
        page_header = initial_data.get("header", {}).get("pageHeaderRenderer", {})

        c4_header = initial_data.get("header", {}).get("c4TabbedHeaderRenderer", {})

        channel_metadata = initial_data.get("metadata", {}).get(
            "channelMetadataRenderer", {}
        )
        microformat = initial_data.get("microformat", {}).get(
            "microformatDataRenderer", {}
        )

        if channel_metadata and channel_metadata.get("description"):
            channel_info["description"] = channel_metadata.get("description", "")
        elif microformat and microformat.get("description"):
            channel_info["description"] = microformat.get("description", "")

        if page_header:
            page_header_view_model = page_header.get("content", {}).get(
                "pageHeaderViewModel", {}
            )

            dynamic_title = page_header_view_model.get("title", {}).get(
                "dynamicTextViewModel", {}
            )
            if (
                dynamic_title
                and "text" in dynamic_title
                and "content" in dynamic_title["text"]
            ):
                channel_info["title"] = dynamic_title["text"]["content"]
            else:
                channel_info["title"] = page_header.get("pageTitle", "")

            desc_view_model = page_header_view_model.get("description", {}).get(
                "descriptionPreviewViewModel", {}
            )
            if desc_view_model and "description" in desc_view_model:
                if not channel_info.get("description"):
                    channel_info["description"] = desc_view_model["description"].get(
                        "content", ""
                    )
                channel_info["description_snippet"] = desc_view_model[
                    "description"
                ].get("content", "")

            avatar_view_model = page_header_view_model.get("image", {}).get(
                "decoratedAvatarViewModel", {}
            )
            if avatar_view_model:
                avatar_sources = (
                    avatar_view_model.get("avatar", {})
                    .get("avatarViewModel", {})
                    .get("image", {})
                    .get("sources", [])
                )
                if avatar_sources:
                    channel_info["avatar_thumbnails"] = avatar_sources
                    channel_info["logo_url"] = avatar_sources[-1].get("url", "")

            banner_view_model = page_header_view_model.get("banner", {}).get(
                "imageBannerViewModel", {}
            )
            if banner_view_model and "image" in banner_view_model:
                banner_sources = banner_view_model["image"].get("sources", [])
                if banner_sources:
                    channel_info["banner_thumbnails"] = banner_sources
                    channel_info["banner_url"] = banner_sources[-1].get("url", "")

            metadata_rows = (
                page_header_view_model.get("metadata", {})
                .get("contentMetadataViewModel", {})
                .get("metadataRows", [])
            )

            for row in metadata_rows:
                if "metadataRowViewModel" in row:
                    row_model = row["metadataRowViewModel"]
                    title = _extract_text(row_model.get("title", {})).lower()
                    content = _extract_text(row_model.get("content", {}))

                    if not content:
                        continue

                    if "subscriber" in title or "sub" in title:
                        channel_info["subscriber_count_text"] = content
                        channel_info["subscriber_count_approximate"] = _parse_count(
                            content
                        )
                    elif "video" in title:
                        try:
                            channel_info["video_count"] = int(
                                re.search(r"([\d,]+)", content)
                                .group(1)
                                .replace(",", "")
                            )
                        except (AttributeError, ValueError):
                            pass
                    elif "view" in title:
                        try:
                            channel_info["view_count"] = int(
                                re.search(r"([\d,]+)", content)
                                .group(1)
                                .replace(",", "")
                            )
                        except (AttributeError, ValueError):
                            pass
                    elif "join" in title:
                        channel_info["joined_date"] = content
                    elif "location" in title or "country" in title:
                        channel_info["location"] = content

            try:
                attribution_vm = page_header_view_model.get("attribution", {}).get(
                    "attributionViewModel", {}
                )
                if attribution_vm and "text" in attribution_vm:
                    attribution_text = _extract_text(attribution_vm["text"])
                    handle_match = re.search(r"@([a-zA-Z0-9_.-]+)", attribution_text)
                    if handle_match:
                        handle_name = handle_match.group(1)
                        channel_info["handle_name"] = handle_name
                        channel_info["handle"] = f"@{handle_name}"
                        channel_info["vanity_url"] = (
                            f"https://www.youtube.com/@{handle_name}"
                        )
            except Exception:
                pass

        if c4_header and not channel_info.get("title"):
            channel_info["title"] = c4_header.get("title", "")

            vanity_channel = (
                c4_header.get("navigationEndpoint", {})
                .get("browseEndpoint", {})
                .get("canonicalBaseUrl", "")
            )
            if vanity_channel:
                channel_info["handle"] = vanity_channel
                if vanity_channel.startswith("/@"):
                    channel_info["handle_name"] = vanity_channel[2:]
                    channel_info["vanity_url"] = (
                        f"https://www.youtube.com{vanity_channel}"
                    )

            if c4_header.get("descriptionSnippet", {}).get("runs"):
                channel_info["description_snippet"] = "".join(
                    run.get("text", "")
                    for run in c4_header.get("descriptionSnippet", {}).get("runs", [])
                )

                if not channel_info.get("description"):
                    channel_info["description"] = channel_info["description_snippet"]

            if not channel_info.get("logo_url") and c4_header.get("avatar", {}).get(
                "thumbnails"
            ):
                channel_info["avatar_thumbnails"] = c4_header.get("avatar", {}).get(
                    "thumbnails", []
                )
                if channel_info["avatar_thumbnails"]:
                    channel_info["logo_url"] = channel_info["avatar_thumbnails"][
                        -1
                    ].get("url")

            if not channel_info.get("banner_url") and c4_header.get("banner", {}).get(
                "thumbnails"
            ):
                channel_info["banner_thumbnails"] = c4_header.get("banner", {}).get(
                    "thumbnails", []
                )
                if channel_info["banner_thumbnails"]:
                    channel_info["banner_url"] = channel_info["banner_thumbnails"][
                        -1
                    ].get("url")

            if not channel_info.get("subscriber_count_text"):
                subscriber_count_text = _extract_text(
                    c4_header.get("subscriberCountText", {})
                )
                if subscriber_count_text:
                    channel_info["subscriber_count_text"] = subscriber_count_text
                    channel_info["subscriber_count_approximate"] = _parse_count(
                        subscriber_count_text
                    )

                metadata_rows = (
                    c4_header.get("metadataRowContainer", {})
                    .get("metadataRowContainerRenderer", {})
                    .get("rows", [])
                )

                for row in metadata_rows:
                    row_renderer = row.get("metadataRowRenderer", {})
                    title = _extract_text(row_renderer.get("title", {})).lower()
                    contents = _extract_text(row_renderer.get("contents", [{}])[0])

                    if not contents:
                        continue

                    if "video" in title and not channel_info.get("video_count"):
                        try:
                            channel_info["video_count"] = int(
                                re.search(r"([\d,]+)", contents)
                                .group(1)
                                .replace(",", "")
                            )
                        except (AttributeError, ValueError):
                            pass
                    elif "view" in title and not channel_info.get("view_count"):
                        try:
                            channel_info["view_count"] = int(
                                re.search(r"([\d,]+)", contents)
                                .group(1)
                                .replace(",", "")
                            )
                        except (AttributeError, ValueError):
                            pass
                    elif "join" in title and not channel_info.get("joined_date"):
                        channel_info["joined_date"] = contents
                    elif "location" in title and not channel_info.get("location"):
                        channel_info["location"] = contents

        if channel_metadata:
            if not channel_info.get("title"):
                channel_info["title"] = channel_metadata.get("title", "")

            if not channel_info.get("logo_url") and channel_metadata.get(
                "avatar", {}
            ).get("thumbnails"):
                channel_info["avatar_thumbnails"] = channel_metadata.get(
                    "avatar", {}
                ).get("thumbnails", [])
                if channel_info["avatar_thumbnails"]:
                    channel_info["logo_url"] = channel_info["avatar_thumbnails"][
                        -1
                    ].get("url")

            if channel_metadata.get("vanityChannelUrl") and not channel_info.get(
                "vanity_url"
            ):
                vanity_url = channel_metadata.get("vanityChannelUrl")
                channel_info["vanity_url"] = vanity_url
                if "/@" in vanity_url:
                    handle_name = vanity_url.split("/@")[-1]
                    channel_info["handle_name"] = handle_name
                    channel_info["handle"] = f"@{handle_name}"

            if not channel_info.get("channel_id"):
                channel_info["channel_id"] = channel_metadata.get("externalId", "")

        for tab in (
            initial_data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])
        ):
            tab_renderer = tab.get("tabRenderer", {})
            if tab_renderer.get("title") == "About":
                sections = (
                    tab_renderer.get("content", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
                )
                for section in sections:
                    items = section.get("itemSectionRenderer", {}).get("contents", [])
                    for item in items:
                        about_renderer = item.get(
                            "channelAboutFullMetadataRenderer", {}
                        )
                        if about_renderer:
                            if not channel_info.get(
                                "description"
                            ) and about_renderer.get("description", {}).get(
                                "simpleText"
                            ):
                                channel_info["description"] = about_renderer.get(
                                    "description", {}
                                ).get("simpleText", "")

                            if (
                                not channel_info.get("video_count")
                                and "videoCountText" in about_renderer
                            ):
                                video_count_text = _extract_text(
                                    about_renderer.get("videoCountText", {})
                                )
                                video_count_match = re.search(
                                    r"([\d,]+)", video_count_text
                                )
                                if video_count_match:
                                    channel_info["video_count"] = int(
                                        video_count_match.group(1).replace(",", "")
                                    )

                            if (
                                not channel_info.get("view_count")
                                and "viewCountText" in about_renderer
                            ):
                                view_count_text = _extract_text(
                                    about_renderer.get("viewCountText", {})
                                )
                                view_count_match = re.search(
                                    r"([\d,]+)", view_count_text
                                )
                                if view_count_match:
                                    channel_info["view_count"] = int(
                                        view_count_match.group(1).replace(",", "")
                                    )

                            if (
                                not channel_info.get("joined_date")
                                and "joinedDateText" in about_renderer
                            ):
                                channel_info["joined_date"] = _extract_text(
                                    about_renderer.get("joinedDateText", {})
                                )

                            if (
                                not channel_info.get("location")
                                and "country" in about_renderer
                            ):
                                channel_info["location"] = _extract_text(
                                    about_renderer.get("country", {})
                                )

                            external_links = []
                            for link in about_renderer.get("primaryLinks", []):
                                title = _extract_text(link.get("title", {}))
                                url = (
                                    link.get("navigationEndpoint", {})
                                    .get("urlEndpoint", {})
                                    .get("url", "")
                                )
                                if title and url:
                                    external_links.append({"title": title, "url": url})

                            if external_links:
                                channel_info["external_links"] = external_links

                            if not channel_info.get(
                                "vanity_url"
                            ) and about_renderer.get("channelId"):
                                channel_id = about_renderer.get("channelId")
                                if channel_id:
                                    channel_info["channel_id"] = channel_id

                                    for link in about_renderer.get("primaryLinks", []):
                                        url = (
                                            link.get("navigationEndpoint", {})
                                            .get("urlEndpoint", {})
                                            .get("url", "")
                                        )
                                        if "youtube.com/" in url and "/@" in url:
                                            channel_info["vanity_url"] = url
                                            handle_name = url.split("/@")[-1].split(
                                                "?"
                                            )[0]
                                            channel_info["handle_name"] = handle_name
                                            channel_info["handle"] = f"@{handle_name}"
                                            break

        if "description" in channel_info and not channel_info.get(
            "description_snippet"
        ):
            channel_info["description_snippet"] = (
                channel_info["description"][:150] + "..."
                if len(channel_info["description"]) > 150
                else channel_info["description"]
            )

        return channel_info
    except Exception as e:
        return {"error": f"Error extracting channel metadata: {str(e)}"}


def extract_channel_videos(initial_data, max_videos=10):
    """Extract recent videos from the channel with detailed information"""
    videos = []

    try:
        tabs = (
            initial_data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])
        )

        for tab in tabs:
            tab_renderer = tab.get("tabRenderer", {})

            if tab_renderer.get("title") == "Videos":
                sections = (
                    tab_renderer.get("content", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
                )

                for section in sections:
                    item_section = section.get("itemSectionRenderer", {}).get(
                        "contents", []
                    )
                    for item in item_section:
                        grid_renderer = item.get("gridRenderer", {})
                        if not grid_renderer:
                            continue

                        items = grid_renderer.get("items", [])
                        for grid_item in items[:max_videos]:
                            video = _extract_video_info(
                                grid_item.get("gridVideoRenderer", {})
                            )
                            if video:
                                videos.append(video)

                if videos:
                    return videos

        for tab in tabs:
            tab_renderer = tab.get("tabRenderer", {})

            if tab_renderer.get("title") == "Home" and not videos:
                sections = (
                    tab_renderer.get("content", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
                )

                for section in sections:
                    item_section = section.get("itemSectionRenderer", {}).get(
                        "contents", []
                    )
                    for item in item_section:
                        shelf_renderer = item.get("shelfRenderer", {})
                        if shelf_renderer:
                            title_text = _extract_text(shelf_renderer.get("title", {}))
                            if any(
                                keyword in title_text
                                for keyword in ["Video", "Upload", "Recent"]
                            ):
                                content = shelf_renderer.get("content", {}).get(
                                    "horizontalListRenderer", {}
                                )
                                items = content.get("items", [])

                                for list_item in items[:max_videos]:
                                    video = _extract_video_info(
                                        list_item.get("gridVideoRenderer", {})
                                    )
                                    if video:
                                        videos.append(video)

        if not videos:
            sections = (
                initial_data.get("contents", {})
                .get("twoColumnBrowseResultsRenderer", {})
                .get("secondaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
            )

            for section in sections:
                if "itemSectionRenderer" in section:
                    items = section.get("itemSectionRenderer", {}).get("contents", [])
                    for item in items:
                        if "shelfRenderer" in item:
                            content = item.get("shelfRenderer", {}).get("content", {})
                            if "horizontalListRenderer" in content:
                                video_items = content.get(
                                    "horizontalListRenderer", {}
                                ).get("items", [])

                                for video_item in video_items[:max_videos]:
                                    video = _extract_video_info(
                                        video_item.get("gridVideoRenderer", {})
                                    )
                                    if video:
                                        videos.append(video)

    except Exception as e:
        return {"error": f"Error extracting channel videos: {str(e)}"}

    return videos


def get_channel_info(channel_input, include_videos=True, max_videos=10, timeout=10):
    """
    Get detailed information about a YouTube channel with minimal requests.

    Args:
        channel_input: Channel ID, username, handle or URL
        include_videos: Whether to include recent videos
        max_videos: Maximum number of videos to include
        timeout: Request timeout in seconds

    Returns:
        dict: Channel information including metadata and videos
    """
    channel_id = extract_channel_id_from_input(channel_input)

    if channel_id:
        url = f"https://www.youtube.com/channel/{channel_id}"
    elif channel_input.startswith("@"):
        url = f"https://www.youtube.com/{channel_input}"
    elif "/" not in channel_input:
        url = f"https://www.youtube.com/user/{channel_input}"
    else:
        url = channel_input

    html_content = fetch_url(url, timeout=timeout)
    if not html_content:
        return {"error": f"Failed to fetch channel data from {url}"}

    initial_data = extract_initial_data(html_content)
    if not initial_data:
        return {"error": "Failed to extract channel data"}

    def get_dict_structure(d):
        if not isinstance(d, dict):
            return type(d).__name__
        return {k: get_dict_structure(v) for k, v in d.items()}

    with open("initial_data_structure.json", "w") as f:
        json.dump(get_dict_structure(initial_data), f)

    if not channel_id:
        channel_id = initial_data.get("header", {}).get(
            "c4TabbedHeaderRenderer", {}
        ).get("channelId") or initial_data.get("metadata", {}).get(
            "channelMetadataRenderer", {}
        ).get(
            "externalId"
        )

    channel_info = {
        "channel_id": channel_id,
        "channel_url": (
            f"https://www.youtube.com/channel/{channel_id}" if channel_id else url
        ),
    }

    metadata = extract_channel_metadata(initial_data)
    if isinstance(metadata, dict):
        channel_info.update(metadata)

    if include_videos:
        videos = extract_channel_videos(initial_data, max_videos)
        if isinstance(videos, list):
            channel_info["videos_count"] = len(videos)
            channel_info["videos"] = videos

    return channel_info


def get_channel_videos(channel_input, max_results=50, timeout=10):
    """
    Get videos from a YouTube channel with minimal requests.

    Args:
        channel_input: Channel ID, username, handle or URL
        max_results: Maximum number of videos to include
        timeout: Request timeout in seconds

    Returns:
        dict: Channel videos information
    """
    channel_info = get_channel_info(
        channel_input, include_videos=True, max_videos=max_results, timeout=timeout
    )

    if "error" in channel_info:
        return channel_info

    return {
        "channel_id": channel_info.get("channel_id", ""),
        "channel_title": channel_info.get("title", ""),
        "videos_count": channel_info.get("videos_count", 0),
        "videos": channel_info.get("videos", []),
    }
