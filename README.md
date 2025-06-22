# SOLACEBOT - Discord Music Bot

A feature-rich Discord music bot built with Python that can play music from YouTube with advanced voice connection management and queue functionality.

## Features

- 🎵 Play music from YouTube using search queries or direct URLs
- 📜 Queue management with skip functionality
- 🔊 Advanced voice connection handling with auto-reconnect
- ⏰ Auto-disconnect after 10 minutes of inactivity
- 🎛️ Volume control and audio processing
- 🔄 Fallback systems for reliable audio streaming
- 💾 Smart caching and prefetching for better performance

## Commands

- `/music` - Join your voice channel
- `/play <query>` - Play a song or add it to the queue
- `/skip` - Skip the current song
- `/queue` - Show the current queue
- `/leave` - Leave the voice channel

## Prerequisites

Before running the bot, make sure you have:

1. **Python 3.8+** installed
2. **FFmpeg** installed and accessible from PATH
3. **Discord Bot Token** from Discord Developer Portal

### Installing FFmpeg

**Windows:**
- Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
- Add to your system PATH

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

## Installation

1. **Clone the repository:**
```bash
git clone <your-repo-url>
cd SOLACEBOT
```

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables:**
```bash
cp .env.example .env
```
Edit `.env` and add your Discord bot token:
```
DISCORD_TOKEN=your_actual_bot_token_here
```

4. **Create a Discord Application:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section and create a bot
   - Copy the token and paste it in your `.env` file
   - Enable "Message Content Intent" in the bot settings

5. **Invite the bot to your server:**
   - In Discord Developer Portal, go to OAuth2 > URL Generator
   - Select "bot" and "applications.commands" scopes
   - Select permissions: "Connect", "Speak", "Use Voice Activity"
   - Use the generated URL to invite the bot

## Usage

1. **Run the bot:**
```bash
python main.py
```

2. **In Discord:**
   - Join a voice channel
   - Use `/music` to make the bot join your channel
   - Use `/play <song name>` to play music
   - Use `/queue` to see what's playing and up next

## Configuration

The bot can be configured through `config.py`:

- `MAX_QUEUE_SIZE`: Maximum songs in queue (default: 100)
- `DEFAULT_VOLUME`: Default playback volume (default: 0.5)
- `SEARCH_FILTERS`: Filters for YouTube searches
- YouTube-DL options for audio extraction

## Troubleshooting

### Common Issues

**Bot not playing audio:**
- Ensure FFmpeg is installed and in PATH
- Check that the bot has proper voice permissions
- Verify your internet connection

**YouTube errors:**
- The bot may need YouTube cookies for some videos
- Age-restricted content may not be accessible

**Connection issues:**
- The bot automatically handles reconnections
- If issues persist, use `/leave` and `/music` to reconnect

### Logs

The bot creates `ffmpeg_stream.log` for debugging audio issues. Check this file if you experience playback problems.

## Architecture

The bot is built with a modular architecture:

- `main.py` - Entry point and bot initialization
- `config.py` - Configuration and settings
- `cogs/music_improved.py` - Main music functionality
- `utils/voice_manager.py` - Voice connection management
- `utils/music_utils.py` - YouTube audio extraction
- `utils/process_manager.py` - External process management
- `audio_downloader.py` - Fallback audio downloading

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is provided as-is for educational and personal use.

## Disclaimer

This bot is for personal/educational use. Ensure you comply with YouTube's Terms of Service and Discord's Terms of Service when using this bot.
