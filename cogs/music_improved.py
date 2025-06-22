import discord
from discord import app_commands
from discord.ext import commands
from utils.music_utils import YTDLSource
from utils.voice_manager import VoiceConnectionManager
from config import FFMPEG_OPTIONS, FALLBACK_FFMPEG_OPTIONS, DEFAULT_VOLUME, MAX_QUEUE_SIZE
from audio_downloader import audio_downloader
import asyncio
from collections import deque
import traceback
import logging
import time
from typing import Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ImprovedMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}
        self.processing_tasks = {}
        self.voice_manager = VoiceConnectionManager(bot)

    class VoiceState:
        def __init__(self):
            self.voice_client = None
            self.current_song = None
            self.queue = deque(maxlen=MAX_QUEUE_SIZE)
            self.volume = DEFAULT_VOLUME
            self.ytdl = YTDLSource(max_workers=4)
            self.loop = asyncio.get_event_loop()
            self.processing_queue = asyncio.Queue()
            self.processing = False
            self.last_error = None
            self.is_connecting = False  # Flag to prevent multiple connection attempts

        def is_playing(self):
            return self.voice_client and self.voice_client.is_playing()

    def get_voice_state(self, ctx):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = self.VoiceState()
            self.voice_states[ctx.guild.id] = state
        return state

    async def prefetch_next_songs(self, state: VoiceState):
        """Pre-fetch the next few songs in the queue"""
        try:
            for i, song in enumerate(list(state.queue)[:3]):
                if 'webpage_url' in song and not state.ytdl.get_cached_url(song['webpage_url']):
                    priority = 5 + i
                    logger.info(f"Prefetching song {i+1} in queue with priority {priority}: {song['title']}")
                    self.bot.loop.create_task(state.ytdl.prefetch_song(song['webpage_url']))
        except Exception as e:
            logger.error(f"Error prefetching songs: {e}")

    async def play_next(self, ctx):
        state = self.get_voice_state(ctx)
        
        if not state.queue or not state.voice_client:
            logger.info("Queue is empty or voice client is None, stopping playback")
            if state.voice_client:
                self.voice_manager.start_inactivity_timer(ctx.guild.id)
            return

        try:
            if len(state.queue) == 0:
                logger.info("Queue became empty while trying to play next song")
                return
                
            next_song = state.queue.popleft()
            self.bot.loop.create_task(self.prefetch_next_songs(state))
            
            source = None  # Initialize source to None
            
            # Try streaming first
            try:
                logger.info(f"Attempting to stream: {next_song['title']}")
                info = await state.ytdl.get_audio_source(next_song['webpage_url'], priority=0)
                if info and info.get('url'):
                    source = discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTIONS, stderr=open('ffmpeg_stream.log', 'a'))
                    source = discord.PCMVolumeTransformer(source, volume=state.volume)
                    logger.info(f"Streaming source created for: {next_song['title']}")
                else:
                    raise Exception("Could not get audio URL for streaming")
            except Exception as stream_error:
                logger.error(f"Streaming failed: {stream_error}")
                # Fallback to downloader
                try:
                    logger.info(f"Falling back to downloader for: {next_song['title']}")
                    source = await audio_downloader.create_audio_source(
                        next_song['webpage_url'], 
                        volume=state.volume
                    )
                    logger.info(f"Downloader source created for: {next_song['title']}")
                except Exception as downloader_error:
                    logger.error(f"Downloader failed: {downloader_error}")
                    raise Exception(f"Both streaming and downloading failed: {downloader_error}")
            
            if source is None:
                raise Exception("Failed to create audio source")
            
            state.current_song = next_song
            state.last_error = None
            
            def after_playing(error):
                if error:
                    logger.error(f"Playback error: {error}")
                    state.last_error = error
                state.loop.create_task(self.play_next(ctx))
            
            self.voice_manager.cancel_inactivity_timer(ctx.guild.id)
            logger.info("About to play source")
            logger.info(f"Audio URL: {info['url']}")
            state.voice_client.play(source, after=after_playing)
            logger.info("Started playing source")

            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"[{next_song['title']}]({next_song['webpage_url']})",
                color=discord.Color.green()
            )
            if next_song.get('thumbnail'):
                embed.set_thumbnail(url=next_song['thumbnail'])
            await ctx.channel.send(embed=embed)
            logger.info(f"Now playing: {next_song['title']}")

        except Exception as e:
            logger.error(f"Error in play_next: {e}")
            state.last_error = e
            await ctx.channel.send(f"❌ Could not play {next_song['title']}: {str(e)}")
            if state.queue:
                logger.info("Attempting next song...")
                await self.play_next(ctx)

    async def process_songs(self, guild_id: int):
        """Background task to process songs in the queue"""
        state = self.voice_states.get(guild_id)
        if not state:
            return

        while True:
            try:
                interaction, query = await state.processing_queue.get()
                state.processing = True

                try:
                    priority = 1 if not state.is_playing() else 2
                    logger.info(f"Processing song request with priority {priority}: {query}")
                    song = await state.ytdl.search_song(query, priority=priority)
                    
                    if song and song.get('url'):
                        state.queue.append(song)
                        
                        # Cancel inactivity timer since we have new activity
                        self.voice_manager.cancel_inactivity_timer(guild_id)
                        
                        if not state.is_playing():
                            await self.play_next(interaction)
                            await interaction.followup.send(f"▶️ Playing: {song['title']}")
                        else:
                            self.bot.loop.create_task(self.prefetch_next_songs(state))
                            await interaction.followup.send(f"➕ Added to queue: {song['title']}")
                    else:
                        await interaction.followup.send("❌ Could not find or play this song!")
                except Exception as e:
                    logger.error(f"Error processing song: {e}")
                    await interaction.followup.send("❌ Error processing song - please try again!")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in process_songs: {e}")
            finally:
                state.processing = False
                state.processing_queue.task_done()

    @app_commands.command(name="music", description="Join your voice channel")
    async def music(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You must be in a voice channel to use this command!")
            return

        await interaction.response.defer(thinking=True)
        
        state = self.get_voice_state(interaction)
        guild_id = interaction.guild_id
        
        try:
            # Check if already connected
            existing_vc = self.voice_manager.get_voice_client(guild_id)
            if existing_vc and await self.voice_manager.validate_session(existing_vc):
                if existing_vc.channel != interaction.user.voice.channel:
                    # Move to new channel
                    voice_client = await self.voice_manager.move_to(guild_id, interaction.user.voice.channel)
                    if voice_client:
                        state.voice_client = voice_client
                        await interaction.followup.send(f"✅ Moved to {interaction.user.voice.channel.mention}")
                    else:
                        await interaction.followup.send("❌ Failed to move to your voice channel.")
                else:
                    await interaction.followup.send("✅ Already connected to your voice channel!")
                return

            # Connect to voice channel
            voice_client = await self.voice_manager.connect_with_retry(interaction.user.voice.channel)
            if voice_client:
                state.voice_client = voice_client
                
                # Start inactivity timer since bot joined but may be idle
                if not state.is_playing() and len(state.queue) == 0:
                    self.voice_manager.start_inactivity_timer(guild_id)
                
                await interaction.followup.send(f"✅ Joined {interaction.user.voice.channel.mention}")
            else:
                await interaction.followup.send("❌ Failed to join voice channel. Please try again later.")
                
        except Exception as e:
            logger.error(f"Error in music command: {e}")
            await interaction.followup.send("❌ Error joining voice channel!")

    @app_commands.command(name="play", description="Play a song or add it to the queue")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You must be in a voice channel to use this command!")
            return

        await interaction.response.defer(thinking=True)

        state = self.get_voice_state(interaction)
        guild_id = interaction.guild_id
        
        # Handle voice connection
        existing_vc = self.voice_manager.get_voice_client(guild_id)
        if not existing_vc or not await self.voice_manager.validate_session(existing_vc):
            voice_client = await self.voice_manager.connect_with_retry(interaction.user.voice.channel)
            if not voice_client:
                await interaction.followup.send("❌ Failed to join voice channel. Please try again later.")
                return
            state.voice_client = voice_client
        else:
            state.voice_client = existing_vc

        # Start the background processing task if not already running
        if guild_id not in self.processing_tasks:
            self.processing_tasks[guild_id] = self.bot.loop.create_task(
                self.process_songs(guild_id)
            )

        # Add the song request to the processing queue
        await state.processing_queue.put((interaction, query))

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        state = self.get_voice_state(interaction)
        
        if not state.is_playing():
            await interaction.followup.send("❌ Nothing is playing!")
            return

        try:
            state.voice_client.stop()
            await interaction.followup.send("⏭️ Skipped the current song!")
        except Exception as e:
            logger.error(f"Error in skip command: {e}")
            await interaction.followup.send("❌ Error skipping the song!")

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        try:
            state = self.get_voice_state(interaction)
            
            if not state.queue and not state.current_song:
                await interaction.followup.send("📭 Queue is empty!")
                return

            embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blue())
            
            if state.current_song and isinstance(state.current_song, dict):
                title = state.current_song.get('title', 'Unknown')
                url = state.current_song.get('webpage_url', '#')
                embed.add_field(
                    name="Now Playing",
                    value=f"[{title}]({url})",
                    inline=False
                )

            if state.queue and len(state.queue) > 0:
                try:
                    queue_items = []
                    for i, song in enumerate(list(state.queue)):
                        if isinstance(song, dict):
                            title = song.get('title', 'Unknown')
                            url = song.get('webpage_url', '#')
                            queue_items.append(f"{i+1}. [{title}]({url})")
                        
                        if i >= 9:
                            remaining = len(state.queue) - 10
                            if remaining > 0:
                                queue_items.append(f"... and {remaining} more songs")
                            break
                    
                    if queue_items:
                        queue_list = "\n".join(queue_items)
                        embed.add_field(name="Up Next", value=queue_list, inline=False)
                except Exception as queue_error:
                    logger.error(f"Error processing queue items: {queue_error}")
                    embed.add_field(name="Up Next", value=f"{len(state.queue)} songs in queue", inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in queue command: {e}")
            await interaction.followup.send("❌ Error displaying queue!")

    @app_commands.command(name="leave", description="Leave the voice channel")
    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        try:
            state = self.get_voice_state(interaction)
            guild_id = interaction.guild_id
            
            if not self.voice_manager.get_voice_client(guild_id):
                await interaction.followup.send("❌ I'm not in a voice channel!")
                return

            # Cancel the background processing task
            if guild_id in self.processing_tasks:
                self.processing_tasks[guild_id].cancel()
                del self.processing_tasks[guild_id]

            # Disconnect using voice manager
            await self.voice_manager.disconnect(guild_id)
            
            # Clear state
            state.voice_client = None
            state.queue.clear()
            state.current_song = None
            
            await interaction.followup.send("👋 Left the voice channel!")
        except Exception as e:
            logger.error(f"Error in leave command: {e}")
            await interaction.followup.send("❌ Error leaving voice channel!")

async def setup(bot):
    await bot.add_cog(ImprovedMusic(bot))