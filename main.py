import discord
import asyncio
import os
import dotenv
from datetime import datetime, timedelta
from discord.ext import commands
from discord.ui import Button, View
import random
import secrets

# Load the environment variables
dotenv.load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

TOKEN = os.getenv("BOT_TOKEN")

bot = commands.Bot(command_prefix="!", intents=intents)

sessions = {}

class DraftSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.message_id = None
        self.draft_channel_id = None
        self.draft_message_id = None
        self.draft_link = None
        self.draft_start_time = datetime.now()
        self.deletion_time = datetime.now() + timedelta(hours=7)
        self.draft_chat_channel = None
        self.guild_id = None
        self.draft_id = None
        self.sign_ups = {}
        self.channel_ids = []

    async def update_draft_message(self, interaction):
        message = await interaction.channel.fetch_message(self.message_id)
        embed = message.embeds[0]
        sign_ups_count = len(self.sign_ups)
        sign_ups_field_name = f"Sign-Ups ({sign_ups_count}):" if self.sign_ups else "Sign-Ups (0):"
        sign_ups_str = '\n'.join(self.sign_ups.values()) if self.sign_ups else 'No players yet.'
        embed.set_field_at(0, name=sign_ups_field_name, value=sign_ups_str, inline=False)

        await message.edit(embed=embed)


    async def create_team_channel(self, guild, team_name, team_members):
        draft_category = discord.utils.get(guild.categories, name="Draft Channels")
        channel_name = f"{team_name}-Chat-{self.draft_id}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        for member in team_members:
            overwrites[member] = discord.PermissionOverwrite(read_messages=True)

        channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites, category=draft_category)
        self.channel_ids.append(channel.id)

        if team_name == "Draft-chat":
            self.draft_chat_channel = channel.id

        # Since self.draft_start_time is a datetime object, you can directly add timedelta to it
        deletion_timestamp = int(self.deletion_time.timestamp())  # Convert to integer for Unix time
        deletion_message = await channel.send(f"This channel will be deleted <t:{deletion_timestamp}:R>.")
        
        # Automatically delete the channel after 7 hours
        await asyncio.sleep(7 * 3600)
        await channel.delete(reason="Scheduled draft session cleanup")

    async def schedule_session_cleanup(self):
        # Calculate the wait time until deletion
        now = datetime.now()
        wait_time = (self.deletion_time - now).total_seconds()

        # Schedule the cleanup task to run after the wait time
        asyncio.create_task(self.cleanup_task())
    
    async def cleanup_task(self):
        # Calculate the wait time again to ensure accuracy
        now = datetime.now()
        wait_time = (self.deletion_time - now).total_seconds()

        # Use asyncio.sleep to wait until the deletion time
        await asyncio.sleep(wait_time)

        # Perform the cleanup: Remove the session from the sessions dictionary
        sessions.pop(self.session_id, None)
        
    async def update_draft_complete_message(self, interaction):
        message = await interaction.channel.fetch_message(self.message_id)
        view = View()
        
        # Assuming you want to disable all buttons in the view
        for item in message.components:  # This will not work as expected since message.components is not directly iterable in this way.
            if isinstance(item, discord.ui.Button):  # This is pseudo-code; you'll need to adapt it based on your actual need.
                # Clone or recreate the buttons you need in your view, and set them to disabled if necessary
                new_button = discord.ui.Button(style=item.style, label=item.label, custom_id=item.custom_id, disabled=True)
                view.add_item(new_button)

        await message.edit(view=view)  # Use the new view instance here
        await interaction.followup.send("Draft complete. You can now post pairings.", ephemeral=True)
    
    def split_into_teams(self):
        sign_ups_list = list(self.sign_ups.keys())
        random.shuffle(sign_ups_list)
        mid_point = len(sign_ups_list) // 2
        return sign_ups_list[:mid_point], sign_ups_list[mid_point:]
    
    async def post_pairings(self, guild):
        if not self.draft_chat_channel:
            print("Draft chat channel not set.")
            return
        
        draft_chat_channel_obj = guild.get_channel(self.draft_chat_channel)
        if not draft_chat_channel_obj:
            print("Draft chat channel not found.")
            return

        # Generate pairings
        team_a_ids, team_b_ids = self.split_into_teams()
        pairings = self.calculate_pairings(team_a_ids, team_b_ids)

        # Ensure member mentions are enabled in the channel
        await draft_chat_channel_obj.edit(slowmode_delay=0)
        
        for round_number, round_pairings in pairings.items():
            # Create an embed for the round
            embed = discord.Embed(title=f"Round {round_number} Pairings", color=discord.Color.blue())
            for player_id, opponent_id in round_pairings:
                player = guild.get_member(player_id)
                opponent = guild.get_member(opponent_id)
                player_name = player.display_name if player else 'Unknown'
                opponent_name = opponent.display_name if opponent else 'Unknown'
                # Add each pairing as a field in the embed
                embed.add_field(name=f"Match {round_pairings.index((player_id, opponent_id)) + 1}", value=f"{player_name} vs {opponent_name}", inline=False)
            
            # Send the embed for the current round
            await draft_chat_channel_obj.send(embed=embed)

        # Construct a message tagging all participants
        sign_up_tags = ' '.join([guild.get_member(user_id).mention for user_id in self.sign_ups.keys() if guild.get_member(user_id)])
        await draft_chat_channel_obj.send(f"{sign_up_tags}\nPairings Posted Above")
    
    def calculate_pairings(self, team_a_ids, team_b_ids):
        assert len(team_a_ids) == len(team_b_ids), "Teams must be of equal size"
        total_players = len(team_a_ids)
        pairings = {1: [], 2: [], 3: []}

        # Initial pairings for round 1
        for a, b in zip(team_a_ids, team_b_ids):
            pairings[1].append((a, b))

        # Generate pairings for subsequent rounds
        for round_number in [2, 3]:
            # Rotate Team B members to get new pairings
            team_b_ids = team_b_ids[1:] + team_b_ids[:1]
            for a, b in zip(team_a_ids, team_b_ids):
                pairings[round_number].append((a, b))

        return pairings
    
    def split_into_teams(self):
        sign_ups_list = list(self.sign_ups.keys())
        random.shuffle(sign_ups_list)
        mid_point = len(sign_ups_list) // 2
        team_a_ids = sign_ups_list[:mid_point]
        team_b_ids = sign_ups_list[mid_point:]
        return team_a_ids, team_b_ids
    
    async def generate_seating_order(self):
        guild = bot.get_guild(self.guild_id)
        # Assuming guild.get_member() is sufficient and members are cached
        team_a_ids, team_b_ids = self.split_into_teams()
        team_a_members = [guild.get_member(user_id) for user_id in team_a_ids]
        team_b_members = [guild.get_member(user_id) for user_id in team_b_ids]

        seating_order = []
        for i in range(max(len(team_a_members), len(team_b_members))):
            if i < len(team_a_members) and team_a_members[i]:
                seating_order.append(team_a_members[i].display_name)  # Adjusted for member objects
            if i < len(team_b_members) and team_b_members[i]:
                seating_order.append(team_b_members[i].display_name)  # Adjusted for member objects
        return seating_order
    
    async def move_message_to_draft_channel(self, bot, original_channel_id, original_message_id, draft_chat_channel_id):
        original_channel = bot.get_channel(original_channel_id)
        if not original_channel:
            print(f"Original channel {original_channel_id} not found.")
            return
        try:
            original_message = await original_channel.fetch_message(original_message_id)
        except discord.NotFound:
            print(f"Message {original_message_id} not found in channel {original_channel_id}.")
            return

        # Check if the draft chat channel is set and exists
        draft_chat_channel = bot.get_channel(draft_chat_channel_id)
        if not draft_chat_channel:
            print(f"Draft chat channel {draft_chat_channel_id} not found.")
            return

        # Send the content of the original message to the draft chat channel
        content = original_message.content
        embeds = original_message.embeds
        attachments = original_message.attachments
        files = [await attachment.to_file() for attachment in attachments]  # Convert attachments to files

        # Send content, embeds, and attachments if they exist
        if content or embeds or files:
            await draft_chat_channel.send(content=content, embeds=embeds, files=files)
        else:
            # If the original message has no content, embeds, or attachments, send a placeholder
            await draft_chat_channel.send("Moved message content not available.")

        # Delete the original message after a delay
        await asyncio.sleep(10)  # Wait for 10 seconds before deleting the message
        await original_message.delete()

class PersistentView(View):
    def __init__(self, session_id):
        super().__init__(timeout=None)
        self.session_id = session_id

        # Initialize buttons without directly setting callbacks via decorators
        self.add_item(discord.ui.Button(label="Sign Up", style=discord.ButtonStyle.green, custom_id=f"{session_id}_sign_up"))
        self.add_item(discord.ui.Button(label="Cancel Sign Up", style=discord.ButtonStyle.red, custom_id=f"{session_id}_cancel_sign_up"))
        self.add_item(discord.ui.Button(label="Cancel Draft", style=discord.ButtonStyle.grey, custom_id=f"{session_id}_cancel_draft"))
        self.add_item(discord.ui.Button(label="Randomize Teams", style=discord.ButtonStyle.blurple, custom_id=f"{session_id}_randomize_teams"))
        self.add_item(discord.ui.Button(label="Draft Complete", style=discord.ButtonStyle.green, custom_id=f"{session_id}_draft_complete", disabled=True))
        self.add_item(discord.ui.Button(label="Post Pairings", style=discord.ButtonStyle.primary, custom_id=f"{session_id}_post_pairings", disabled=True))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data['custom_id'] == f"{self.session_id}_sign_up":
            await self.sign_up_callback(interaction)
        elif interaction.data['custom_id'] == f"{self.session_id}_cancel_sign_up":
            await self.cancel_sign_up_callback(interaction)
        elif interaction.data['custom_id'] == f"{self.session_id}_cancel_draft":
            await self.cancel_draft_callback(interaction)
        elif interaction.data['custom_id'] == f"{self.session_id}_randomize_teams":
            await self.randomize_teams_callback(interaction)
        elif interaction.data['custom_id'] == f"{self.session_id}_draft_complete":
            await self.draft_complete_callback(interaction)
        elif interaction.data['custom_id'] == f"{self.session_id}_post_pairings":
            await self.post_pairings_callback(interaction)
        else:
            # If the custom_id doesn't match any known button, you may want to log this or handle it appropriately.
            # Returning False will stop the interaction from being processed further by this View.
            return False

        # Returning True to indicate the interaction has been successfully processed.
        return True

    async def sign_up_callback(self, interaction: discord.Interaction): 
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in session.sign_ups:
            # User is already signed up; inform them
            await interaction.response.send_message("You are already signed up!", ephemeral=True)
        else:
            # User is signing up
            session.sign_ups[user_id] = interaction.user.display_name
            # Confirm signup
            await interaction.response.send_message("You are now signed up.", ephemeral=True)
            # Update the draft message to reflect the new list of sign-ups
            await session.update_draft_message(interaction)
        

    async def cancel_sign_up_callback(self, interaction: discord.Interaction):
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.sign_ups:
            # User is not signed up; inform them
            await interaction.response.send_message("You are not signed up!", ephemeral=True)
        else:
            # User is canceling their sign-up
            del session.sign_ups[user_id]
            await interaction.response.send_message("Your sign-up has been canceled.", ephemeral=True)
            # Update the draft message to reflect the change in sign-ups
            await session.update_draft_message(interaction)
        

    async def draft_complete_callback(self, interaction: discord.Interaction):
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        # Splits sign-ups into teams
        team_a_ids, team_b_ids = session.split_into_teams()
        team_a_members = [guild.get_member(user_id) for user_id in team_a_ids]
        team_b_members = [guild.get_member(user_id) for user_id in team_b_ids]
        all_members = [guild.get_member(user_id) for user_id in session.sign_ups.keys()]

        # Creates channels for the teams and draft chat
        tasks = [
            session.create_team_channel(guild, "Team-A", team_a_members),
            session.create_team_channel(guild, "Team-B", team_b_members),
            session.create_team_channel(guild, "Draft-chat", all_members)
        ]
        await asyncio.gather(*tasks)

        # Update the original message to reflect the draft completion
        await session.update_draft_complete_message(interaction)
        

    async def cancel_draft_callback(self, interaction: discord.Interaction):
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        user_id = interaction.user.id
        # Check if the user is in session.sign_ups or if session.sign_ups is empty
        if user_id in session.sign_ups or not session.sign_ups:
            # Perform cancellation
            if user_id in session.sign_ups:
                del session.sign_ups[user_id]
                await interaction.response.send_message("Your sign-up has been canceled.", ephemeral=True)
                # Optionally, update the draft message to reflect the change in sign-ups
                await session.update_draft_message(interaction)
            if not session.sign_ups:
                # If there are no more sign-ups, consider deleting the draft session
                await interaction.message.delete()
                sessions.pop(self.session_id, None)
                await interaction.response.send_message("The draft has been canceled.", ephemeral=True)
        else:
            # If the user is not signed up and there are sign-ups present, do not allow cancellation
            await interaction.response.send_message("You cannot cancel this draft because you are not signed up or there are active sign-ups.", ephemeral=True)

        

    async def randomize_teams_callback(self, interaction: discord.Interaction):
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        if len(session.sign_ups) < 2:  # Ensure there are enough sign-ups to form teams
            await interaction.response.send_message("Not enough sign-ups to randomize teams.", ephemeral=True)
            return

        team_a_ids, team_b_ids = session.split_into_teams()
        team_a = [session.sign_ups[user_id] for user_id in team_a_ids]
        team_b = [session.sign_ups[user_id] for user_id in team_b_ids]
        seating_order = await session.generate_seating_order()

        # Create the embed message for the draft
        embed = discord.Embed(
            title="Draft is Ready!",
            description=f"**Team A**:\n" + "\n".join(team_a) +
                        "\n\n**Team B**:\n" + "\n".join(team_b) +
                        "\n\n**Seating Order:**\n" + " -> ".join(seating_order) +
                        "\n\nNote: Host of Draftmancer must manually adjust seating as per above" +
                        f"\n\n**Draftmancer Session**: **[Join Here]({session.draft_link})**",
            color=discord.Color.gold()
        )

        # Iterate over the view's children (buttons) to update their disabled status
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                # Enable "Post Pairings" and "Draft Complete" buttons
                if item.custom_id in [f"{self.session_id}_post_pairings", f"{self.session_id}_draft_complete"]:
                    item.disabled = False
                else:
                    # Disable all other buttons
                    item.disabled = True

        # Respond with the embed and updated view
        await interaction.response.edit_message(embed=embed, view=self)

        
    
    async def post_pairings_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Ensure there's enough time for operations
        
        session = sessions.get(self.session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        # Move the original draft announcement message before posting pairings
        original_message_id = session.message_id
        original_channel_id = interaction.channel.id  # Assuming the original message is in the same channel as the interaction
        draft_chat_channel_id = session.draft_chat_channel
        await session.move_message_to_draft_channel(bot, original_channel_id, original_message_id, draft_chat_channel_id)

        # Generate and post pairings
        team_a_ids, team_b_ids = session.split_into_teams()
        pairings = session.calculate_pairings(team_a_ids, team_b_ids)
        await session.post_pairings(interaction.guild)

        await interaction.followup.send("Pairings have been posted to the draft chat channel and the original message moved.", ephemeral=True)
        


    #@discord.ui.button(label="Sign Up", style=discord.ButtonStyle.green, custom_id="persistent_sign_up")
    async def sign_up(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.sign_up_callback(interaction, interaction.user.id)

    #@discord.ui.button(label="Cancel Sign Up", style=discord.ButtonStyle.red, custom_id="persistent_cancel_sign_up")
    async def cancel_sign_up(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cancel_sign_up_callback(interaction, interaction.user.id)
        
    #@discord.ui.button(label="Draft Complete", style=discord.ButtonStyle.green, custom_id="persistent_draft_complete")
    async def draft_complete(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.draft_complete_callback(interaction)

    #@discord.ui.button(label="Cancel Draft", style=discord.ButtonStyle.grey, custom_id="persistent_cancel_draft")
    async def cancel_draft(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cancel_draft_callback(interaction)

    #@discord.ui.button(label="Randomize Teams", style=discord.ButtonStyle.blurple, custom_id="persistent_randomize_teams")
    async def randomize_teams(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.randomize_teams_callback(interaction)

    #@discord.ui.button(label="Post Pairings", style=discord.ButtonStyle.primary, custom_id="persistent_post_pairings")
    async def post_pairings(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.post_pairings_callback(interaction)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.slash_command(name='startdraft', description='Start a Magic: The Gathering draft table', guild_id=None)
async def start_draft(interaction: discord.Interaction):
    await interaction.response.defer()

    draft_start_time = datetime.now().timestamp()
    session_id = f"{interaction.user.id}-{int(draft_start_time)}"
    draft_id = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
    draft_link = f"https://draftmancer.com/?session=DB{draft_id}"

    session = DraftSession(session_id)
    session.guild_id = interaction.guild_id
    session.draft_link = draft_link
    session.draft_id = draft_id
    session.draft_start_time = draft_start_time

    sessions[session_id] = session

    cube_drafter_role = discord.utils.get(interaction.guild.roles, name="Cube Drafter")
    ping_message = f"{cube_drafter_role.mention if cube_drafter_role else 'Cube Drafter'} Vintage Cube Draft Queue Open!"
    await interaction.followup.send(ping_message, ephemeral=False)

    embed = discord.Embed(
        title=f"Vintage Cube Team Draft Queue - Started <t:{int(draft_start_time)}:R>",
        description=f"\n**Click Sign Up to Join!** \n\nNote: Draftmancer settings, such as importing the cube, must still be managed by the host. Seating order will be determined in the next step.\n\n**Draftmancer Session**: **[Join Here]({draft_link})**",
        color=discord.Color.dark_magenta()
    )
    embed.add_field(name="Sign-Ups", value="No players yet.", inline=False)
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1186757246936424558/1217295353972527176/131.png")

    view = PersistentView(session_id)
  
    message = await interaction.followup.send(embed=embed, view=view)
    
    session.draft_message_id = message.id
    session.message_id = message.id
    
    await session.schedule_session_cleanup()

    # Pin the message to the channel
    await message.pin()

bot.run(TOKEN)
