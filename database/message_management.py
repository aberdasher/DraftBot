from typing import Optional
import discord
from sqlalchemy import JSON, Column, Integer, String, Boolean, Float, select
from sqlalchemy.ext.asyncio import AsyncSession
from views import PersistentView
from database.models_base import Base
from session import AsyncSessionLocal, DraftSession, get_draft_session
from loguru import logger
import time
import asyncio

STICKY_MESSAGE_BUFFER = 8
INACTIVITY_THRESHOLD = 120  # 120 seconds (2 minutes) of inactivity
INACTIVITY_CHECK_INTERVAL = 60  # Check for inactive channels every 60 seconds

class Message(Base):
    """Represents a message stored in the database, potentially a sticky message."""
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(String(64), nullable=False)
    channel_id = Column(String(64), nullable=False)
    message_id = Column(String(64), nullable=False)
    content = Column(String, nullable=False)
    view_metadata = Column(JSON, nullable=True)
    is_sticky = Column(Boolean, default=False)
    message_count = Column(Integer, default=0)
    last_activity = Column(Float, default=0.0)  # Timestamp of last message in channel

    def __repr__(self) -> str:
        return (
            f"<Message(guild_id={self.guild_id}, channel_id={self.channel_id}, "
            f"message_id={self.message_id}, is_sticky={self.is_sticky})>"
        )


async def fetch_sticky_message(channel_id: str, session: AsyncSession) -> Optional[Message]:
    """Fetches the sticky message for a given channel from the database."""
    result = await session.execute(
        select(Message).filter_by(channel_id=channel_id, is_sticky=True)
    )
    return result.scalars().first()


async def fetch_all_sticky_messages(session: AsyncSession) -> list[Message]:
    """Fetches all sticky messages from the database."""
    result = await session.execute(
        select(Message).filter_by(is_sticky=True)
    )
    return result.scalars().all()


async def update_draft_session_message(draft_session_id: str, message_id: str, session: AsyncSession) -> None:
    """Updates the draft session with a new sticky message ID."""
    draft_session = await get_draft_session(draft_session_id)
    if not draft_session:
        logger.error(f"DraftSession with ID {draft_session_id} not found in database.")
        return

    draft_session.message_id = message_id
    session.add(draft_session)
    await session.commit()


async def handle_sticky_message_update(sticky_message: Message, bot: discord.Client, session: AsyncSession) -> None:
    """Handles the process of updating and pinning the sticky message in Discord."""
    # Check if message_count threshold is met before doing anything
    if sticky_message.message_count < STICKY_MESSAGE_BUFFER:
        logger.info(f"Not enough messages ({sticky_message.message_count}/{STICKY_MESSAGE_BUFFER}) to update sticky message in channel {sticky_message.channel_id}")
        return

    draft_session_id = sticky_message.view_metadata.get("draft_session_id")
    if not draft_session_id:
        logger.error("Missing draft_session_id in view_metadata.")
        return

    # Fetch the current draft session to get its current state
    draft_session = await get_draft_session(draft_session_id)
    if not draft_session:
        logger.error(f"DraftSession with ID {draft_session_id} not found.")
        return
    
    # Update the view metadata with the current session stage
    view_metadata = sticky_message.view_metadata.copy()
    view_metadata["session_stage"] = draft_session.session_stage
    
    channel = await bot.fetch_channel(int(sticky_message.channel_id))
    try:
        old_message = await channel.fetch_message(int(sticky_message.message_id))
        embed = old_message.embeds[0] if old_message.embeds else None
    except discord.NotFound:
        logger.warning(f"Sticky message with ID {sticky_message.message_id} not found.")
        return

    # Create view with updated metadata including the current session stage
    view = PersistentView.from_metadata(bot, view_metadata)
    new_message = await channel.send(content=sticky_message.content, embed=embed, view=view)
    await new_message.pin()
    logger.info(f"Pinned new sticky message with ID {new_message.id} in channel {channel.id}")

    # Save the new message ID to the sticky_message record
    old_message_id = sticky_message.message_id
    sticky_message.message_id = str(new_message.id)
    sticky_message.view_metadata = view_metadata  # Save the updated metadata
    sticky_message.message_count = 0  # Reset message count after update
    sticky_message.last_activity = time.time()  # Reset last activity timestamp
    
    # Update the draft session directly without calling update_draft_session_message
    if draft_session:
        draft_session.message_id = str(new_message.id)
        session.add(draft_session)
    else:
        logger.error(f"DraftSession with ID {draft_session_id} not found in database.")
    
    # Commit all changes at once
    await session.commit()

    # Only after all database changes are committed, delete the old message
    try:
        await old_message.delete()
        logger.info(f"Deleted old sticky message with ID {old_message_id}")
    except discord.NotFound:
        logger.info(f"Old message {old_message_id} was already deleted")


async def check_channels_for_inactivity(bot: discord.Client) -> None:
    """Background task that periodically checks all channels with sticky messages for inactivity."""
    await bot.wait_until_ready()
    logger.info("Starting background task to check for inactive channels")
    
    while not bot.is_closed():
        current_time = time.time()
        async with AsyncSessionLocal() as session:
            sticky_messages = await fetch_all_sticky_messages(session)
            
            for sticky_message in sticky_messages:
                elapsed_time = current_time - sticky_message.last_activity
                
                if elapsed_time >= INACTIVITY_THRESHOLD and sticky_message.message_count >= STICKY_MESSAGE_BUFFER:
                    logger.info(f"Channel {sticky_message.channel_id} has been inactive for {elapsed_time:.2f}s with {sticky_message.message_count} messages. Updating sticky message.")
                    await handle_sticky_message_update(sticky_message, bot, session)
        
        # Wait before checking again
        await asyncio.sleep(INACTIVITY_CHECK_INTERVAL)


async def setup_sticky_handler(bot: discord.Client) -> None:
    """Sets up event handlers for managing sticky messages in Discord."""
    logger.info("Setting up sticky message handler")
    
    # Start the background task for checking inactive channels
    bot.loop.create_task(check_channels_for_inactivity(bot))

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return

        current_time = time.time()
        async with AsyncSessionLocal() as session:
            sticky_message = await fetch_sticky_message(str(message.channel.id), session)
            if not sticky_message:
                return

            # Update the last activity timestamp for this channel
            sticky_message.last_activity = current_time
            
            # Increment message count
            sticky_message.message_count += 1
            
            logger.info(f"Updated channel {message.channel.id} activity. Count: {sticky_message.message_count}/{STICKY_MESSAGE_BUFFER}")
            await session.commit()  # Commit to save the changes

    @bot.event
    async def on_message_unpin(message: discord.Message) -> None:
        await remove_sticky_message(message)

    @bot.event
    async def on_message_delete(message: discord.Message) -> None:
        await remove_sticky_message(message)


async def make_message_sticky(
    guild_id: str, channel_id: str, message: discord.Message, view: PersistentView
) -> None:
    """Pins a message in a channel and saves it as sticky in the database."""
    async with AsyncSessionLocal() as session:
        existing_sticky = await fetch_sticky_message(channel_id, session)
        view_metadata = view.to_metadata()
        if not message.pinned:
            await message.pin()
            logger.info(f"Pinned message ID {message.id} in channel {channel_id} as sticky.")

        current_time = time.time()
        if existing_sticky:
            existing_sticky.message_id = str(message.id)
            existing_sticky.content = message.content
            existing_sticky.view_metadata = view_metadata
            existing_sticky.message_count = 0  # Reset counter on update
            existing_sticky.last_activity = current_time  # Initialize activity timestamp
            logger.info(f"Updated sticky message in database for channel {channel_id}.")
        else:
            new_message = Message(
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=str(message.id),
                content=message.content,
                view_metadata=view_metadata,
                is_sticky=True,
                message_count=0,  # Initialize counter
                last_activity=current_time  # Initialize activity timestamp
            )
            session.add(new_message)
            logger.info(f"Created new sticky message entry for channel {channel_id}.")

        await session.commit()
        logger.info(f"Sticky message ID {message.id} committed for channel {channel_id}")


async def remove_sticky_message(message: discord.Message) -> None:
    """Removes a sticky message from the database if it matches the given message."""
    async with AsyncSessionLocal() as session:
        sticky_message = await fetch_sticky_message(str(message.channel.id), session)
        if not sticky_message or sticky_message.message_id != str(message.id):
            return

        await session.delete(sticky_message)
        logger.info(f"Removed sticky message with ID {message.id} from channel {message.channel.id} in database.")
        await session.commit()