import discord
import os
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from session import init_db
from modals import CubeSelectionModal
from utils import cleanup_sessions_task
from commands import league_commands, scheduled_posts, swiss_draft_commands
import asyncio

async def main():
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve the bot token
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Error: BOT_TOKEN is not set in environment variables.")
        return

    # Required Intents
    intents = discord.Intents.default()
    intents.messages = True
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    intents.reactions = True
    intents.presences = True

    # Initialize bot with intents and command prefix
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        # Sync slash commands to Discord
        await bot.tree.sync()
        print(f'Logged in as {bot.user}!')

        # Start background task to clean up sessions
        bot.loop.create_task(cleanup_sessions_task(bot))
        
        # Register views and challenges
        from utils import re_register_views, re_register_challenges
        await re_register_views(bot)
        await re_register_challenges(bot)
        
        # Re-register team finder if necessary
        from teamfinder import re_register_teamfinder
        await re_register_teamfinder(bot)

    # Define slash commands using bot.tree
    @bot.tree.command(name='startdraft', description='Start a team draft with random teams')
    async def start_draft(interaction: discord.Interaction):
        await interaction.response.send_modal(CubeSelectionModal(session_type="random", title="Select Cube"))

    @bot.tree.command(name='premadedraft', description='Start a team draft with premade teams')
    async def premade_draft(interaction: discord.Interaction):
        await interaction.response.send_modal(CubeSelectionModal(session_type="premade", title="Select Cube"))

    # Define a simple test command
    @bot.tree.command(name="test", description="Test command to check if the bot is responsive")
    async def test(interaction: discord.Interaction):
        await interaction.response.send_message("Bot is active and responsive!")

    # Register additional commands and tasks
    await league_commands(bot)
    await scheduled_posts(bot)
    await swiss_draft_commands(bot)
    await init_db()

    # Start the bot
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
