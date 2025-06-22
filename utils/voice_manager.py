import discord
import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
import traceback

logger = logging.getLogger(__name__)

class VoiceConnectionManager:
    """Manages voice connections with proper session handling and error recovery"""
    
    def __init__(self, bot):
        self.bot = bot
        self._connections: Dict[int, discord.VoiceClient] = {}
        self._connection_attempts: Dict[int, datetime] = {}
        self._connection_locks: Dict[int, asyncio.Lock] = {}
        self._cleanup_tasks: Dict[int, asyncio.Task] = {}
        self._keepalive_tasks: Dict[int, asyncio.Task] = {}
        self._inactivity_tasks: Dict[int, asyncio.Task] = {}
        self._session_refresh_interval = 3600  # Refresh session every hour
        self._inactivity_timeout = 600  # 10 minutes in seconds
        
    def get_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create a lock for the guild"""
        if guild_id not in self._connection_locks:
            self._connection_locks[guild_id] = asyncio.Lock()
        return self._connection_locks[guild_id]
        
    async def cleanup_stale_connection(self, guild_id: int) -> None:
        """Clean up any stale connections for a guild"""
        logger.info(f"Cleaning up stale connections for guild {guild_id}")
        
        # Check bot's voice_clients list
        for vc in list(self.bot.voice_clients):
            if vc.guild.id == guild_id:
                try:
                    logger.info(f"Found stale voice client for guild {guild_id}, force disconnecting...")
                    await vc.disconnect(force=True)
                except Exception as e:
                    logger.error(f"Error disconnecting stale voice client: {e}")
                    
        # Remove from our tracking
        if guild_id in self._connections:
            del self._connections[guild_id]
            
        # Cancel any cleanup tasks
        if guild_id in self._cleanup_tasks:
            self._cleanup_tasks[guild_id].cancel()
            del self._cleanup_tasks[guild_id]
            
        # Cancel keepalive tasks
        if guild_id in self._keepalive_tasks:
            self._keepalive_tasks[guild_id].cancel()
            del self._keepalive_tasks[guild_id]
            
        # Cancel inactivity tasks
        if guild_id in self._inactivity_tasks:
            self._inactivity_tasks[guild_id].cancel()
            del self._inactivity_tasks[guild_id]
            
        # Wait for Discord to process the disconnection
        await asyncio.sleep(2)
        
    def should_retry_connection(self, guild_id: int) -> bool:
        """Check if we should retry connection based on cooldown"""
        if guild_id not in self._connection_attempts:
            return True
            
        last_attempt = self._connection_attempts[guild_id]
        cooldown_period = timedelta(seconds=10)  # 10 second cooldown between attempts
        
        return datetime.now() - last_attempt > cooldown_period
        
    async def validate_session(self, voice_client: discord.VoiceClient) -> bool:
        """Validate if a voice session is still valid"""
        if not voice_client or not voice_client.is_connected():
            return False
            
        try:
            # Check if we can access voice client properties
            _ = voice_client.channel
            _ = voice_client.guild
            
            # Check WebSocket state
            if hasattr(voice_client, 'ws') and voice_client.ws:
                return True
            else:
                logger.warning("Voice client has no valid WebSocket")
                return False
                
        except Exception as e:
            logger.error(f"Error validating session: {e}")
            return False
            
    async def connect_with_retry(
        self, 
        channel: discord.VoiceChannel, 
        max_retries: int = 3,
        backoff_base: float = 2.0
    ) -> Optional[discord.VoiceClient]:
        """Connect to voice channel with exponential backoff retry logic"""
        guild_id = channel.guild.id
        
        async with self.get_lock(guild_id):
            # Check cooldown
            if not self.should_retry_connection(guild_id):
                wait_time = 10 - (datetime.now() - self._connection_attempts[guild_id]).seconds
                logger.warning(f"Connection on cooldown for guild {guild_id}, wait {wait_time}s")
                return None
                
            # Clean up any existing connections first
            await self.cleanup_stale_connection(guild_id)
            
            for attempt in range(max_retries):
                try:
                    # Update last attempt time
                    self._connection_attempts[guild_id] = datetime.now()
                    
                    # Calculate backoff time
                    if attempt > 0:
                        backoff_time = min(backoff_base ** attempt, 30)  # Cap at 30 seconds
                        logger.info(f"Waiting {backoff_time}s before retry attempt {attempt + 1}")
                        await asyncio.sleep(backoff_time)
                    
                    logger.info(f"Voice connection attempt {attempt + 1}/{max_retries} to {channel}")
                    
                    # Attempt connection with proper parameters
                    voice_client = await channel.connect(
                        timeout=60.0,
                        reconnect=True,
                        self_deaf=True,
                        self_mute=False,
                        cls=discord.VoiceClient
                    )
                    
                    # Verify connection stability
                    await asyncio.sleep(1)
                    
                    if await self.validate_session(voice_client):
                        logger.info(f"Successfully connected to {channel} on attempt {attempt + 1}")
                        self._connections[guild_id] = voice_client
                        
                        # Schedule periodic session refresh
                        if guild_id in self._cleanup_tasks:
                            self._cleanup_tasks[guild_id].cancel()
                        self._cleanup_tasks[guild_id] = asyncio.create_task(
                            self._session_refresh_task(guild_id)
                        )
                        
                        # Start voice keepalive task
                        if guild_id in self._keepalive_tasks:
                            self._keepalive_tasks[guild_id].cancel()
                        self._keepalive_tasks[guild_id] = asyncio.create_task(
                            self._voice_keepalive_task(guild_id)
                        )
                        
                        return voice_client
                    else:
                        logger.warning("Connection established but session validation failed")
                        if voice_client:
                            await voice_client.disconnect(force=True)
                            
                except discord.errors.ConnectionClosed as e:
                    if e.code == 4006:
                        logger.error(f"Session invalid (4006) on attempt {attempt + 1}")
                        # For 4006, we need a longer wait
                        if attempt < max_retries - 1:
                            await asyncio.sleep(15)
                    else:
                        logger.error(f"Connection closed with code {e.code}: {e}")
                        
                except discord.ClientException as e:
                    if "already connected" in str(e).lower():
                        logger.warning("Bot reports already connected, attempting recovery")
                        # Try to find and validate existing connection
                        for vc in self.bot.voice_clients:
                            if vc.guild.id == guild_id:
                                if await self.validate_session(vc):
                                    logger.info("Found valid existing connection")
                                    self._connections[guild_id] = vc
                                    return vc
                                else:
                                    logger.info("Found invalid connection, cleaning up")
                                    await self.cleanup_stale_connection(guild_id)
                                    break
                    else:
                        logger.error(f"Discord client error: {e}")
                        
                except asyncio.TimeoutError:
                    logger.error(f"Connection timeout on attempt {attempt + 1}")
                    
                except Exception as e:
                    logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                    logger.error(traceback.format_exc())
                    
            logger.error(f"Failed to connect after {max_retries} attempts")
            return None
            
    async def _session_refresh_task(self, guild_id: int):
        """Periodically refresh the voice session to prevent 4006 errors"""
        try:
            while guild_id in self._connections:
                await asyncio.sleep(self._session_refresh_interval)
                
                voice_client = self._connections.get(guild_id)
                if voice_client and await self.validate_session(voice_client):
                    logger.info(f"Refreshing voice session for guild {guild_id}")
                    # Send a heartbeat or perform a minor action to keep session alive
                    # This helps prevent session timeout issues
                else:
                    logger.warning(f"Voice session invalid for guild {guild_id}, will reconnect on next use")
                    await self.cleanup_stale_connection(guild_id)
                    break
                    
        except asyncio.CancelledError:
            logger.info(f"Session refresh task cancelled for guild {guild_id}")
            
    async def _voice_keepalive_task(self, guild_id: int):
        """Keeps the voice connection alive by periodically sending packets"""
        try:
            logger.info(f"Starting voice keepalive task for guild {guild_id}")
            while guild_id in self._connections:
                voice_client = self._connections.get(guild_id)
                if voice_client and voice_client.is_connected():
                    # Send a packet every 15 seconds
                    try:
                        voice_client.send_audio_packet(b'\xF8\xFF\xFE', encode=False)
                        await asyncio.sleep(15)
                    except Exception as e:
                        logger.error(f"Error sending keepalive packet for guild {guild_id}: {e}")
                        # If we can't send packets, the connection is prob dead
                        break
                else:
                    logger.info(f"Voice client disconnected for guild {guild_id}, stopping keepalive")
                    break
        except asyncio.CancelledError:
            logger.info(f"Voice keepalive task cancelled for guild {guild_id}")
        except Exception as e:
            logger.error(f"Unexpected error in voice keepalive task for guild {guild_id}: {e}")
            
    async def _inactivity_disconnect_task(self, guild_id: int):
        """Disconnect after inactivity timeout"""
        try:
            logger.info(f"Starting inactivity timer for guild {guild_id} ({self._inactivity_timeout}s)")
            await asyncio.sleep(self._inactivity_timeout)
            
            # Check if we're still connected and should disconnect
            voice_client = self._connections.get(guild_id)
            if voice_client and voice_client.is_connected():
                logger.info(f"Disconnecting from guild {guild_id} due to inactivity")
                
                # Try to send a message to the last known channel
                try:
                    # Get the guild and find a text channel to send the message
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        # Try to find a channel named 'music' or 'bot-commands' first
                        target_channel = None
                        for channel in guild.text_channels:
                            if channel.name.lower() in ['music', 'bot-commands']:
                                target_channel = channel
                                break
                        
                        # If not found, use the first available text channel
                        if not target_channel and guild.text_channels:
                            target_channel = guild.text_channels[0]
                        
                        if target_channel:
                            embed = discord.Embed(
                                title="🚪 Auto-Disconnect",
                                description="Left voice channel due to 10 minutes of inactivity.",
                                color=discord.Color.orange()
                            )
                            await target_channel.send(embed=embed)
                except Exception as msg_error:
                    logger.error(f"Could not send inactivity message for guild {guild_id}: {msg_error}")
                
                # Disconnect
                await self.disconnect(guild_id)
                
        except asyncio.CancelledError:
            logger.info(f"Inactivity timer cancelled for guild {guild_id}")
        except Exception as e:
            logger.error(f"Error in inactivity disconnect task for guild {guild_id}: {e}")
            
    def start_inactivity_timer(self, guild_id: int):
        """Start the inactivity timer for auto-disconnect"""
        # Cancel any existing inactivity timer
        if guild_id in self._inactivity_tasks:
            self._inactivity_tasks[guild_id].cancel()
        
        # Start new inactivity timer
        self._inactivity_tasks[guild_id] = asyncio.create_task(
            self._inactivity_disconnect_task(guild_id)
        )
        logger.info(f"Started inactivity timer for guild {guild_id}")
        
    def cancel_inactivity_timer(self, guild_id: int):
        """Cancel the inactivity timer"""
        if guild_id in self._inactivity_tasks:
            self._inactivity_tasks[guild_id].cancel()
            del self._inactivity_tasks[guild_id]
            logger.info(f"Cancelled inactivity timer for guild {guild_id}")
    
    async def disconnect(self, guild_id: int) -> None:
        """Properly disconnect from a voice channel"""
        async with self.get_lock(guild_id):
            voice_client = self._connections.get(guild_id)
            
            if voice_client:
                try:
                    await voice_client.disconnect()
                    logger.info(f"Disconnected from guild {guild_id}")
                except Exception as e:
                    logger.error(f"Error during disconnect: {e}")
                    
            await self.cleanup_stale_connection(guild_id)
            
    def get_voice_client(self, guild_id: int) -> Optional[discord.VoiceClient]:
        """Get the voice client for a guild"""
        return self._connections.get(guild_id)
        
    async def move_to(self, guild_id: int, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        """Move to a different voice channel in the same guild"""
        voice_client = self._connections.get(guild_id)
        
        if voice_client and await self.validate_session(voice_client):
            try:
                await voice_client.move_to(channel)
                logger.info(f"Moved to {channel} in guild {guild_id}")
                return voice_client
            except Exception as e:
                logger.error(f"Error moving to channel: {e}")
                await self.cleanup_stale_connection(guild_id)
                
        # If move failed or no valid connection, try fresh connection
        return await self.connect_with_retry(channel)
