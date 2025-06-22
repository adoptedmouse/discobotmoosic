import os
import discord
from discord.ext import commands
from config import TOKEN, COMMAND_PREFIX

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/music | /play"
            )
        )

    async def setup_hook(self):
        """Load cogs when the bot starts"""
        # Load improved music cog
        try:
            await self.load_extension('cogs.music_improved')
            print("Improved music cog loaded!")
        except Exception as e:
            print(f"Failed to load music cog: {e}")
            raise

    async def on_ready(self):
        """Called when the bot is ready"""
        print(f'Logged in as {self.user.name} ({self.user.id})')
        print('------')
        
        # Sync slash commands
        print("Syncing slash commands...")
        await self.tree.sync()
        print("Slash commands synced!")

def main():
    """Main entry point for the bot"""
    if not TOKEN:
        print("Error: No Discord token found. Please set the DISCORD_TOKEN environment variable.")
        return

    bot = MusicBot()
    bot.run(TOKEN)

if __name__ == '__main__':
    main()
