from datetime import datetime, timedelta
from sqlalchemy import select
import discord
import random
from session import DraftSession, AsyncSessionLocal, get_draft_session
from views import PersistentView

class CubeSelectionModal(discord.ui.Modal):
    def __init__(self, session_type, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_type = session_type
        self.add_inputs()
        
    def add_inputs(self):
        cube_placeholder = "LSVCube, AlphaFrog, MOCS24" if self.session_type == "swiss" else "LSVCube, AlphaFrog, MOCS24, or your choice"
        self.add_item(discord.ui.TextInput(label="Cube Name", placeholder=cube_placeholder, custom_id="cube_name_input"))
        if self.session_type == "premade":
            self.add_item(discord.ui.TextInput(label="Team A Name", placeholder="Team A Name", custom_id="team_a_input"))
            self.add_item(discord.ui.TextInput(label="Team B Name", placeholder="Team B Name", custom_id="team_b_input"))

    async def callback(self, interaction: discord.Interaction):
        if self.session_type == "schedule":
            await self.handle_schedule(interaction)
        else:
            await self.setup_draft(interaction)

    async def handle_schedule(self, interaction):
        from league import InitialPostView
        initial_view = InitialPostView(command_type=self.session_type, team_id=1, cube_choice=self.children[0].value)
        await interaction.response.send_message("Post a scheduled draft. Select a Timezone.", view=initial_view, ephemeral=True)

    async def setup_draft(self, interaction):
        bot = interaction.client
        session_id, draft_id, draft_link, draft_start_time = self.generate_session_details(interaction)
        new_draft_session = await self.create_draft_session(interaction, session_id, draft_id, draft_link, draft_start_time)
        embed = self.build_embed(draft_start_time, draft_link, self.children[0].value)

        message = await interaction.followup.send(embed=embed, view=await self.build_persistent_view(bot, session_id))
        await self.update_draft_session(new_draft_session, message)
        await message.pin()

    def generate_session_details(self, interaction):
        draft_start_time = datetime.now().timestamp()
        session_id = f"{interaction.user.id}-{int(draft_start_time)}"
        draft_id = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
        draft_link = f"https://draftmancer.com/?session=DB{draft_id}"
        return session_id, draft_id, draft_link, draft_start_time

    async def create_draft_session(self, interaction, session_id, draft_id, draft_link, draft_start_time):
        cube_option = self.children[0].value or "MTG"
        team_a_name, team_b_name = None, None
        if self.session_type == "premade":
            team_a_name, team_b_name = self.children[1].value, self.children[2].value

        async with AsyncSessionLocal() as session:
            async with session.begin():
                new_draft_session = DraftSession(
                    session_id=session_id,
                    guild_id=str(interaction.guild_id),
                    draft_link=draft_link,
                    draft_id=draft_id,
                    draft_start_time=datetime.now(),
                    deletion_time=datetime.now() + timedelta(hours=3),
                    session_type=self.session_type,
                    premade_match_id=None if self.session_type != "swiss" else 9000,
                    team_a_name=team_a_name,
                    team_b_name=team_b_name,
                    tracked_draft=True,
                    cube=cube_option
                )
                session.add(new_draft_session)
                await session.commit()
        return new_draft_session

    def build_embed(self, draft_start_time, draft_link, cube_name):
        title, description, color, team_a, team_b = self.get_embed_content(draft_start_time, draft_link, cube_name)
        embed = discord.Embed(title=title, description=description, color=color)
        if team_a and team_b:
            embed.add_field(name=team_a, value="No players yet.", inline=False)
            embed.add_field(name=team_b, value="No players yet.", inline=False)
        else:
            embed.add_field(name="Sign-Ups", value="No players yet.", inline=False)
        embed.set_thumbnail(url=self.get_thumbnail_url())
        return embed

    def get_embed_content(self, draft_start_time, draft_link, cube_name):
        cube_option = cube_name or "MTG"
        if self.session_type == "random":
            title = f"Looking for Players! {cube_option} Random Team Draft - Queue Opened <t:{int(draft_start_time)}:R>"
            description = self.get_random_draft_description(draft_link, cube_option)
            return title, description, discord.Color.dark_magenta(), None, None
        elif self.session_type == "swiss":
            title = f"AlphaFrog Prelims: Looking for Players! Queue Opened <t:{int(draft_start_time)}:R>"
            description = self.get_swiss_draft_description(draft_link, cube_option)
            return title, description, discord.Color.dark_gold(), None, None
        elif self.session_type == "premade":
            title = f"{cube_option} Premade Team Draft Queue - Started <t:{int(draft_start_time)}:R>"
            description = self.get_premade_draft_description(draft_link, cube_option)
            return title, description, discord.Color.blue(), "Team A", "Team B"

    def get_random_draft_description(self, draft_link, cube_option):
        return f"**Chosen Cube: [{cube_option}](https://cubecobra.com/cube/list/{cube_option})** \n**Draftmancer Session**: **[Join Here]({draft_link})**"

    def get_swiss_draft_description(self, draft_link, cube_option):
        return f"Swiss 8 player draft. Turn off randomized seating. **Weekly Cube: [{cube_option}](https://cubecobra.com/cube/list/{cube_option})** \n**Draftmancer Session**: **[Join Here]({draft_link})**"

    def get_premade_draft_description(self, draft_link, cube_option):
        return f"**Chosen Cube: [{cube_option}](https://cubecobra.com/cube/list/{cube_option})** \n**Draftmancer Session**: **[Join Here]({draft_link})**"

    def get_thumbnail_url(self):
        return "https://cdn.discordapp.com/attachments/1186757246936424558/1217295353972527176/131.png"

    async def build_persistent_view(self, bot, session_id):
        draft_session = await get_draft_session(session_id)
        if draft_session:
            return PersistentView(
                bot=bot,
                draft_session_id=draft_session.session_id,
                session_type=self.session_type,
                team_a_name=getattr(draft_session, 'team_a_name', None),
                team_b_name=getattr(draft_session, 'team_b_name', None)
            )

    async def update_draft_session(self, new_draft_session, message):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(DraftSession).filter_by(session_id=new_draft_session.session_id))
                updated_session = result.scalars().first()
                if updated_session:
                    updated_session.message_id = str(message.id)
                    updated_session.draft_channel_id = str(message.channel.id)
                    session.add(updated_session)
                    await session.commit()
