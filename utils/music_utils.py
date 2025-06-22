import asyncio
import yt_dlp
from concurrent.futures import ProcessPoolExecutor
from config import YTDL_OPTIONS
import time
import threading
import queue
import logging

logger = logging.getLogger(__name__)

def extract_info_sync(query, options):
    """Synchronous function to extract info using yt_dlp in a separate process"""
    try:
        with yt_dlp.YoutubeDL(options) as ytdl:
            info = ytdl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            return info
    except Exception as e:
        logger.error(f"Error in process: {e}")
        return None

class YTDLSource:
    def __init__(self, max_workers=2):  # Reduced workers to conserve resources
        self.process_pool = ProcessPoolExecutor(max_workers=max_workers)
        self.download_queue = queue.PriorityQueue()
        self.url_cache = {}
        self.cache_expiry = {}
        self.cache_duration = 3600
        self.download_in_progress = set()
        self.download_lock = threading.Lock()
        self.options = YTDL_OPTIONS.copy()

    def get_cached_url(self, query):
        if query in self.url_cache and time.time() < self.cache_expiry.get(query, 0):
            logger.info(f"Using cached URL for {query}")
            return self.url_cache[query]
        return None

    async def extract_info(self, query, download=False, priority=1):
        with self.download_lock:
            if query in self.download_in_progress:
                logger.info(f"Waiting for {query} in progress...")
                return None  # Simplified; could wait with a Future
            self.download_in_progress.add(query)

        try:
            info = await asyncio.get_event_loop().run_in_executor(
                self.process_pool,
                extract_info_sync,
                query,
                self.options
            )
            if info and 'url' in info:
                self.url_cache[query] = info['url']
                self.cache_expiry[query] = time.time() + self.cache_duration
            return info
        finally:
            with self.download_lock:
                self.download_in_progress.discard(query)

    async def search_song(self, search_query: str, priority=1):
        try:
            info = await self.extract_info(f"ytsearch1:{search_query}", False, priority)
            if info:
                return {
                    'webpage_url': info['webpage_url'],
                    'title': info['title'],
                    'thumbnail': info.get('thumbnail'),
                    'url': info.get('url')
                }
            return None
        except Exception as e:
            logger.error(f"Search error: {e}")
            return None

    async def get_audio_source(self, url: str, priority=1):
        try:
            cached_url = self.get_cached_url(url)
            if cached_url:
                return {'url': cached_url, 'title': 'Unknown', 'webpage_url': url}
            info = await self.extract_info(url, False, priority)
            if info:
                return {
                    'url': info.get('url'),
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail'),
                    'webpage_url': info.get('webpage_url', url)
                }
            return None
        except Exception as e:
            logger.error(f"Audio source error: {e}")
            return None

    async def prefetch_song(self, url: str):
        try:
            await self.extract_info(url, False, priority=10)
            return True
        except Exception as e:
            logger.error(f"Prefetch error: {e}")
            return False