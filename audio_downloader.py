import asyncio
import os
import tempfile
import logging
import yt_dlp
from config import YTDL_OPTIONS
import discord
import threading
import time

logger = logging.getLogger(__name__)

class DownloadedAudioSource(discord.AudioSource):
    """
    Audio source that plays from a downloaded temporary file
    """
    
    def __init__(self, filepath, cleanup_func=None):
        self.filepath = filepath
        self.cleanup_func = cleanup_func
        
        # Create FFmpeg source for the downloaded file
        self.source = discord.FFmpegPCMAudio(
            filepath,
            before_options='-nostdin',
            options='-vn'
        )
        
    def read(self):
        return self.source.read()
    
    def is_opus(self):
        return self.source.is_opus()
    
    def cleanup(self):
        if hasattr(self.source, 'cleanup'):
            self.source.cleanup()
        
        if self.cleanup_func:
            self.cleanup_func()

class AudioDownloader:
    """
    Downloads audio from YouTube URLs and provides audio sources for discord.py
    """
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="discord_music_")
        self.active_downloads = {}
        self.cleanup_tasks = []
        
        # Configure yt-dlp for downloading (override skip_download)
        self.ytdl_options = YTDL_OPTIONS.copy()
        self.ytdl_options.update({
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'skip_download': False,  # Enable downloading
            'extract_flat': False,   # Don't extract flat
        })
        
        # Remove any options that prevent downloading
        if 'skip_download' in self.ytdl_options:
            del self.ytdl_options['skip_download']
        
        logger.info(f"AudioDownloader initialized with temp directory: {self.temp_dir}")
    
    async def download_audio(self, url, timeout=60):
        """
        Download audio from YouTube URL and return the file path
        
        Args:
            url: YouTube URL
            timeout: Download timeout in seconds
            
        Returns:
            str: Path to downloaded audio file
        """
        try:
            # Check if already downloading
            if url in self.active_downloads:
                logger.info(f"Download already in progress for {url}, waiting...")
                future = self.active_downloads[url]
                return await future
            
            # Create future for this download
            future = asyncio.Future()
            self.active_downloads[url] = future
            
            try:
                # Run yt-dlp download in thread pool
                loop = asyncio.get_event_loop()
                filepath = await asyncio.wait_for(
                    loop.run_in_executor(None, self._download_sync, url),
                    timeout=timeout
                )
                
                if filepath and os.path.exists(filepath):
                    logger.info(f"Successfully downloaded audio to: {filepath}")
                    future.set_result(filepath)
                    return filepath
                else:
                    error_msg = "Download completed but file not found"
                    logger.error(error_msg)
                    future.set_exception(Exception(error_msg))
                    return None
                    
            except asyncio.TimeoutError:
                error_msg = f"Download timed out after {timeout} seconds"
                logger.error(error_msg)
                future.set_exception(Exception(error_msg))
                return None
            except Exception as e:
                logger.error(f"Download error: {e}")
                future.set_exception(e)
                return None
            finally:
                # Remove from active downloads
                if url in self.active_downloads:
                    del self.active_downloads[url]
                    
        except Exception as e:
            logger.error(f"Error in download_audio: {e}")
            return None
    
    def _download_sync(self, url):
        """
        Synchronous download function to run in thread pool
        """
        try:
            # List files before download
            files_before = set(os.listdir(self.temp_dir)) if os.path.exists(self.temp_dir) else set()
            
            with yt_dlp.YoutubeDL(self.ytdl_options) as ytdl:
                # Extract info first
                info = ytdl.extract_info(url, download=False)
                if not info:
                    raise Exception("Could not extract video info")
                
                video_id = info.get('id', 'unknown')
                title = info.get('title', 'Unknown')
                
                logger.info(f"Downloading: {title} (ID: {video_id})")
                
                # Download the audio
                ytdl.download([url])
                
                # List files after download
                files_after = set(os.listdir(self.temp_dir))
                new_files = files_after - files_before
                
                if new_files:
                    # Found new file(s)
                    filename = list(new_files)[0]  # Take the first new file
                    filepath = os.path.join(self.temp_dir, filename)
                    logger.info(f"Found downloaded file: {filepath}")
                    
                    # Verify file exists and has content
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        return filepath
                    else:
                        raise Exception(f"Downloaded file exists but is empty: {filepath}")
                else:
                    # Try to find by video ID (fallback)
                    for filename in os.listdir(self.temp_dir):
                        if video_id in filename:
                            filepath = os.path.join(self.temp_dir, filename)
                            logger.info(f"Found file by video ID: {filepath}")
                            return filepath
                    
                    # List all files for debugging
                    all_files = os.listdir(self.temp_dir)
                    logger.error(f"No new files found. Current files in temp dir: {all_files}")
                    raise Exception(f"Downloaded file not found for video ID: {video_id}")
                
        except Exception as e:
            logger.error(f"Sync download error: {e}")
            raise
    
    async def create_audio_source(self, url, volume=1.0):
        """
        Create an audio source for the given URL
        
        Args:
            url: YouTube URL
            volume: Audio volume (0.0 to 1.0)
            
        Returns:
            AudioSource: Discord audio source
        """
        try:
            filepath = await self.download_audio(url)
            if not filepath:
                raise Exception("Failed to download audio")
            
            # Create cleanup function
            def cleanup_file():
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        logger.info(f"Cleaned up temporary file: {filepath}")
                except Exception as e:
                    logger.error(f"Error cleaning up file {filepath}: {e}")
            
            # Schedule cleanup after some time (in case of errors)
            def schedule_cleanup():
                time.sleep(300)  # 5 minutes
                cleanup_file()
            
            cleanup_thread = threading.Thread(target=schedule_cleanup, daemon=True)
            cleanup_thread.start()
            
            # Create audio source
            source = DownloadedAudioSource(filepath, cleanup_file)
            
            # Apply volume if needed
            if volume != 1.0:
                source = discord.PCMVolumeTransformer(source, volume=volume)
            
            return source
            
        except Exception as e:
            logger.error(f"Error creating audio source: {e}")
            raise
    
    def cleanup(self):
        """
        Clean up temporary directory and files
        """
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up temp directory: {e}")

# Global instance
audio_downloader = AudioDownloader()
