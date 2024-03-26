import discord
from datetime import datetime
from sqlalchemy import update
from session import AsyncSessionLocal, get_draft_session, DraftSession


class PersistentView(discord.ui.View):
    def __init__(self, bot, draft_session_id, session_type, team_a_name=None, team_b_name=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.draft_session_id = draft_session_id
        self.session_type = session_type
        self.team_a_name = team_a_name
        self.team_b_name = team_b_name
        self.add_buttons()


    def add_buttons(self):
        if self.session_type == "random":
            self.add_item(self.create_button("Sign Up", "green", f"sign_up_{self.draft_session_id}", self.sign_up_callback))
            self.add_item(self.create_button("Cancel Sign Up", "red", f"cancel_sign_up_{self.draft_session_id}", self.cancel_sign_up_callback))
            self.add_item(self.create_button("Create Teams", "blurple", f"randomize_teams_{self.draft_session_id}", self.randomize_teams_callback))
        elif self.session_type == "premade":
            self.add_item(self.create_button(self.team_a_name, "green", f"Team_A_{self.draft_session_id}", self.team_assignment_callback))
            self.add_item(self.create_button(self.team_b_name, "red", f"Team_B_{self.draft_session_id}", self.team_assignment_callback))
            self.add_item(self.create_button("Generate Seating Order", "blurple", f"generate_seating_{self.draft_session_id}", self.randomize_teams_callback))
        # self.add_item(self.create_button("Cancel Draft", "grey", "cancel_draft", self.cancel_draft_callback))
        # self.add_item(self.create_button("Remove User", "grey", "remove_user", self.remove_user_button_callback))
        # self.add_item(self.create_button("Ready Check", "green", "ready_check", self.ready_check_callback))
        # self.add_item(self.create_button("Create Rooms & Post Pairings", "primary", "create_rooms_pairings", self.create_rooms_pairings_callback, disabled=True))


    def create_button(self, label, style, custom_id, custom_callback, disabled=False):
        style = getattr(discord.ButtonStyle, style)
        button = CallbackButton(label=label, style=style, custom_id=custom_id, custom_callback=custom_callback, disabled=disabled)
        return button



    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        session_exists = await get_draft_session(self.draft_session_id) is not None
        if not session_exists:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
        return session_exists
    
 
    async def sign_up_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Fetch the current draft session to ensure it's up to date
        draft_session = await get_draft_session(self.draft_session_id)
        if not draft_session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return
        
        sign_ups = draft_session.sign_ups or {}

        # Check if the sign-up list is already full
        if len(sign_ups) >= 8:
            await interaction.response.send_message("The sign-up list is already full. No more players can sign up.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if user_id in sign_ups:
            # User is already signed up; inform them
            await interaction.response.send_message("You are already signed up!", ephemeral=True)
        else:
            # User is signing up
            sign_ups[user_id] = interaction.user.display_name

            # Start an asynchronous database session
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Directly update the 'sign_ups' of the draft session
                    await session.execute(
                        update(DraftSession).
                        where(DraftSession.session_id == self.draft_session_id).
                        values(sign_ups=sign_ups)
                    )
                    await session.commit()

            # After committing, re-fetch the draft session to work with updated data
            draft_session_updated = await get_draft_session(self.draft_session_id)
            if not draft_session_updated:
                print("Failed to fetch updated draft session after sign-up.")
                return

            # Confirm signup with draft link
            draft_link = draft_session_updated.draft_link
            signup_confirmation_message = f"You are now signed up. Join Here: {draft_link}"
            await interaction.response.send_message(signup_confirmation_message, ephemeral=True)

            # Update the draft message to reflect the new list of sign-ups
            await update_draft_message(interaction.client, self.draft_session_id)


    async def cancel_sign_up_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        draft_session = await get_draft_session(self.draft_session_id)
        if not draft_session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return
        
        sign_ups = draft_session.sign_ups or {}
        user_id = str(interaction.user.id)
        if user_id not in sign_ups:
            # User is not signed up; inform them
            await interaction.response.send_message("You are not signed up!", ephemeral=True)
        else:
            # User is canceling their sign-up
            del draft_session.sign_ups[user_id]

            # Start an asynchronous database session
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Directly update the 'sign_ups' of the draft session
                    await session.execute(
                        update(DraftSession).
                        where(DraftSession.session_id == self.draft_session_id).
                        values(sign_ups=sign_ups)
                    )
                    await session.commit()
            cancel_message = "You're sign up has been canceled!"
            await interaction.response.send_message(cancel_message, ephemeral=True)

            # After committing, re-fetch the draft session to work with updated data
            draft_session_updated = await get_draft_session(self.draft_session_id)
            if not draft_session_updated:
                print("Failed to fetch updated draft session after sign-up.")
                return
            
            # Update the draft message to reflect the new list of sign-ups
            await update_draft_message(interaction.client, self.draft_session_id)
    

    async def randomize_teams_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        session = await get_draft_session(self.draft_session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return
        session.teams_start_time = datetime.now().timestamp()
        session.session_stage = 'teams'
        # Check session type and prepare teams if necessary
        if session.session_type == 'random':
            from methods import split_into_teams
            await split_into_teams(session.session_id)
            session = await get_draft_session(self.draft_session_id)

        # Generate names for display using the session's sign_ups dictionary
        team_a_display_names = [session.sign_ups[user_id] for user_id in session.team_a]
        team_b_display_names = [session.sign_ups[user_id] for user_id in session.team_b]
        
        from methods import generate_seating_order
        seating_order = await generate_seating_order(bot, session)

        # Create the embed message for displaying the teams and seating order
        embed = discord.Embed(
            title=f"Draft-{session.draft_id} is Ready!",
            description=f"**Draftmancer Session**: **[Join Here]({session.draft_link})** \n" +
                        "Host of Draftmancer must manually adjust seating as per below. **TURN OFF RANDOM SEATING SETTING IN DRAFMANCER**" +
                        "\n\n**AFTER THE DRAFT**, select Create Chat Rooms (give it five seconds to generate rooms) then select Post Pairings" +
                        "\nPost Pairings will take about 10 seconds to process. Only press once.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Team A" if session.session_type == "random" else f"{session.team_a_name}", value="\n".join(team_a_display_names), inline=True)
        embed.add_field(name="Team B" if session.session_type == "random" else f"{session.team_b_name}", value="\n".join(team_b_display_names), inline=True)
        embed.add_field(name="Seating Order", value=" -> ".join(seating_order), inline=False)

        # Iterate over the view's children (buttons) to update their disabled status
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                # Enable "Create Rooms" and "Cancel Draft" buttons
                if item.custom_id == f"{self.draft_session_id}_create_rooms_pairings" or item.custom_id == f"{self.draft_session_id}_cancel_draft":
                    item.disabled = False
                else:
                    # Disable all other buttons
                    item.disabled = True


        # Respond with the embed and updated view
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def team_assignment_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await get_draft_session(self.draft_session_id)
        if not session:
            await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
            return

        user_id = str(interaction.user.id)  # Ensure string format for consistency
        custom_id = button.custom_id
        user_name = interaction.user.display_name

        # Initialize variables to avoid UnboundLocalError
        primary_team = secondary_team = primary_key = secondary_key = None

        # Determine which team the user is trying to interact with
        if "Team_A" in custom_id:
            primary_team, secondary_team = session.team_a or [], session.team_b or []
            primary_key, secondary_key = "team_a", "team_b"
        elif "Team_B" in custom_id:
            primary_team, secondary_team = session.team_b or [], session.team_a or []
            primary_key, secondary_key = "team_b", "team_a"

        # Safety check if the button custom_id doesn't correctly specify a team
        if primary_team is None or secondary_team is None:
            await interaction.response.send_message("An error occurred. Unable to determine the team.", ephemeral=True)
            return

        sign_ups = session.sign_ups or {}

        # Process the team assignment
        if user_id in primary_team:
            # User wants to leave the primary team
            primary_team.remove(user_id)
            action_message = f"You have been removed from {getattr(session, primary_key + '_name', primary_key)}."
        else:
            if user_id in secondary_team:
                # User switches teams
                secondary_team.remove(user_id)
            primary_team.append(user_id)
            action_message = f"You have been added to {getattr(session, primary_key + '_name', primary_key)}."

        # Update or add user in the sign-ups dictionary
        sign_ups[user_id] = user_name

        # Persist changes to the database
        async with AsyncSessionLocal() as db_session:
            async with db_session.begin():
                await db_session.execute(update(DraftSession)
                                        .where(DraftSession.session_id == session.session_id)
                                        .values({primary_key: primary_team, secondary_key: secondary_team, 'sign_ups': sign_ups}))
                await db_session.commit()

        await interaction.response.send_message(action_message, ephemeral=True)

        # Optionally update the message view to reflect the new team compositions
        await self.update_team_view(interaction)

    async def update_team_view(self, interaction: discord.Interaction):
        session = await get_draft_session(self.draft_session_id)
        if not session:
            print("Draft session not found.")
            return

        channel = self.bot.get_channel(int(session.draft_channel_id))
        if channel is None:
            print(f"Channel not found for draft session ID {self.draft_session_id}.")
            return

        message = await channel.fetch_message(int(session.message_id))
        embed = message.embeds[0]  # Assuming there's only one embed attached to the message

        # Assume team_a_names and team_b_names are prepared earlier in the method
        team_a_names = [session.sign_ups.get(str(user_id), "Unknown User") for user_id in (session.team_a or [])]
        team_b_names = [session.sign_ups.get(str(user_id), "Unknown User") for user_id in (session.team_b or [])]

        # Find the index of the Team A and Team B fields in the embed
        team_a_index = next((i for i, e in enumerate(embed.fields) if e.name.startswith(session.team_a_name or "Team A")), None)
        team_b_index = next((i for i, e in enumerate(embed.fields) if e.name.startswith(session.team_b_name or "Team B")), None)

        # Update the fields if found
        if team_a_index is not None:
            embed.set_field_at(team_a_index, name=f"{session.team_a_name} ({len(session.team_a or [])}):", value="\n".join(team_a_names) if team_a_names else "No players yet.", inline=True)
        if team_b_index is not None:
            embed.set_field_at(team_b_index, name=f"{session.team_b_name} ({len(session.team_b or [])}):", value="\n".join(team_b_names) if team_b_names else "No players yet.", inline=True)

        # Edit the original message with the updated embed
        await message.edit(embed=embed)


class CallbackButton(discord.ui.Button):
    def __init__(self, *, label, style, custom_id, custom_callback, disabled=False):
        super().__init__(label=label, style=style, custom_id=custom_id, disabled=disabled)
        self.custom_callback = custom_callback  

    async def callback(self, interaction: discord.Interaction):
        await self.custom_callback(interaction, self)


# class PersistentView(discord.ui.View):
#     def __init__(self, draft_session):
#         super().__init__(timeout=None)
#         self.draft_session = draft_session
        
#         if self.draft_session.session_type == 'premade':
#             self.add_item(discord.ui.Button(label=f"{self.draft_session.team_a_name}", style=discord.ButtonStyle.green, custom_id=f"{self.draft_session.session_id}_Team_A"))
#             self.add_item(discord.ui.Button(label=f"{self.draft_session.team_b_name}", style=discord.ButtonStyle.red, custom_id=f"{self.draft_session.session_id}_Team_B"))
#             self.add_item(discord.ui.Button(label="Generate Seating Order", style=discord.ButtonStyle.blurple, custom_id=f"{self.draft_session.session_id}_generate_seating"))
#         elif self.draft_session.session_type == 'random':
#             self.add_item(discord.ui.Button(label="Sign Up", style=discord.ButtonStyle.green, custom_id=f"{self.draft_session.session_id}_sign_up"))
#             self.add_item(discord.ui.Button(label="Cancel Sign Up", style=discord.ButtonStyle.red, custom_id=f"{self.draft_session.session_id}_cancel_sign_up"))
#             self.add_item(discord.ui.Button(label="Create Teams", style=discord.ButtonStyle.blurple, custom_id=f"{self.draft_session.session_id}_randomize_teams"))
                
#         self.add_item(discord.ui.Button(label="Cancel Draft", style=discord.ButtonStyle.grey, custom_id=f"{self.draft_session.session_id}_cancel_draft"))
#         self.add_item(discord.ui.Button(label="Remove User", style=discord.ButtonStyle.grey, custom_id=f"{self.draft_session.session_id}_remove_user"))
#         self.add_item(discord.ui.Button(label="Ready Check", style=discord.ButtonStyle.green, custom_id=f"{self.draft_session.session_id}_ready_check"))
#         self.add_item(discord.ui.Button(label="Create Rooms & Post Pairings", style=discord.ButtonStyle.primary, custom_id=f"{self.draft_session.session_id}_create_rooms_pairings", disabled=True))

#     async def interaction_check(self, interaction: discord.Interaction) -> bool:
#         custom_id = interaction.data['custom_id']
#             # If none of the conditions match, the interaction is not recognized and you might want to log this case.
#             return False

    # async def create_rooms_pairings_callback(self, interaction: discord.Interaction):
    #     # Defer the response to ensure there's enough time for operations
    #     await interaction.response.defer()

    #     session = sessions.get(self.session_id)
    #     if not session:
    #         await interaction.followup.send("The draft session could not be found.", ephemeral=True)
    #         return
        
    #     # Check if the process is already running
    #     if session.are_rooms_processing:
    #     # Process is already running, so we inform the user and do nothing else
    #         await interaction.response.send_message("The rooms and pairings are currently being created. Please wait.", ephemeral=True)
    #         return

    #     # Set the flag to indicate the process is running
    #     session.are_rooms_processing = True

    #     session.session_stage = 'pairings'

    #     guild = interaction.guild

    #     # Immediately disable the "Create Rooms & Post Pairings" button to prevent multiple presses
    #     for child in self.children:
    #         if isinstance(child, discord.ui.Button) and child.label == "Create Rooms & Post Pairings":
    #             child.disabled = True
    #             break

    #     await interaction.edit_original_response(view=self)  # Now correctly referring to 'self'

    #     # Execute tasks to create chat channels
    #     team_a_members = [guild.get_member(user_id) for user_id in session.team_a]
    #     team_b_members = [guild.get_member(user_id) for user_id in session.team_b]
    #     all_members = team_a_members + team_b_members

    #     tasks = [
    #         session.create_team_channel(guild, "Draft", all_members, session.team_a, session.team_b), 
    #         session.create_team_channel(guild, "Team-A", team_a_members, session.team_a, session.team_b),
    #         session.create_team_channel(guild, "Team-B", team_b_members, session.team_a, session.team_b)
    #     ]
    #     await asyncio.gather(*tasks)
    #     draft_chat_channel_id = session.draft_chat_channel
    #     # Post a sign-up ping in the draft chat channel
    #     draft_chat_channel = guild.get_channel(draft_chat_channel_id)
    #     if draft_chat_channel:
    #         sign_up_tags = ' '.join([f"<@{user_id}>" for user_id in session.sign_ups.keys()])
    #         await draft_chat_channel.send(f"Pairing posted below. Good luck in your matches! {sign_up_tags}")

    #     original_message_id = session.message_id
    #     original_channel_id = interaction.channel.id  
    #     session.pairings = session.calculate_pairings()
    #     await session.move_message_to_draft_channel(bot, original_channel_id, original_message_id, draft_chat_channel_id)
    
    #     # Execute Post Pairings

    #     await session.post_pairings(guild, session.pairings)
        
    
    # async def ready_check_callback(self, interaction: discord.Interaction):
    #     session = sessions.get(self.session_id)
    #     if session:
    #         # Check if the user is in the sign-up list
    #         if interaction.user.id in session.sign_ups:
    #             # Proceed with the ready check
    #             await session.initiate_ready_check(interaction)

    #             # Disable the "Ready Check" button after use
    #             for item in self.children:
    #                 if isinstance(item, discord.ui.Button) and item.custom_id == f"{self.session_id}_ready_check":
    #                     item.disabled = True
    #                     break  # Stop the loop once the button is found and modified

    #             # Ensure the view reflects the updated state with the button disabled
    #             await interaction.edit_original_response(view=self)
    #         else:
    #             # Inform the user they're not in the sign-up list, hence can't initiate a ready check
    #             await interaction.response.send_message("You must be signed up to initiate a ready check.", ephemeral=True)
    #     else:
    #         await interaction.response.send_message("Session not found.", ephemeral=True)


    # async def team_assignment_callback(self, interaction: discord.Interaction):
    #     session = sessions.get(self.session_id)
    #     if not session:
    #         await interaction.response.send_message("Session not found.", ephemeral=True)
    #         return

    #     user_id = interaction.user.id
    #     custom_id = interaction.data["custom_id"]
    #     user_name = interaction.user.display_name

    #     if "_Team_A" in custom_id:
    #         primary_team_key = "team_a"
    #         secondary_team_key = "team_b"
    #     elif "_Team_B" in custom_id:
    #         primary_team_key = "team_b"
    #         secondary_team_key = "team_a"
    #     else:
    #         await interaction.response.send_message("An error occurred.", ephemeral=True)
    #         return

    #     primary_team = getattr(session, primary_team_key, [])
    #     secondary_team = getattr(session, secondary_team_key, [])

    #     # Add or remove the user from the team lists
    #     if user_id in primary_team:
    #         primary_team.remove(user_id)
    #         del session.sign_ups[user_id]  # Remove from sign-ups dictionary
    #         action_message = f"You have been removed from a team."
    #     else:
    #         if user_id in secondary_team:
    #             secondary_team.remove(user_id)
    #             del session.sign_ups[user_id]  # Remove from sign-ups dictionary before re-adding to correct team
    #         primary_team.append(user_id)
    #         session.sign_ups[user_id] = user_name  # Add/update in sign-ups dictionary
    #         action_message = f"You have been added to a team."

    #     # Update session attribute to reflect changes
    #     setattr(session, primary_team_key, primary_team)
    #     setattr(session, secondary_team_key, secondary_team)

    #     await interaction.response.send_message(action_message, ephemeral=True)
    #     await session.update_team_view(interaction)

    

    # async def cancel_draft_callback(self, interaction: discord.Interaction):
    #     session = sessions.get(self.session_id)
    #     if not session:
    #         await interaction.response.send_message("The draft session could not be found.", ephemeral=True)
    #         return

    #     user_id = interaction.user.id
    #     # Check if the user is in session.sign_ups or if session.sign_ups is empty
    #     if user_id in session.sign_ups or not session.sign_ups:
    #         # Delete the draft message and remove the session
    #         await interaction.message.delete()
    #         sessions.pop(self.session_id, None)
    #         await interaction.response.send_message("The draft has been canceled.", ephemeral=True)
    #     else:
    #         # If the user is not signed up and there are sign-ups present, inform the user
    #         await interaction.response.send_message("You cannot cancel this draft because you are not signed up.", ephemeral=True)
    
    # async def remove_user_button_callback(self, interaction: discord.Interaction):
    #     session = sessions.get(self.session_id)
    #     if not session:
    #         await interaction.response.send_message("Session not found.", ephemeral=True)
    #         return

    #     # Check if the user initiating the remove action is in the sign_ups
    #     if interaction.user.id not in session.sign_ups:
    #         await interaction.response.send_message("You are not authorized to remove users.", ephemeral=True)
    #         return

    #     # If the session exists and has sign-ups, and the user is authorized, proceed
    #     if session.sign_ups:
    #         options = [SelectOption(label=user_name, value=str(user_id)) for user_id, user_name in session.sign_ups.items()]
    #         view = UserRemovalView(session_id=self.session_id)
    #         await interaction.response.send_message("Select a user to remove:", view=view, ephemeral=True)
    #     else:
    #         await interaction.response.send_message("No users to remove.", ephemeral=True)

    
            
async def update_draft_message(bot, session_id):
    draft_session = await get_draft_session(session_id)
    if not draft_session:
        print("Failed to fetch draft session for updating the message.")
        return

    channel_id = int(draft_session.draft_channel_id)
    message_id = int(draft_session.message_id)
    channel = bot.get_channel(channel_id)

    if not channel:
        print(f"Channel with ID {channel_id} not found.")
        return

    try:
        message = await channel.fetch_message(message_id)
        embed = message.embeds[0]  # Assuming there's at least one embed in the message
        sign_ups_field_name = "Sign-Ups:"
        sign_ups_str = '\n'.join([f"{name}" for name in draft_session.sign_ups.values()]) if draft_session.sign_ups else 'No players yet.'
        embed.set_field_at(0, name=sign_ups_field_name, value=sign_ups_str, inline=False)
        await message.edit(embed=embed)
    except Exception as e:
        print(f"Failed to update message for session {session_id}. Error: {e}")
