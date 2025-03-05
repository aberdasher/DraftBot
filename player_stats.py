import discord
import json
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, or_, text
from session import AsyncSessionLocal, DraftSession, MatchResult, PlayerStats
from loguru import logger

async def get_player_statistics(user_id, time_frame=None, user_display_name=None):
    """Get player statistics for a specific user and time frame."""
    try:
        now = datetime.now()
        
        # Calculate the start date based on time frame
        if time_frame == 'week':
            start_date = now - timedelta(days=7)
        elif time_frame == 'month':
            start_date = now - timedelta(days=30)
        else:  # Lifetime stats
            start_date = datetime(2000, 1, 1)  # Far in the past
        
        # Default values for stats
        drafts_played = 0
        matches_played = 0
        matches_won = 0
        trophies_won = 0
        match_win_percentage = 0
        current_elo = 1200
        display_name = user_display_name or "Unknown"
        cube_stats = {}
        
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Get basic player stats if they exist
                player_stats_query = select(PlayerStats).where(PlayerStats.player_id == user_id)
                player_stats_result = await session.execute(player_stats_query)
                player_stats = player_stats_result.scalar_one_or_none()
                
                if player_stats:
                    current_elo = player_stats.elo_rating
                    if player_stats.display_name:
                        display_name = player_stats.display_name
                
                # Define the pattern for JSON searches
                pattern = f'%"{user_id}"%'  # Pattern to match user_id in JSON string
                
                # For SQLite, we need to use json_extract with LIKE to search for values in JSON
                # Use direct SQL for the complex JSON conditions
                drafts_query = text("""
                    SELECT COUNT(*) FROM draft_sessions 
                    WHERE (
                        json_extract(sign_ups, '$') LIKE :pattern
                        OR json_extract(team_a, '$') LIKE :pattern
                        OR json_extract(team_b, '$') LIKE :pattern
                    ) AND draft_start_time >= :start_date
                """)
                
                drafts_played_result = await session.execute(
                    drafts_query, 
                    {"pattern": pattern, "start_date": start_date}
                )
                drafts_played = drafts_played_result.scalar() or 0
                
                # Get matches won
                matches_won_query = select(func.count(MatchResult.id)).where(
                    and_(
                        MatchResult.winner_id == user_id,
                        # Join with DraftSession to filter by date
                        MatchResult.session_id.in_(
                            select(DraftSession.session_id).where(
                                DraftSession.draft_start_time >= start_date
                            )
                        )
                    )
                )
                matches_won_result = await session.execute(matches_won_query)
                matches_won = matches_won_result.scalar() or 0
                
                # First, try to get the display name from any sign_ups entries
                name_query = text("""
                    SELECT sign_ups FROM draft_sessions 
                    WHERE json_extract(sign_ups, '$') LIKE :pattern
                    ORDER BY draft_start_time DESC LIMIT 1
                """)
                
                name_result = await session.execute(name_query, {"pattern": pattern})
                sign_ups_json = name_result.scalar()
                
                # Extract display name from sign_ups JSON
                if sign_ups_json:
                    try:
                        # Handle string or dict format
                        if isinstance(sign_ups_json, str):
                            sign_ups = json.loads(sign_ups_json)
                        else:
                            sign_ups = sign_ups_json
                            
                        # Find the user's display name
                        if user_id in sign_ups:
                            display_name = sign_ups[user_id]
                            logger.info(f"Found display name '{display_name}' for user {user_id}")
                    except Exception as e:
                        logger.error(f"Error parsing sign_ups JSON: {e}")
                
                # Get trophies with two approaches
                
                # Approach 1: Direct display name matching in trophy_drafters
                trophies_query = text("""
                    SELECT trophy_drafters FROM draft_sessions 
                    WHERE trophy_drafters IS NOT NULL
                    AND draft_start_time >= :start_date
                """)
                
                trophies_result = await session.execute(trophies_query, {"start_date": start_date})
                trophies_entries = trophies_result.fetchall()
                
                trophies_won = 0
                for (trophy_drafters_json,) in trophies_entries:
                    if not trophy_drafters_json:
                        continue
                        
                    try:
                        # Parse trophy_drafters - could be a string or already JSON
                        if isinstance(trophy_drafters_json, str):
                            trophy_drafters = json.loads(trophy_drafters_json)
                        elif isinstance(trophy_drafters_json, list):
                            trophy_drafters = trophy_drafters_json
                        else:
                            logger.warning(f"Unexpected trophy_drafters format: {type(trophy_drafters_json)}")
                            continue
                            
                        # Check if display name is in the list
                        if display_name in trophy_drafters:
                            trophies_won += 1
                            logger.info(f"Found trophy for '{display_name}' in {trophy_drafters}")
                    except Exception as e:
                        logger.error(f"Error processing trophy_drafters: {e}")
                
                # Approach 2: Cross-reference with sign_ups to find all display names
                if trophies_won == 0:
                    # Get all display names this user has used
                    names_query = text("""
                        SELECT sign_ups FROM draft_sessions 
                        WHERE json_extract(sign_ups, '$') LIKE :pattern
                    """)
                    
                    names_result = await session.execute(names_query, {"pattern": pattern})
                    all_sign_ups = names_result.fetchall()
                    
                    user_names = set()
                    for (signup_json,) in all_sign_ups:
                        if not signup_json:
                            continue
                            
                        try:
                            # Parse sign_ups
                            if isinstance(signup_json, str):
                                sign_ups = json.loads(signup_json)
                            else:
                                sign_ups = signup_json
                                
                            # Add this display name
                            if user_id in sign_ups:
                                user_names.add(sign_ups[user_id])
                        except Exception as e:
                            logger.error(f"Error processing sign_ups for names: {e}")
                    
                    # Now count trophies again with all user names
                    for (trophy_drafters_json,) in trophies_entries:
                        if not trophy_drafters_json:
                            continue
                            
                        try:
                            # Parse trophy_drafters
                            if isinstance(trophy_drafters_json, str):
                                trophy_drafters = json.loads(trophy_drafters_json)
                            elif isinstance(trophy_drafters_json, list):
                                trophy_drafters = trophy_drafters_json
                            else:
                                continue
                                
                            # Check if any of the user's names are in trophy_drafters
                            for name in user_names:
                                if name in trophy_drafters:
                                    trophies_won += 1
                                    logger.info(f"Found trophy for alternate name '{name}' in {trophy_drafters}")
                                    break  # Count each trophy only once
                        except Exception as e:
                            logger.error(f"Error processing trophy_drafters for alternates: {e}")
                
                # Get total matches played
                matches_played_query = select(func.count(MatchResult.id)).where(
                    and_(
                        or_(
                            MatchResult.player1_id == user_id,
                            MatchResult.player2_id == user_id
                        ),
                        # Join with DraftSession to filter by date
                        MatchResult.session_id.in_(
                            select(DraftSession.session_id).where(
                                DraftSession.draft_start_time >= start_date
                            )
                        )
                    )
                )
                matches_played_result = await session.execute(matches_played_query)
                matches_played = matches_played_result.scalar() or 0
                
                # Calculate match win percentage
                match_win_percentage = (matches_won / matches_played * 100) if matches_played > 0 else 0
                
                # ==== TEAM DRAFT WINS ====
                # Get all draft sessions the user participated in
                drafts_query = text("""
                    SELECT id, session_id, team_a, team_b, session_type
                    FROM draft_sessions 
                    WHERE (
                        json_extract(sign_ups, '$') LIKE :pattern
                        OR json_extract(team_a, '$') LIKE :pattern
                        OR json_extract(team_b, '$') LIKE :pattern
                    ) 
                    AND draft_start_time >= :start_date
                    AND (session_type = 'random' OR session_type = 'premade')
                """)
                
                drafts_result = await session.execute(
                    drafts_query, 
                    {"pattern": pattern, "start_date": start_date}
                )
                
                draft_sessions = drafts_result.fetchall()
                
                # Initialize counters
                team_drafts_played = 0
                team_drafts_won = 0
                team_drafts_tied = 0
                
                # Process each draft
                for draft_id, session_id, team_a_json, team_b_json, session_type in draft_sessions:
                    # Skip if not a team draft or missing team data
                    if session_type not in ['random', 'premade'] or not team_a_json or not team_b_json:
                        continue
                    
                    # Determine which team the user was on
                    try:
                        team_a = team_a_json if isinstance(team_a_json, list) else json.loads(team_a_json) if isinstance(team_a_json, str) else []
                        team_b = team_b_json if isinstance(team_b_json, list) else json.loads(team_b_json) if isinstance(team_b_json, str) else []
                        
                        user_team = None
                        if user_id in team_a:
                            user_team = 'A'
                        elif user_id in team_b:
                            user_team = 'B'
                        else:
                            # User not on either team (might be in sign_ups but not teams)
                            continue
                            
                        # Now get all match results for this draft
                        match_results_query = text("""
                            SELECT 
                                player1_id, player2_id, 
                                player1_wins, player2_wins, 
                                winner_id
                            FROM match_results 
                            WHERE session_id = :session_id
                        """)
                        
                        match_results = await session.execute(
                            match_results_query, 
                            {"session_id": session_id}
                        )
                        
                        team_a_wins = 0
                        team_b_wins = 0
                        
                        for p1_id, p2_id, p1_wins, p2_wins, winner_id in match_results.fetchall():
                            # Determine which team won this match
                            if winner_id:
                                if winner_id in team_a:
                                    team_a_wins += 1
                                elif winner_id in team_b:
                                    team_b_wins += 1
                        
                        # Count this as a played draft
                        team_drafts_played += 1
                        
                        # Determine the draft winner
                        if team_a_wins > team_b_wins:
                            # Team A won
                            if user_team == 'A':
                                team_drafts_won += 1
                        elif team_b_wins > team_a_wins:
                            # Team B won
                            if user_team == 'B':
                                team_drafts_won += 1
                        else:
                            # It's a tie
                            team_drafts_tied += 1
                            
                    except Exception as e:
                        logger.error(f"Error processing draft {draft_id}: {e}")
                
                # Calculate team draft win percentage
                team_draft_win_percentage = (team_drafts_won / team_drafts_played * 100) if team_drafts_played > 0 else 0
                
                # Get stats by cube type
                cube_query = text("""
                    SELECT cube, COUNT(*) as draft_count 
                    FROM draft_sessions 
                    WHERE (
                        json_extract(sign_ups, '$') LIKE :pattern
                        OR json_extract(team_a, '$') LIKE :pattern
                        OR json_extract(team_b, '$') LIKE :pattern
                    ) 
                    AND draft_start_time >= :start_date
                    AND cube IS NOT NULL
                    GROUP BY LOWER(cube)
                    HAVING COUNT(*) >= 5
                """)
                
                cube_result = await session.execute(
                    cube_query, 
                    {"pattern": pattern, "start_date": start_date}
                )
                cube_data = cube_result.fetchall()
                
                # For each cube, get matches played and won
                cube_stats = {}
                for cube_name, draft_count in cube_data:
                    if not cube_name:  # Skip if cube name is None
                        continue
                        
                    # Normalize cube name
                    normalized_cube_name = cube_name.lower()
                    
                    # Get matches played for this cube
                    cube_matches_query = text("""
                        SELECT COUNT(*) 
                        FROM match_results 
                        WHERE (player1_id = :user_id OR player2_id = :user_id)
                        AND session_id IN (
                            SELECT session_id FROM draft_sessions 
                            WHERE LOWER(cube) = :cube_name
                            AND draft_start_time >= :start_date
                        )
                    """)
                    
                    cube_matches_result = await session.execute(
                        cube_matches_query, 
                        {"user_id": user_id, "cube_name": normalized_cube_name, "start_date": start_date}
                    )
                    cube_matches_played = cube_matches_result.scalar() or 0
                    
                    # Get matches won for this cube
                    cube_wins_query = text("""
                        SELECT COUNT(*) 
                        FROM match_results 
                        WHERE winner_id = :user_id
                        AND session_id IN (
                            SELECT session_id FROM draft_sessions 
                            WHERE LOWER(cube) = :cube_name
                            AND draft_start_time >= :start_date
                        )
                    """)
                    
                    cube_wins_result = await session.execute(
                        cube_wins_query, 
                        {"user_id": user_id, "cube_name": normalized_cube_name, "start_date": start_date}
                    )
                    cube_matches_won = cube_wins_result.scalar() or 0
                    
                    # Calculate win percentage
                    cube_win_percentage = (cube_matches_won / cube_matches_played * 100) if cube_matches_played > 0 else 0
                    
                    # Store stats with the original cube name (not normalized)
                    cube_stats[cube_name] = {
                        "drafts_played": draft_count,
                        "matches_played": cube_matches_played,
                        "matches_won": cube_matches_won,
                        "win_percentage": cube_win_percentage
                    }
                
                return {
                    "drafts_played": drafts_played,
                    "matches_played": matches_played,
                    "matches_won": matches_won,
                    "trophies_won": trophies_won,
                    "match_win_percentage": match_win_percentage,
                    "current_elo": current_elo,
                    "display_name": display_name,
                    "cube_stats": cube_stats,
                    # Add team draft stats
                    "team_drafts_played": team_drafts_played,
                    "team_drafts_won": team_drafts_won,
                    "team_drafts_tied": team_drafts_tied,
                    "team_draft_win_percentage": team_draft_win_percentage
                }
                
    except Exception as e:
        logger.error(f"Error getting stats for user {user_id}: {e}")
        # Return default values with team draft stats
        return {
            "drafts_played": 0,
            "matches_played": 0,
            "matches_won": 0,
            "trophies_won": 0,
            "match_win_percentage": 0,
            "current_elo": 1200,
            "display_name": "Unknown",
            "cube_stats": {},
            "team_drafts_played": 0,
            "team_drafts_won": 0,
            "team_drafts_tied": 0,
            "team_draft_win_percentage": 0
        }

async def create_stats_embed(user, stats_weekly, stats_monthly, stats_lifetime):
    """Create a Discord embed with player statistics."""
    # Use the display name from stats if user object doesn't have a name
    display_name = user.display_name if hasattr(user, 'display_name') else stats_lifetime['display_name']
    
    embed = discord.Embed(
        title=f"Stats for {display_name}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # Set thumbnail if user object is available
    if hasattr(user, 'display_avatar'):
        embed.set_thumbnail(url=user.display_avatar.url)
    
    # Calculate losses for each time frame
    weekly_losses = stats_weekly['team_drafts_played'] - stats_weekly['team_drafts_won'] - stats_weekly['team_drafts_tied']
    monthly_losses = stats_monthly['team_drafts_played'] - stats_monthly['team_drafts_won'] - stats_monthly['team_drafts_tied']
    lifetime_losses = stats_lifetime['team_drafts_played'] - stats_lifetime['team_drafts_won'] - stats_lifetime['team_drafts_tied']
    
    # Weekly stats
    embed.add_field(
        name="Weekly Stats (Last 7 Days)",
        value=(
            f"Drafts Played: {stats_weekly['drafts_played']}\n"
            f"Matches Won: {stats_weekly['matches_won']}/{stats_weekly['matches_played']}\n"
            f"Win %: {stats_weekly['match_win_percentage']:.1f}%\n"
            f"Trophies: {stats_weekly['trophies_won']}\n"
            f"Draft Record: {stats_weekly['team_drafts_won']}-{weekly_losses}-{stats_weekly['team_drafts_tied']}"
            + (f" (Win %: {stats_weekly['team_draft_win_percentage']:.1f}%)" if stats_weekly['team_drafts_played'] > 0 else "")
        ),
        inline=True
    )
    
    # Monthly stats
    embed.add_field(
        name="Monthly Stats (Last 30 Days)",
        value=(
            f"Drafts Played: {stats_monthly['drafts_played']}\n"
            f"Matches Won: {stats_monthly['matches_won']}/{stats_monthly['matches_played']}\n"
            f"Win %: {stats_monthly['match_win_percentage']:.1f}%\n"
            f"Trophies: {stats_monthly['trophies_won']}\n"
            f"Draft Record: {stats_monthly['team_drafts_won']}-{monthly_losses}-{stats_monthly['team_drafts_tied']}" 
            + (f" (Win %: {stats_monthly['team_draft_win_percentage']:.1f}%)" if stats_monthly['team_drafts_played'] > 0 else "")
        ),
        inline=True
    )
    
    # Lifetime stats
    embed.add_field(
        name="Lifetime Stats",
        value=(
            f"Drafts Played: {stats_lifetime['drafts_played']}\n"
            f"Matches Won: {stats_lifetime['matches_won']}/{stats_lifetime['matches_played']}\n"
            f"Win %: {stats_lifetime['match_win_percentage']:.1f}%\n"
            f"Trophies: {stats_lifetime['trophies_won']}\n"
            f"Current ELO: {stats_lifetime['current_elo']:.0f}\n"
            f"Draft Record: {stats_lifetime['team_drafts_won']}-{lifetime_losses}-{stats_lifetime['team_drafts_tied']}"
            + (f" (Win %: {stats_lifetime['team_draft_win_percentage']:.1f}%)" if stats_lifetime['team_drafts_played'] > 0 else "")
        ),
        inline=False
    )
    
    # Add cube-specific stats if any are available
    if stats_lifetime['cube_stats']:
        # Convert to list and sort by drafts_played in descending order
        sorted_cube_stats = sorted(
            stats_lifetime['cube_stats'].items(),
            key=lambda x: x[1]['drafts_played'],
            reverse=True
        )
        
        cube_stats_text = ""
        for cube_name, stats in sorted_cube_stats:
            cube_stats_text += f"**{cube_name}**: {stats['win_percentage']:.1f}% ({stats['drafts_played']} Drafts)\n"
        
        embed.add_field(
            name="Cube Win Percentage",
            value=cube_stats_text,
            inline=False
        )
    
    embed.set_footer(text="Stats are updated after each draft")
    
    return embed