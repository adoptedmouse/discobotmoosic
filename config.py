import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
TOKEN = os.getenv('DISCORD_TOKEN')
COMMAND_PREFIX = '/'

# Music Configuration
MAX_QUEUE_SIZE = 100
DEFAULT_VOLUME = 0.5
SEARCH_FILTERS = {
    'duration': {
        'max': 600,  # 10 minutes max duration
        'min': 30    # 30 seconds min duration
    },
    'ignore_patterns': [
        'shorts',    # Ignore YouTube shorts
        'podcast',   # Ignore podcasts
        'live',      # Ignore live streams
    ]
}

# YouTube DL Options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'cookiefile': 'youtube_cookies.txt',
    'ignoreerrors': True,
    'no_color': True,
    'retries': 10,  # Increased retry attempts
    'socket_timeout': 30,  # Increased timeout
    'extract_flat': False,
    'skip_download': True,
    'source_address': '0.0.0.0',  # Bind to all interfaces
    'geo_bypass': True,  # Try to bypass geo-restrictions
    'geo_bypass_country': 'US',
    'extractor_retries': 5,  # Retry extractor on failure
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    }
}

# FFmpeg options optimized for YouTube streaming
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -loglevel error"
}

# Fallback FFmpeg options for when the main options fail
FALLBACK_FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn'
}
