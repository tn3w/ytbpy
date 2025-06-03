# ytpy

A fast, lightweight Python library for extracting information from YouTube without requiring API keys or authentication.

## Features

- **Zero Dependencies**: Uses only Python standard libraries
- **No API Key Required**: Works without YouTube API credentials
- **Fast & Lightweight**: Minimal overhead for quick information extraction
- **No Authentication**: No need for login or OAuth

## Installation

```bash
git clone https://github.com/tn3w/ytpy.git
cd ytpy
git install -e .
```

## Usage

### Get Video Information

```python
from ytpy import video

# Get details about a video using URL or ID
video_info = video.get_video_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
# OR
video_info = video.get_video_info('dQw4w9WgXcQ')

print(video_info['title'])
print(video_info['duration'])
print(video_info['views_count'])
```

### Search YouTube

```python
from ytpy import search

# Search YouTube videos
results = search.search_youtube('python tutorial', max_results=5)

for video in results:
    print(f"{video['title']} - {video['url']}")
```

### Get Playlist Information

```python
from ytpy import playlist

# Get all videos in a playlist
playlist_info = playlist.get_playlist_info('https://www.youtube.com/playlist?list=PLvFYFNbi-IBFeP5ALr55MbK4EkxqdkzFT')

print(f"Playlist: {playlist_info['title']}")
print(f"Videos: {playlist_info['video_count']}")

for video in playlist_info['videos']:
    print(video['title'])
```

### Get Channel Information

```python
from ytpy import channel

# Get channel info and recent videos
channel_info = channel.get_channel_info('https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw')

print(f"Channel: {channel_info['title']}")
print(f"Subscribers: {channel_info['subscriber_count']}")

# List recent videos
for video in channel_info['videos']:
    print(video['title'])
```

## License

Copyright 2025 TN3W

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.