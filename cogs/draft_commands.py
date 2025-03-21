import discord
from discord.ext import commands
from loguru import logger
from modals import CubeDraftSelectionView, StakedCubeDraftSelectionView

from session import DraftSession, MatchResult
from views import MatchResultSelect

class DraftCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name='startdraft', description='Start a team draft with random teams', guild_id=None)
    async def start_draft(self, ctx):
        logger.info("Received startdraft command")
        view = CubeDraftSelectionView(session_type="random")
        await ctx.response.send_message("Select a cube:", view=view, ephemeral=True)

    @discord.slash_command(name='premadedraft', description='Start a team draft with premade teams', guild_id=None)
    async def premade_draft(self, ctx):
        logger.info("Received premadedraft command")
        view = CubeDraftSelectionView(session_type="premade")
        await ctx.response.send_message("Select a cube:", view=view, ephemeral=True)
        
    @discord.slash_command(name='dynamic_stake', description='Start a team draft with random teams and customizable stakes')
    async def staked_draft(self, ctx):
        logger.info("Received stakedraft command")
        view = StakedCubeDraftSelectionView()
        await ctx.response.send_message("Select a cube for the staked draft:", view=view, ephemeral=True)

    @discord.slash_command(
        name='report_results', 
        description='Report the result of your last unreported match',
        guild_ids=None
    )
    async def report_match(self, ctx):
        """Report the result of your latest unreported match"""
        logger.info(f"Received report command from user {ctx.author.id}")
        await ctx.response.defer(ephemeral=True)
        
        user_id = str(ctx.author.id)
        channel_id = str(ctx.channel_id)
        
        # Get draft session by channel
        draft_session = await DraftSession.get_by_channel_id(channel_id)
        if not draft_session:
            await ctx.followup.send("This command can only be used in active draft channels.", ephemeral=True)
            return
        
        # Check if user is participating
        if not draft_session.is_user_participating(user_id):
            await ctx.followup.send("You are not a participant in this draft.", ephemeral=True)
            return
        
        # Find unreported match for user
        match = await MatchResult.find_unreported_for_user(draft_session.session_id, user_id)
        if not match:
            await ctx.followup.send("You don't have any unreported matches in this draft.", ephemeral=True)
            return
        
        # Create match result UI
        await self._send_match_result_selector(ctx, match, draft_session.session_id)

    async def _send_match_result_selector(self, ctx, match, session_id):
        """Create and send the match result selection UI."""
        # Get player names
        player1 = ctx.guild.get_member(int(match.player1_id))
        player2 = ctx.guild.get_member(int(match.player2_id))
        
        if not player1 or not player2:
            await ctx.followup.send("Could not find one or both players for this match.", ephemeral=True)
            return
            
        player1_name = player1.display_name
        player2_name = player2.display_name
        
        # Create the select menu
        select_menu = MatchResultSelect(
            bot=self.bot,
            match_number=match.match_number,
            session_id=session_id,
            player1_name=player1_name,
            player2_name=player2_name
        )
        
        # Create a view and add the select menu
        view = discord.ui.View()
        view.add_item(select_menu)
        
        # Send the response with the select menu
        await ctx.followup.send(
            f"Report result for Match {match.match_number}: {player1_name} vs {player2_name}", 
            view=view,
            ephemeral=True
        )

def setup(bot):
    bot.add_cog(DraftCommands(bot))
