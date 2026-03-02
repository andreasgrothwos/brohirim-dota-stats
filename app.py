"""
Brohirim Dota 2 Statistics Dashboard
Streamlit App - Interactive web dashboard for Dota 2 stats
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import json
import shutil
from PIL import Image
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Brohirim Dota 2 Stats",
    page_icon="👏",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Player configuration
PLAYERS = {
    "Andreas": 3336264,
    "Magnus": 29391237,
    "Casper": 143488868,
    "Ahle": 4222575,
    "Nicolai": 74973595,
    "Patrick": 95669087
}

# API Configuration
try:
    API_KEY = st.secrets["STRATZ_API_KEY"]
except (FileNotFoundError, KeyError):
    st.error("⚠️ API Key not found! Please configure it in Streamlit secrets.")
    st.info("For local development: Create .streamlit/secrets.toml with your API key")
    st.info("For Streamlit Cloud: Add STRATZ_API_KEY in app settings > Secrets")
    st.stop()

BASE_DIR = Path.cwd()
IMAGE_DIR = BASE_DIR / "images"
CACHE_DIR = BASE_DIR / ".match_cache"

# Bump when GraphQL schema adds new fields – forces a full re-fetch
CACHE_SCHEMA_VERSION = 2

def load_player_image(player_name):
    """Load player profile picture if it exists"""
    # Try both .jpg and .JPG extensions
    for ext in ['.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']:
        image_path = IMAGE_DIR / f"{player_name}{ext}"
        if image_path.exists():
            try:
                return Image.open(image_path)
            except Exception:
                continue
    return None


def _load_disk_cache(player_name):
    """Load raw match data from disk cache. Returns list of match dicts."""
    cache_file = CACHE_DIR / f"{player_name}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            # Old format was a plain list – version mismatch means re-fetch
            if isinstance(data, list):
                return []
            if data.get("version", 1) != CACHE_SCHEMA_VERSION:
                return []
            return data.get("matches", [])
        except Exception:
            return []
    return []


def _save_disk_cache(player_name, matches):
    """Persist raw match data to disk cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{player_name}.json"
    try:
        with open(cache_file, "w") as f:
            json.dump({"version": CACHE_SCHEMA_VERSION, "matches": matches}, f)
    except Exception as e:
        st.warning(f"Kunne ikke gemme cache for {player_name}: {e}")


def fetch_all_matches_for_player(steam_id, player_name, cutoff_date):
    """
    Fetch matches for a player using a persistent disk cache.
    Loads historical matches from disk and only fetches new ones from the API.
    """
    cutoff_ts = int(cutoff_date.timestamp())

    # Load existing cached matches from disk
    cached_matches = _load_disk_cache(player_name)
    cached_ids = {m["id"] for m in cached_matches}

    query = """
    query($steamAccountId: Long!, $take: Int!, $skip: Int!) {
      player(steamAccountId: $steamAccountId) {
        steamAccountId
        matches(request: { take: $take, skip: $skip }) {
          id
          startDateTime
          durationSeconds
          didRadiantWin
          gameMode
          lobbyType
          bracket
          players {
            steamAccountId
            isVictory
            isRadiant
            imp
            hero {
              displayName
              id
            }
            kills
            deaths
            assists
            level
            position
            lane
            goldPerMinute
            experiencePerMinute
            networth
            heroDamage
            heroHealing
            towerDamage
            lastHits
            denies
            stuns
            campsStacked
            award
            laneEfficiency
            item0Id
            item1Id
            item2Id
            item3Id
            item4Id
            item5Id
            neutralItemId
            steamAccount {
              seasonRank
              seasonLeaderboardRank
            }
          }
        }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "STRATZ_API",
        "Content-Type": "application/json"
    }

    new_matches = []
    skip = 0
    batch_size = 100
    max_batches = 10  # Allow more batches; early exit hits for cached players

    for batch_num in range(max_batches):
        variables = {
            "steamAccountId": steam_id,
            "take": batch_size,
            "skip": skip
        }

        try:
            response = requests.post(
                "https://api.stratz.com/graphql",
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=20
            )

            if response.status_code != 200:
                st.warning(f"API returned status {response.status_code} for {player_name}")
                break

            data = response.json()

            if "errors" in data:
                st.error(f"API errors for {player_name}: {data['errors']}")
                break

            matches = data.get("data", {}).get("player", {}).get("matches")

            if not matches or len(matches) == 0:
                break

            reached_cached = False
            for match in matches:
                if match["id"] in cached_ids:
                    # We've reached matches already in cache – stop fetching
                    reached_cached = True
                    break
                if match["startDateTime"] >= cutoff_ts:
                    new_matches.append(match)

            if reached_cached:
                break

            # Stop if oldest match in batch is before our cutoff
            if min(m["startDateTime"] for m in matches) < cutoff_ts:
                break

            if len(matches) < batch_size:
                break

            skip += batch_size
            time.sleep(0.5)  # Rate limiting between batches

        except Exception as e:
            st.error(f"Exception fetching {player_name}: {str(e)}")
            break

    if new_matches:
        # Merge new matches with cached ones, keeping only matches within date range
        all_matches = new_matches + [m for m in cached_matches if m["startDateTime"] >= cutoff_ts]
        _save_disk_cache(player_name, all_matches)
        return all_matches, len(new_matches)

    # Nothing new – return from disk cache (filtered to date range)
    return [m for m in cached_matches if m["startDateTime"] >= cutoff_ts], 0


def process_matches(matches, steam_id, player_name, all_steam_ids):
    """Process raw match data into structured format"""
    
    processed_data = []
    
    for match in matches:
        match_id = match["id"]
        match_date = datetime.fromtimestamp(match["startDateTime"])
        duration_min = round(match["durationSeconds"] / 60, 1)
        game_mode = match.get("gameMode")
        lobby_type = match.get("lobbyType")
        bracket = match.get("bracket")

        players = match["players"]
        player_data = next((p for p in players if p["steamAccountId"] == steam_id), None)

        if not player_data:
            continue

        # Find Brohirim teammates
        is_radiant = player_data["isRadiant"]
        teammates = [p for p in players if p["isRadiant"] == is_radiant and p["steamAccountId"] != steam_id]
        brohirim_teammates = [t for t in teammates if t["steamAccountId"] in all_steam_ids]

        is_party = len(brohirim_teammates) > 0
        friend_names = [list(PLAYERS.keys())[list(PLAYERS.values()).index(t["steamAccountId"])]
                        for t in brohirim_teammates]

        # Calculate KDA
        kills = player_data["kills"]
        deaths = max(player_data["deaths"], 1)
        assists = player_data["assists"]
        kda = round((kills + assists) / deaths, 2)

        # Map position to role
        position_map = {
            "POSITION_1": "Carry (Pos 1)",
            "POSITION_2": "Mid (Pos 2)",
            "POSITION_3": "Offlane (Pos 3)",
            "POSITION_4": "Soft Support (Pos 4)",
            "POSITION_5": "Hard Support (Pos 5)",
        }
        position = player_data.get("position")
        role = position_map.get(position, "Unknown")

        # Get lane info
        lane_map = {
            "SAFE_LANE": "Safe Lane",
            "MID_LANE": "Mid Lane",
            "OFF_LANE": "Off Lane",
            "JUNGLE": "Jungle",
            "ROAMING": "Roaming",
        }
        lane = player_data.get("lane")
        lane_name = lane_map.get(lane, "Unknown")

        # Find laning partners
        same_lane_teammates = [
            t for t in brohirim_teammates
            if t.get("lane") == lane and lane is not None
        ]
        lane_partner_names = [list(PLAYERS.keys())[list(PLAYERS.values()).index(t["steamAccountId"])]
                              for t in same_lane_teammates]

        # Steam account / rank
        steam_account = player_data.get("steamAccount") or {}

        processed_data.append({
            "player_name": player_name,
            "match_id": match_id,
            "match_date": match_date,
            "duration_min": duration_min,
            "game_mode": str(game_mode) if game_mode else None,
            "lobby_type": str(lobby_type) if lobby_type else None,
            "bracket": str(bracket) if bracket else None,
            "hero": player_data["hero"]["displayName"] if player_data.get("hero") else "Unknown",
            "is_victory": player_data["isVictory"],
            "performance_score": player_data["imp"],
            "kills": kills,
            "deaths": player_data["deaths"],
            "assists": assists,
            "kda": kda,
            "level": player_data.get("level"),
            "position": position if position else "Unknown",
            "role": role,
            "lane": lane_name,
            "is_party": is_party,
            "party_with": ", ".join(friend_names) if friend_names else None,
            "lane_partner": ", ".join(lane_partner_names) if lane_partner_names else None,
            # Economy
            "gold_per_min": player_data.get("goldPerMinute"),
            "xp_per_min": player_data.get("experiencePerMinute"),
            "networth": player_data.get("networth"),
            "last_hits": player_data.get("lastHits"),
            "denies": player_data.get("denies"),
            "lane_efficiency": player_data.get("laneEfficiency"),
            # Damage & impact
            "hero_damage": player_data.get("heroDamage"),
            "hero_healing": player_data.get("heroHealing"),
            "tower_damage": player_data.get("towerDamage"),
            "stuns": player_data.get("stuns"),
            "camps_stacked": player_data.get("campsStacked"),
            # Award
            "award": player_data.get("award") or "NONE",
            # Items
            "item0_id": player_data.get("item0Id"),
            "item1_id": player_data.get("item1Id"),
            "item2_id": player_data.get("item2Id"),
            "item3_id": player_data.get("item3Id"),
            "item4_id": player_data.get("item4Id"),
            "item5_id": player_data.get("item5Id"),
            "neutral_item_id": player_data.get("neutralItemId"),
            # Rank
            "season_rank": steam_account.get("seasonRank"),
            "season_leaderboard_rank": steam_account.get("seasonLeaderboardRank"),
        })
    
    return processed_data


RANK_NAMES = {
    1: "Herald", 2: "Guardian", 3: "Crusader",
    4: "Archon", 5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal",
}


def decode_rank(season_rank):
    """Convert Dota 2 seasonRank integer to a readable badge string."""
    if season_rank is None or season_rank == 0:
        return "Ukalibreret"
    tier = int(season_rank) // 10
    stars = int(season_rank) % 10
    name = RANK_NAMES.get(tier, "Ukendt")
    if tier == 8:
        return "Immortal"
    return f"{name} {'★' * stars}" if stars > 0 else name


@st.cache_data(ttl=86400)
def load_item_names():
    """Load item ID → display name mapping from STRATZ constants (cached 24h)."""
    query = "query { constants { items { id displayName } } }"
    try:
        resp = requests.post(
            "https://api.stratz.com/graphql",
            json={"query": query},
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            items = resp.json().get("data", {}).get("constants", {}).get("items") or []
            return {i["id"]: i["displayName"] for i in items if i.get("id") and i.get("displayName")}
    except Exception:
        pass
    return {}


def format_items(row, item_names):
    """Return a comma-separated string of item names for a match row."""
    names = []
    for col in ["item0_id", "item1_id", "item2_id", "item3_id", "item4_id", "item5_id"]:
        val = row.get(col)
        if val and val > 0:
            names.append(item_names.get(val, f"#{val}"))
    neutral = row.get("neutral_item_id")
    if neutral and neutral > 0:
        names.append(f"[{item_names.get(neutral, f'#{neutral}')}]")
    return ", ".join(names)


@st.cache_data(ttl=7200)  # Cache processed DataFrame for 2 hours in-memory
def load_full_year_data(selected_players):
    """Load ALL matches from last year – uses disk cache, only fetches new matches from API"""

    cutoff_date = datetime.now() - timedelta(days=365)
    all_data = []
    all_steam_ids = [PLAYERS[p] for p in selected_players]

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_new = 0

    for idx, player_name in enumerate(selected_players):
        status_text.text(f"📥 Henter matches for {player_name}...")
        steam_id = PLAYERS[player_name]

        try:
            matches, new_count = fetch_all_matches_for_player(steam_id, player_name, cutoff_date)
            total_new += new_count

            if matches:
                processed = process_matches(matches, steam_id, player_name, all_steam_ids)
                all_data.extend(processed)
                if new_count > 0:
                    status_text.text(f"✅ {len(processed)} matches for {player_name} ({new_count} nye)")
                else:
                    status_text.text(f"✅ {len(processed)} matches for {player_name} (fra cache)")
            else:
                status_text.text(f"⚠️ Ingen matches fundet for {player_name}")
                st.warning(f"Kunne ikke indlæse matches for {player_name}. Tjek API-nøgle eller prøv igen.")
        except Exception as e:
            st.error(f"Fejl ved indlæsning af {player_name}: {str(e)}")
            status_text.text(f"❌ Fejl for {player_name}")

        progress_bar.progress((idx + 1) / len(selected_players))

    status_text.empty()
    progress_bar.empty()

    df = pd.DataFrame(all_data)

    if not df.empty:
        cache_note = f" ({total_new} nye fra API)" if total_new > 0 else " (alt fra disk-cache)"
        st.success(f"✅ {len(df)} matches fra {len(df['player_name'].unique())} spillere{cache_note}. Cachet i 2 timer.")
    else:
        st.error("⚠️ Ingen data indlæst. Dette kan skyldes:")
        st.info("1. API rate limiting – vent lidt og klik 'Opdater data'\n2. API-nøgle problemer\n3. Ingen matches det seneste år")

    return df


def display_player_cards(selected_players, df):
    """Display player cards sorted by performance, with form indicator and current streak"""
    st.subheader("👥 Bros (efter performance)")

    player_stats = []
    for player in selected_players:
        player_data = df[df["player_name"] == player].sort_values("match_date", ascending=False)
        if player_data.empty:
            continue

        matches = len(player_data)
        win_rate = player_data["is_victory"].sum() / matches * 100
        avg_perf = player_data["performance_score"].mean()

        # Form: last 5 games vs overall average within current filter
        if matches >= 5:
            last5_perf = player_data.head(5)["performance_score"].mean()
            if last5_perf > avg_perf * 1.1:
                form = "🔥"
            elif last5_perf < avg_perf * 0.9:
                form = "📉"
            else:
                form = "😐"
        else:
            form = ""

        # Current streak (consecutive wins or losses from most recent)
        streak_count, streak_type = 0, None
        for _, row in player_data.iterrows():
            if streak_type is None:
                streak_type = "win" if row["is_victory"] else "loss"
                streak_count = 1
            elif (row["is_victory"] and streak_type == "win") or (not row["is_victory"] and streak_type == "loss"):
                streak_count += 1
            else:
                break

        # Award summary (only if award data exists)
        award_summary = ""
        if "award" in player_data.columns:
            award_counts = player_data[player_data["award"] != "NONE"]["award"].value_counts()
            award_icons = {"MVP": "🏆 MVP", "TOP_CORE": "⚔️ Top Core", "TOP_SUPPORT": "🛡️ Top Support"}
            parts = [f"{award_icons.get(a, a)} ×{c}" for a, c in award_counts.head(3).items()]
            award_summary = " · ".join(parts)

        player_stats.append({
            "name": player,
            "matches": matches,
            "win_rate": win_rate,
            "avg_perf": avg_perf,
            "form": form,
            "streak_count": streak_count,
            "streak_type": streak_type,
            "award_summary": award_summary,
        })

    player_stats.sort(key=lambda x: x["avg_perf"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    cols = st.columns(len(player_stats))

    for idx, player_info in enumerate(player_stats):
        player = player_info["name"]
        with cols[idx]:
            img = load_player_image(player)
            if img:
                st.image(img, use_container_width=True)

            medal = medals[idx] if idx < 3 else ""
            st.markdown(f"### {medal} {player} {player_info['form']}")

            st.metric("Matches", player_info["matches"])
            st.metric("Win rate", f"{player_info['win_rate']:.1f}%")
            st.metric("Gns. performance", f"{player_info['avg_perf']:.1f}")

            if player_info["streak_type"] == "win" and player_info["streak_count"] >= 2:
                st.success(f"🔥 {player_info['streak_count']} sejre i træk")
            elif player_info["streak_type"] == "loss" and player_info["streak_count"] >= 2:
                st.error(f"💀 {player_info['streak_count']} tab i træk")

            if player_info["award_summary"]:
                st.caption(player_info["award_summary"])

    st.markdown("---")


def main():
    """Main app"""
    
    st.title("👏 Brohirim Dota")
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Indtillinger")
        
        page = st.selectbox(
            "📄 Vælg side",
            ["🏠 Overblik", "📊 Performance", "🎯 Rolle & position", "🤝 Lanes", "🦸 Heroes", "📅 Aktivitet", "📋 Matches"]
        )
        
        st.markdown("---")
        
        selected_players = st.multiselect(
            "Vælg spillere",
            options=list(PLAYERS.keys()),
            default=list(PLAYERS.keys())
        )
        
        st.markdown("---")
        st.subheader("📅 Filtrer data")
        
        time_range = st.selectbox(
            "Tidsperiode",
            options=["Alle data", "I dag", "Sidste 7 dage", "Sidste 30 dage", "Sidste 90 dage", "2025 kun", "Brugerdefineret"],
            index=2,
            help="Filtrer cached data - ingen API kald"
        )
        
        if time_range == "Brugerdefineret":
            start_date = st.date_input("Start dato", value=datetime(2025, 1, 1))
            filter_start_date = datetime.combine(start_date, datetime.min.time())
        elif time_range == "I dag":
            filter_start_date = datetime.now() - timedelta(hours=16)
        elif time_range == "Sidste 7 dage":
            filter_start_date = datetime.now() - timedelta(days=7)
        elif time_range == "Sidste 30 dage":
            filter_start_date = datetime.now() - timedelta(days=30)
        elif time_range == "Sidste 90 dage":
            filter_start_date = datetime.now() - timedelta(days=90)
        elif time_range == "2025 kun":
            filter_start_date = datetime(2025, 1, 1)
        else:
            filter_start_date = None
        
        limit_matches = st.selectbox(
            "Begræns til seneste N matches",
            options=["Alle matches", "Sidste 10", "Sidste 20", "Sidste 50"],
            index=0,
            help="Seneste N matches per spiller"
        )

        show_turbo = st.checkbox(
            "Inkluder Turbo-kampe",
            value=False,
            help="Turbo-kampe skæver GPM, damage og varighed – slå fra for clean statistik"
        )

        st.markdown("---")
        if st.button("🔄 Opdater data", use_container_width=True,
                     help="Henter nye matches fra API (gemte historiske matches bevares)"):
            st.cache_data.clear()
            st.session_state.data_loaded_at = datetime.now()
            st.rerun()

        if st.button("🗑️ Nulstil disk cache", use_container_width=True,
                     help="Sletter alle gemte matches og henter alt forfra fra API"):
            if CACHE_DIR.exists():
                shutil.rmtree(CACHE_DIR)
            st.cache_data.clear()
            st.session_state.data_loaded_at = datetime.now()
            st.rerun()

        st.markdown("---")
        st.caption("💡 Historiske matches gemmes på disk – kun nye hentes fra API")
        st.caption(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    
    if not selected_players:
        st.warning("Vælg mindst én Brohirim")
        return
    
    # Load data once
    with st.spinner("🔄 Indlæser data fra det sidste år..."):
        df_full = load_full_year_data(selected_players)

    if "data_loaded_at" not in st.session_state:
        st.session_state.data_loaded_at = datetime.now()

    if df_full.empty:
        st.error("Ingen data tilgængelig")
        return

    # Filter in memory - NO API CALLS
    df = df_full.copy()

    if filter_start_date:
        df = df[df["match_date"] >= filter_start_date]

    if limit_matches != "Alle matches":
        n = int(limit_matches.split()[-1])
        df = df.sort_values("match_date", ascending=False).groupby("player_name").head(n).reset_index(drop=True)

    if not show_turbo and "game_mode" in df.columns:
        df = df[df["game_mode"] != "TURBO"]

    if df.empty:
        st.warning("Ingen matches med nuværende filtre")
        return

    # Update info bar
    mins_ago = int((datetime.now() - st.session_state.data_loaded_at).total_seconds() / 60)
    info_col, btn_col = st.columns([6, 1])
    with info_col:
        label = "frisk indlæst" if mins_ago == 0 else f"indlæst for {mins_ago} min. siden"
        st.caption(f"🕐 Data {label} · {len(df)} matches · {df['match_date'].min().date()} → {df['match_date'].max().date()}")
    with btn_col:
        if st.button("⚡ Opdater", help="Henter nye matches fra API"):
            st.cache_data.clear()
            st.session_state.data_loaded_at = datetime.now()
            st.rerun()

    # Route to pages
    if page == "🏠 Overblik":
        show_overview_page(df, selected_players)
    elif page == "📊 Performance":
        show_performance_page(df, selected_players)
    elif page == "🎯 Rolle & position":
        show_role_page(df)
    elif page == "🤝 Lanes":
        show_synergy_page(df)
    elif page == "🦸 Heroes":
        show_hero_page(df)
    elif page == "📅 Aktivitet":
        show_activity_page(df)
    elif page == "📋 Matches":
        show_match_history_page(df)


def show_overview_page(df, selected_players):
    """Overview page – seneste kamp øverst, derefter generel statistik"""
    show_latest_match_page(df, selected_players)

    st.markdown("---")
    display_player_cards(selected_players, df)

    st.header("📊 Overblik")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total matches", len(df))
    with col2:
        win_rate = (df["is_victory"].sum() / len(df) * 100)
        st.metric("Win rate", f"{win_rate:.1f}%")
    with col3:
        st.metric("Gns. performance", f"{df['performance_score'].mean():.1f}")
    with col4:
        party_rate = (df["is_party"].sum() / len(df) * 100)
        st.metric("Party rate", f"{party_rate:.1f}%")
    
    st.markdown("---")
    st.header("👥 Sammenligning af spillere")
    
    col1, col2 = st.columns(2)
    
    with col1:
        player_stats = df.groupby("player_name").agg({
            "performance_score": "mean",
            "match_id": "count"
        }).round(2).reset_index()
        player_stats.columns = ["Spiller", "Gns. performance", "Matches"]
        player_stats = player_stats.sort_values("Gns. performance", ascending=True)
        
        fig1 = px.bar(player_stats, x="Gns. performance", y="Spiller", orientation="h",
                     title="Gennemsnitlig performance", text="Gns. performance",
                     color="Gns. performance", color_continuous_scale="RdYlGn")
        fig1.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig1.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig1, use_container_width=True)
    
    with col2:
        win_stats = df.groupby("player_name").agg({
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count"
        }).round(1).reset_index()
        win_stats.columns = ["Spiller", "Win rate %", "Matches"]
        win_stats = win_stats.sort_values("Win rate %", ascending=True)
        
        fig2 = px.bar(win_stats, x="Win rate %", y="Spiller", orientation="h",
                     title="Win rate", text="Win rate %",
                     color="Win rate %", color_continuous_scale="RdYlGn")
        fig2.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig2.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig2, use_container_width=True)
    
    st.header("📈 Performance fordeling")
    fig3 = px.box(df, x="player_name", y="performance_score", color="player_name",
                 title="Performance score fordeling")
    fig3.update_layout(showlegend=False, height=400)
    st.plotly_chart(fig3, use_container_width=True)


def show_performance_page(df, selected_players):
    """Performance page"""
    st.header("📊 Performance")
    
    st.subheader("👥 Party vs Solo")
    party_comparison = df.groupby(["player_name", "is_party"]).agg({
        "performance_score": "mean",
        "is_victory": lambda x: (x.sum() / len(x) * 100),
        "match_id": "count"
    }).round(2).reset_index()
    party_comparison.columns = ["Spiller", "Er party", "Gns. performance", "Win rate %", "Matches"]
    party_comparison["Kamptype"] = party_comparison["Er party"].map({True: "Party", False: "Solo"})
    
    col1, col2 = st.columns(2)
    with col1:
        fig4 = px.bar(party_comparison, x="Spiller", y="Gns. performance", color="Kamptype",
                     barmode="group", title="Performance: Party vs Solo", text="Gns. performance")
        fig4.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        st.plotly_chart(fig4, use_container_width=True)
    
    with col2:
        fig5 = px.bar(party_comparison, x="Spiller", y="Win rate %", color="Kamptype",
                     barmode="group", title="Win rate: Party vs Solo", text="Win rate %")
        fig5.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        st.plotly_chart(fig5, use_container_width=True)
    
    if df["is_party"].any():
        st.subheader("🤝 Party kombinationer")
        party_games = df[df["is_party"] & df["party_with"].notna()].copy()
        if not party_games.empty:
            # Normalize combinations by sorting player names alphabetically
            def normalize_combo(row):
                players = [row["player_name"]] + row["party_with"].split(", ")
                return ", ".join(sorted(players))
            
            party_games["combo"] = party_games.apply(normalize_combo, axis=1)
            party_combos = party_games.groupby("combo").size().reset_index(name="Matches sammen")
            party_combos = party_combos.sort_values("Matches sammen", ascending=False)
            party_combos.columns = ["Spillere", "Matches sammen"]
            
            st.dataframe(party_combos, use_container_width=True, hide_index=True)
    
    st.subheader("📅 Performance over tid")
    df_sorted = df.sort_values("match_date")
    
    # Calculate Brohirim clan average per date
    clan_avg = df_sorted.groupby("match_date")["performance_score"].mean().reset_index()
    clan_avg["player_name"] = "Brohirim gennemsnit"
    
    fig6 = px.line(clan_avg, x="match_date", y="performance_score",
                  title="Performance trend - Brohirim gennemsnit",
                  labels={"match_date": "Dato", "performance_score": "Performance score"})
    fig6.add_hline(y=df["performance_score"].mean(), line_dash="dash", annotation_text="Samlet gennemsnit")
    fig6.update_traces(line=dict(color='#636EFA', width=3))
    st.plotly_chart(fig6, use_container_width=True)
    
    st.markdown("---")
    st.subheader("⏱️ Comeback-meter")
    df_cm = df.copy()
    df_cm["Varighed"] = pd.cut(
        df_cm["duration_min"],
        bins=[0, 25, 35, 45, 200],
        labels=["< 25 min", "25–35 min", "35–45 min", "> 45 min"]
    )
    duration_stats = df_cm.groupby("Varighed", observed=True).agg(
        Kampe=("match_id", "count"),
        Win_rate=("is_victory", lambda x: round(x.sum() / len(x) * 100, 1))
    ).reset_index()
    duration_stats.columns = ["Varighed", "Kampe", "Win rate %"]

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(duration_stats, x="Varighed", y="Win rate %",
                     title="Win rate efter kampvarighed",
                     color="Win rate %", color_continuous_scale="RdYlGn",
                     text="Win rate %")
        fig.update_traces(texttemplate='%{text:.0f}%', textposition='outside')
        fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50%")
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = px.bar(duration_stats, x="Varighed", y="Kampe",
                     title="Antal kampe per varighed",
                     text="Kampe")
        fig.update_traces(texttemplate='%{text}', textposition='outside')
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    if "gold_per_min" in df.columns and df["gold_per_min"].notna().any():
        st.markdown("---")
        st.subheader("💰 GPM, XPM & Farming")
        eco = df.groupby("player_name").agg(
            GPM=("gold_per_min", "mean"),
            XPM=("xp_per_min", "mean"),
            LH=("last_hits", "mean"),
            DN=("denies", "mean"),
        ).round(1).reset_index()

        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(eco, x="player_name", y="GPM", title="Gns. GPM",
                         text="GPM", color="GPM", color_continuous_scale="YlOrRd")
            fig.update_traces(texttemplate='%{text:.0f}', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            fig = px.bar(eco, x="player_name", y="XPM", title="Gns. XPM",
                         text="XPM", color="XPM", color_continuous_scale="Blues")
            fig.update_traces(texttemplate='%{text:.0f}', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)
        with col3:
            fig = px.bar(eco, x="player_name", y="LH", title="Gns. Last Hits",
                         text="LH", color="LH", color_continuous_scale="Greens")
            fig.update_traces(texttemplate='%{text:.0f}', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with col4:
            fig = px.bar(eco, x="player_name", y="DN", title="Gns. Denies",
                         text="DN", color="DN", color_continuous_scale="Oranges")
            fig.update_traces(texttemplate='%{text:.0f}', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    if "hero_damage" in df.columns and df["hero_damage"].notna().any():
        st.markdown("---")
        st.subheader("⚔️ Damage & Impact")
        dmg = df.groupby("player_name").agg(
            Hero_dmg=("hero_damage", "mean"),
            Tower_dmg=("tower_damage", "mean"),
            Healing=("hero_healing", "mean"),
        ).round(0).reset_index()
        dmg_long = dmg.melt(id_vars="player_name", var_name="Type", value_name="Damage")
        label_map = {"Hero_dmg": "Hero Damage", "Tower_dmg": "Tower Damage", "Healing": "Healing"}
        dmg_long["Type"] = dmg_long["Type"].map(label_map)
        fig = px.bar(
            dmg_long, x="player_name", y="Damage", color="Type", barmode="group",
            title="Gns. per kamp",
            color_discrete_map={"Hero Damage": "#e74c3c", "Tower Damage": "#3498db", "Healing": "#2ecc71"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Detaljerede stats")
    detailed_stats = df.groupby("player_name").agg({
        "match_id": "count",
        "is_victory": ["sum", lambda x: (x.sum() / len(x) * 100)],
        "performance_score": ["mean", "min", "max"],
        "kda": "mean",
        "kills": "mean",
        "deaths": "mean",
        "assists": "mean",
        "is_party": "sum"
    }).round(2)
    detailed_stats.columns = ["Matches", "Wins", "Win rate %", "Gns. perf", "Min", "Max", 
                              "KDA", "Kills", "Deaths", "Assists", "Party matches"]
    detailed_stats = detailed_stats.sort_values("Gns. perf", ascending=False).reset_index()
    
    for idx, row in detailed_stats.iterrows():
        with st.container():
            col1, col2 = st.columns([1, 6])
            with col1:
                img = load_player_image(row["player_name"])
                if img:
                    img.thumbnail((80, 80))
                    st.image(img, width=80)
            with col2:
                st.markdown(f"**{row['player_name']}**")
                st.text(f"Matches: {int(row['Matches'])} | WR: {row['Win rate %']:.1f}% | Perf: {row['Gns. perf']:.1f} | KDA: {row['KDA']:.2f}")
                st.progress(min(row['Win rate %'] / 100, 1.0))
            st.markdown("---")


def show_role_page(df):
    """Role page"""
    st.header("🎯 Rolle performance")
    df_with_roles = df[df["role"] != "Unknown"].copy()
    
    if not df_with_roles.empty:
        role_stats = df_with_roles.groupby(["player_name", "role"]).agg({
            "performance_score": "mean",
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count",
            "kda": "mean"
        }).round(2).reset_index()
        role_stats.columns = ["Spiller", "Rolle", "Gns. performance", "Win rate %", "Matches", "Gns. KDA"]
        role_stats = role_stats[role_stats["Matches"] >= 3]
        
        if not role_stats.empty:
            # Add position number for sorting
            def extract_position_number(role):
                if "Pos" in role:
                    return int(role.split("Pos ")[1].rstrip(")"))
                return 999  # Unknown roles go last
            
            role_stats["position_number"] = role_stats["Rolle"].apply(extract_position_number)
            role_stats = role_stats.sort_values("position_number")
            
            # Define role order for graphs
            role_order = ["Carry (Pos 1)", "Mid (Pos 2)", "Offlane (Pos 3)", 
                         "Soft Support (Pos 4)", "Hard Support (Pos 5)"]
            
            col1, col2 = st.columns(2)
            with col1:
                fig = px.bar(role_stats, x="Rolle", y="Gns. performance", color="Spiller",
                           barmode="group", title="Performance efter rolle", text="Gns. performance",
                           category_orders={"Rolle": role_order})
                fig.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.bar(role_stats, x="Rolle", y="Win rate %", color="Spiller",
                           barmode="group", title="Win rate efter rolle", text="Win rate %",
                           category_orders={"Rolle": role_order})
                fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("⭐ Bedste rolle per spiller")
            best_roles = role_stats.loc[role_stats.groupby("Spiller")["Gns. performance"].idxmax()]
            for idx, row in best_roles.iterrows():
                col1, col2 = st.columns([1, 6])
                with col1:
                    img = load_player_image(row["Spiller"])
                    if img:
                        img.thumbnail((80, 80))
                        st.image(img, width=80)
                with col2:
                    st.markdown(f"**{row['Spiller']}** - Bedst som **{row['Rolle']}**")
                    st.text(f"Perf: {row['Gns. performance']:.1f} | WR: {row['Win rate %']:.1f}% | Matches: {int(row['Matches'])} | KDA: {row['Gns. KDA']:.2f}")
                st.markdown("---")
        else:
            st.info("Behøver 3+ matches per rolle")
    else:
        st.info("Ingen rolle data")


def show_synergy_page(df):
    """Synergy page"""
    st.header("🤝 Lanes")
    df_with_partners = df[df["lane_partner"].notna()].copy()
    
    if not df_with_partners.empty:
        laning_stats = df_with_partners.groupby(["player_name", "lane_partner", "lane", "role"]).agg({
            "performance_score": "mean",
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count",
            "kda": "mean"
        }).round(2).reset_index()
        laning_stats.columns = ["Spiller", "Partner", "Lane", "Position", "Gns. perf", "Win rate %", "Matches", "KDA"]
        laning_stats = laning_stats[laning_stats["Matches"] >= 2].sort_values("Gns. perf", ascending=False)
        
        if not laning_stats.empty:
            # Display table at top
            st.subheader("🏆 Bedste lanes")
            st.dataframe(laning_stats.nlargest(10, "Gns. perf"), use_container_width=True, hide_index=True)
            
            st.markdown("---")
            
            # Individual graphs for each player
            st.subheader("📊 Individuelle synergies")
            
            unique_players = sorted(laning_stats["Spiller"].unique())
            
            for player in unique_players:
                player_data = laning_stats[laning_stats["Spiller"] == player].copy()
                
                if not player_data.empty:
                    st.markdown(f"### {player}")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        fig = px.bar(player_data.nlargest(10, "Gns. perf"), 
                                   x="Gns. perf", y="Partner", 
                                   title=f"{player} - Top partnere (Performance)",
                                   text="Gns. perf", orientation="h",
                                   hover_data=["Lane", "Position", "Matches", "Win rate %"],
                                   color="Gns. perf", color_continuous_scale="RdYlGn")
                        fig.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                        fig.update_layout(showlegend=False, height=400)
                        st.plotly_chart(fig, use_container_width=True)
                    
                    with col2:
                        fig = px.bar(player_data.nlargest(10, "Win rate %"), 
                                   x="Win rate %", y="Partner",
                                   title=f"{player} - Top partnere (Win rate)",
                                   text="Win rate %", orientation="h",
                                   hover_data=["Lane", "Position", "Matches", "Gns. perf"],
                                   color="Win rate %", color_continuous_scale="RdYlGn")
                        fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                        fig.update_layout(showlegend=False, height=400)
                        st.plotly_chart(fig, use_container_width=True)
                    
                    st.markdown("---")
        else:
            st.info("Behøver 2+ matches sammen")
    else:
        st.info("Ingen laning partner data")

    # Support utility stats
    if "stuns" in df.columns and df["stuns"].notna().any():
        st.markdown("---")
        st.subheader("🛡️ Support utility")
        supp = df.groupby("player_name").agg(
            Stuns=("stuns", "mean"),
            Camps=("camps_stacked", "mean"),
        ).round(2).reset_index()

        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(supp, x="player_name", y="Stuns", title="Gns. Stun-tid per kamp (sek)",
                         text="Stuns", color="Stuns", color_continuous_scale="Purples")
            fig.update_traces(texttemplate='%{text:.1f}s', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            fig = px.bar(supp, x="player_name", y="Camps", title="Gns. Camps Stacked per kamp",
                         text="Camps", color="Camps", color_continuous_scale="Teal")
            fig.update_traces(texttemplate='%{text:.1f}', textposition='outside')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)


def show_latest_match_page(df, selected_players):
    """Latest match analysis page with MVP and bottom player awards"""
    st.header("🏆 Seneste match")
    
    # Find the latest match that has multiple Brohirim players
    if df.empty:
        st.warning("Ingen data tilgængelig")
        return
    
    # Group by match to find matches with multiple Brohirim players
    match_groups = df.groupby("match_id").agg({
        "player_name": lambda x: list(x),
        "match_date": "first",
        "is_victory": "first",
        "duration_min": "first"
    }).reset_index()
    
    # Filter for matches with 2+ Brohirim players
    brohirim_matches = match_groups[match_groups["player_name"].apply(len) >= 2]
    
    if brohirim_matches.empty:
        st.warning("Ingen fælles Brohirim kampe fundet i den valgte periode")
        st.info("Prøv at udvide tidsperioden i sidebaren")
        return
    
    # Sort by date and get the LATEST match (most recent first)
    brohirim_matches = brohirim_matches.sort_values("match_date", ascending=False)
    
    # Get the latest Brohirim match
    latest_match = brohirim_matches.iloc[0]
    match_id = latest_match["match_id"]
    match_date = latest_match["match_date"]
    is_victory = latest_match["is_victory"]
    match_result = "✅ Easy win" if is_victory else "❌ CHAT WIN"
    duration = latest_match["duration_min"]
    
    # Get all players from this match
    match_data = df[df["match_id"] == match_id].copy()
    
    # Display match header
    st.markdown(f"### {match_result}")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Dato", match_date.strftime("%Y-%m-%d %H:%M"))
    with col2:
        st.metric("Varighed", f"{duration:.1f} min")
    with col3:
        st.metric("Brohirim spillere", len(match_data))
    
    st.markdown("---")
    
    # Calculate comprehensive scores for MVP/Bottom ranking
    match_data["mvp_score"] = (
        match_data["performance_score"] * 0.4 +  # Performance is key
        match_data["kda"] * 10 +  # KDA weighted
        (match_data["kills"] + match_data["assists"]) * 2 -  # Kill participation
        match_data["deaths"] * 3  # Deaths penalty
    )
    
    match_data_sorted = match_data.sort_values("mvp_score", ascending=False)
    
    # MVP and Bottom player
    mvp = match_data_sorted.iloc[0]
    bottom = match_data_sorted.iloc[-1]
    
    # If victory: show MVP on top, Bottom on bottom
    # If loss: show Bottom on top, MVP on bottom
    
    if is_victory:
        # Victory: MVP first
        st.subheader("🥇 Match MVP")
        col1, col2 = st.columns([1, 3])
        with col1:
            img = load_player_image(mvp["player_name"])
            if img:
                st.image(img, use_container_width=True)
        with col2:
            st.markdown(f"## {mvp['player_name']}")
            st.markdown(f"**Hero:** {mvp['hero']} | **Rolle:** {mvp['role']}")
            
            metric_cols = st.columns(4)
            with metric_cols[0]:
                st.metric("Performance", f"{mvp['performance_score']:.1f}")
            with metric_cols[1]:
                st.metric("KDA", f"{mvp['kda']:.2f}")
            with metric_cols[2]:
                st.metric("K/D/A", f"{mvp['kills']}/{mvp['deaths']}/{mvp['assists']}")
            with metric_cols[3]:
                st.metric("Level", int(mvp['level']))
        
        st.markdown("**MVP Begrundelse:**")
        reasons = []
        if mvp['performance_score'] >= 60:
            reasons.append(f"🌟 Exceptionel performance score ({mvp['performance_score']:.1f})")
        elif mvp['performance_score'] >= 50:
            reasons.append(f"⭐ Stærk performance score ({mvp['performance_score']:.1f})")
        
        if mvp['kda'] >= 5:
            reasons.append(f"💀 Fremragende KDA ratio ({mvp['kda']:.2f})")
        elif mvp['kda'] >= 3:
            reasons.append(f"✨ God KDA ratio ({mvp['kda']:.2f})")
        
        if mvp['kills'] + mvp['assists'] >= 20:
            reasons.append(f"🎯 Høj kill participation ({mvp['kills']} kills, {mvp['assists']} assists)")
        
        if mvp['deaths'] <= 3:
            reasons.append(f"🛡️ Få deaths ({mvp['deaths']})")
        
        if not reasons:
            reasons.append(f"Bedste præstation i kampen")
        
        for reason in reasons:
            st.markdown(f"- {reason}")
        
        st.markdown("---")
        
        # Bottom player
        st.subheader("💩 Bundplacering")
        col1, col2 = st.columns([1, 3])
        with col1:
            img = load_player_image(bottom["player_name"])
            if img:
                st.image(img, use_container_width=True)
        with col2:
            st.markdown(f"## {bottom['player_name']}")
            st.markdown(f"**Hero:** {bottom['hero']} | **Rolle:** {bottom['role']}")
            
            metric_cols = st.columns(4)
            with metric_cols[0]:
                st.metric("Performance", f"{bottom['performance_score']:.1f}")
            with metric_cols[1]:
                st.metric("KDA", f"{bottom['kda']:.2f}")
            with metric_cols[2]:
                st.metric("K/D/A", f"{bottom['kills']}/{bottom['deaths']}/{bottom['assists']}")
            with metric_cols[3]:
                st.metric("Level", int(bottom['level']))
        
        st.markdown("---")
    
    else:
        # Loss: Bottom first
        st.subheader("💩 Bundplacering")
        col1, col2 = st.columns([1, 3])
        with col1:
            img = load_player_image(bottom["player_name"])
            if img:
                st.image(img, use_container_width=True)
        with col2:
            st.markdown(f"## {bottom['player_name']}")
            st.markdown(f"**Hero:** {bottom['hero']} | **Rolle:** {bottom['role']}")
            
            metric_cols = st.columns(4)
            with metric_cols[0]:
                st.metric("Performance", f"{bottom['performance_score']:.1f}")
            with metric_cols[1]:
                st.metric("KDA", f"{bottom['kda']:.2f}")
            with metric_cols[2]:
                st.metric("K/D/A", f"{bottom['kills']}/{bottom['deaths']}/{bottom['assists']}")
            with metric_cols[3]:
                st.metric("Level", int(bottom['level']))
        
        st.markdown("---")
        
        # MVP player
        st.subheader("🥇 Match MVP")
        col1, col2 = st.columns([1, 3])
        with col1:
            img = load_player_image(mvp["player_name"])
            if img:
                st.image(img, use_container_width=True)
        with col2:
            st.markdown(f"## {mvp['player_name']}")
            st.markdown(f"**Hero:** {mvp['hero']} | **Rolle:** {mvp['role']}")
            
            metric_cols = st.columns(4)
            with metric_cols[0]:
                st.metric("Performance", f"{mvp['performance_score']:.1f}")
            with metric_cols[1]:
                st.metric("KDA", f"{mvp['kda']:.2f}")
            with metric_cols[2]:
                st.metric("K/D/A", f"{mvp['kills']}/{mvp['deaths']}/{mvp['assists']}")
            with metric_cols[3]:
                st.metric("Level", int(mvp['level']))
        
        st.markdown("**MVP Begrundelse:**")
        reasons = []
        if mvp['performance_score'] >= 60:
            reasons.append(f"🌟 Exceptionel performance score ({mvp['performance_score']:.1f})")
        elif mvp['performance_score'] >= 50:
            reasons.append(f"⭐ Stærk performance score ({mvp['performance_score']:.1f})")
        
        if mvp['kda'] >= 5:
            reasons.append(f"💀 Fremragende KDA ratio ({mvp['kda']:.2f})")
        elif mvp['kda'] >= 3:
            reasons.append(f"✨ God KDA ratio ({mvp['kda']:.2f})")
        
        if mvp['kills'] + mvp['assists'] >= 20:
            reasons.append(f"🎯 Høj kill participation ({mvp['kills']} kills, {mvp['assists']} assists)")
        
        if mvp['deaths'] <= 3:
            reasons.append(f"🛡️ Få deaths ({mvp['deaths']})")
        
        if not reasons:
            reasons.append(f"Bedste præstation i kampen")
        
        for reason in reasons:
            st.markdown(f"- {reason}")
        
        st.markdown("---")
    
    # Team overview
    st.subheader("📊 Fuld holdoversigt")
    
    # Create ranking table
    ranking_data = match_data_sorted[["player_name", "hero", "role", "performance_score", 
                                       "kills", "deaths", "assists", "kda", "level"]].copy()
    ranking_data["rank"] = range(1, len(ranking_data) + 1)
    ranking_data["medal"] = ranking_data["rank"].apply(
        lambda x: "🥇" if x == 1 else "🥈" if x == 2 else "🥉" if x == 3 else "💩" if x == len(ranking_data) else ""
    )
    
    ranking_data = ranking_data[["medal", "rank", "player_name", "hero", "role", 
                                 "performance_score", "kda", "kills", "deaths", "assists", "level"]]
    ranking_data.columns = ["", "Rank", "Spiller", "Hero", "Rolle", "Performance", 
                            "KDA", "K", "D", "A", "Lvl"]
    
    st.dataframe(ranking_data, use_container_width=True, hide_index=True)
    
    # Performance comparison chart
    st.subheader("📈 Performance sammenligning")
    fig = px.bar(match_data_sorted, x="player_name", y="performance_score",
                 title="Performance Score",
                 color="performance_score",
                 color_continuous_scale="RdYlGn",
                 text="performance_score")
    fig.update_traces(texttemplate='%{text:.1f}', textposition='outside')
    fig.update_layout(showlegend=False, xaxis_title="Spiller", yaxis_title="Performance Score")
    st.plotly_chart(fig, use_container_width=True)
    
    # KDA comparison
    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(match_data_sorted, x="player_name", y="kda",
                     title="KDA Ratio",
                     color="kda",
                     color_continuous_scale="RdYlGn",
                     text="kda")
        fig.update_traces(texttemplate='%{text:.2f}', textposition='outside')
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Create kills/deaths/assists breakdown
        breakdown_data = []
        for _, row in match_data_sorted.iterrows():
            breakdown_data.append({"Spiller": row["player_name"], "Type": "Kills", "Antal": row["kills"]})
            breakdown_data.append({"Spiller": row["player_name"], "Type": "Deaths", "Antal": row["deaths"]})
            breakdown_data.append({"Spiller": row["player_name"], "Type": "Assists", "Antal": row["assists"]})
        
        breakdown_df = pd.DataFrame(breakdown_data)
        fig = px.bar(breakdown_df, x="Spiller", y="Antal", color="Type",
                     title="Kills / Deaths / Assists",
                     barmode="group",
                     color_discrete_map={"Kills": "#2ecc71", "Deaths": "#e74c3c", "Assists": "#3498db"})
        st.plotly_chart(fig, use_container_width=True)


def show_hero_page(df):
    """Hero statistics page"""
    st.header("🦸 Heroes")

    hero_stats = df.groupby("hero").agg(
        Matches=("match_id", "count"),
        Win_rate=("is_victory", lambda x: round(x.sum() / len(x) * 100, 1)),
        Avg_perf=("performance_score", lambda x: round(x.mean(), 1)),
        Avg_kda=("kda", lambda x: round(x.mean(), 2)),
    ).reset_index()
    hero_stats = hero_stats[hero_stats["Matches"] >= 2]
    hero_stats.columns = ["Hero", "Matches", "Win rate %", "Gns. perf", "Gns. KDA"]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏆 Bedste win rate (min 2 matches)")
        top_wr = hero_stats.nlargest(10, "Win rate %")
        fig = px.bar(top_wr, x="Win rate %", y="Hero", orientation="h",
                     color="Win rate %", color_continuous_scale="RdYlGn",
                     text="Win rate %", hover_data=["Matches", "Gns. perf"])
        fig.update_traces(texttemplate='%{text:.0f}%', textposition='outside')
        fig.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("🎯 Mest spillede")
        top_played = hero_stats.nlargest(10, "Matches")
        fig = px.bar(top_played, x="Matches", y="Hero", orientation="h",
                     color="Win rate %", color_continuous_scale="RdYlGn",
                     text="Matches", hover_data=["Win rate %", "Gns. perf"])
        fig.update_traces(texttemplate='%{text}', textposition='outside')
        fig.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("👤 Per spiller (min 2 matches)")

    player_hero = df.groupby(["player_name", "hero"]).agg(
        Matches=("match_id", "count"),
        Win_rate=("is_victory", lambda x: round(x.sum() / len(x) * 100, 1)),
        Avg_perf=("performance_score", lambda x: round(x.mean(), 1)),
        Avg_kda=("kda", lambda x: round(x.mean(), 2)),
    ).reset_index()
    player_hero = player_hero[player_hero["Matches"] >= 2]
    player_hero.columns = ["Spiller", "Hero", "Matches", "Win rate %", "Gns. perf", "Gns. KDA"]

    for player in sorted(df["player_name"].unique()):
        pdata = player_hero[player_hero["Spiller"] == player]
        if pdata.empty:
            continue
        with st.expander(f"**{player}** – {len(pdata)} helte (min 2 matches)"):
            col1, col2 = st.columns(2)
            with col1:
                top = pdata.nlargest(8, "Gns. perf")
                fig = px.bar(top, x="Gns. perf", y="Hero", orientation="h",
                             title="Bedste performance",
                             color="Gns. perf", color_continuous_scale="RdYlGn",
                             text="Gns. perf", hover_data=["Matches", "Win rate %"])
                fig.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig.update_layout(showlegend=False, height=350)
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                top = pdata.nlargest(8, "Matches")
                fig = px.bar(top, x="Matches", y="Hero", orientation="h",
                             title="Mest spillede",
                             color="Win rate %", color_continuous_scale="RdYlGn",
                             text="Matches", hover_data=["Gns. perf", "Win rate %"])
                fig.update_traces(texttemplate='%{text}', textposition='outside')
                fig.update_layout(showlegend=False, height=350)
                st.plotly_chart(fig, use_container_width=True)


def show_activity_page(df):
    """Activity heatmap and personal records"""
    st.header("📅 Aktivitet & Rekorder")

    # --- HVORNÅR SPILLER VI? ---
    st.subheader("🕐 Hvornår spiller vi?")
    match_times = df.drop_duplicates("match_id")[["match_id", "match_date"]].copy()
    day_map = {0: "Mandag", 1: "Tirsdag", 2: "Onsdag", 3: "Torsdag",
               4: "Fredag", 5: "Lørdag", 6: "Søndag"}
    day_order = list(day_map.values())

    match_times["ugedag"] = match_times["match_date"].dt.dayofweek.map(day_map)
    match_times["time"] = match_times["match_date"].dt.hour

    heatmap_data = (
        match_times.groupby(["ugedag", "time"])
        .size()
        .reset_index(name="Kampe")
        .pivot(index="ugedag", columns="time", values="Kampe")
        .fillna(0)
    )
    heatmap_data = heatmap_data.reindex([d for d in day_order if d in heatmap_data.index])

    fig = px.imshow(
        heatmap_data,
        labels=dict(x="Tidspunkt (time)", y="Ugedag", color="Kampe"),
        title="Kampe per ugedag og tidspunkt",
        color_continuous_scale="Blues",
        aspect="auto",
    )
    fig.update_xaxes(tickmode="linear", tick0=0, dtick=1)
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)

    if not match_times.empty:
        top_day = match_times["ugedag"].value_counts().index[0]
        top_hour = int(match_times["time"].value_counts().index[0])
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Mest aktive dag", top_day)
        with col2:
            st.metric("Peak tidspunkt", f"{top_hour}:00–{top_hour + 1}:00")
        with col3:
            st.metric("Unikke kampe i alt", len(match_times))

    st.markdown("---")

    # --- AWARDS ---
    if "award" in df.columns and df["award"].notna().any() and (df["award"] != "NONE").any():
        st.subheader("🏆 Awards")
        award_icons = {"MVP": "🏆 MVP", "TOP_CORE": "⚔️ Top Core", "TOP_SUPPORT": "🛡️ Top Support"}
        awards_df = df[df["award"] != "NONE"].copy()
        awards_df["Award"] = awards_df["award"].map(award_icons).fillna(awards_df["award"])
        awards_agg = awards_df.groupby(["player_name", "Award"]).size().reset_index(name="Antal")
        fig = px.bar(awards_agg, x="player_name", y="Antal", color="Award", barmode="group",
                     title="Antal awards per spiller",
                     color_discrete_map={"🏆 MVP": "#FFD700", "⚔️ Top Core": "#e74c3c", "🛡️ Top Support": "#3498db"})
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("---")

    # --- MMR PROGRESSION ---
    if "season_rank" in df.columns and df["season_rank"].notna().any():
        st.subheader("📈 MMR Progression")
        rank_df = df[df["season_rank"].notna()][["player_name", "match_date", "season_rank"]].copy()
        rank_df = rank_df.sort_values("match_date")
        rank_df["Rank label"] = rank_df["season_rank"].apply(decode_rank)
        fig = px.line(rank_df, x="match_date", y="season_rank", color="player_name",
                      title="MMR badge over tid (højere = bedre)",
                      labels={"season_rank": "Rank (råværdi)", "match_date": "Dato", "player_name": "Spiller"},
                      custom_data=["Rank label"])
        fig.update_traces(hovertemplate="%{customdata[0]}<extra></extra>")
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("---")

    # --- PERSONLIGE REKORDER ---
    st.subheader("🏅 Personlige rekorder")
    records_data = []
    has_gpm = "gold_per_min" in df.columns and df["gold_per_min"].notna().any()
    has_dmg = "hero_damage" in df.columns and df["hero_damage"].notna().any()
    for player in sorted(df["player_name"].unique()):
        pdata = df[df["player_name"] == player]
        if pdata.empty:
            continue
        kda_row = pdata.loc[pdata["kda"].idxmax()]
        perf_row = pdata.loc[pdata["performance_score"].idxmax()]
        kills_row = pdata.loc[pdata["kills"].idxmax()]
        rec = {
            "Spiller": player,
            "Bedste KDA": f"{kda_row['kda']:.2f} ({kda_row['hero']})",
            "Højeste performance": f"{perf_row['performance_score']:.0f} ({perf_row['hero']})",
            "Flest kills": f"{int(kills_row['kills'])} ({kills_row['hero']})",
        }
        if has_gpm:
            gpm_row = pdata.loc[pdata["gold_per_min"].idxmax()]
            rec["Højeste GPM"] = f"{int(gpm_row['gold_per_min'])} ({gpm_row['hero']})"
        if has_dmg:
            dmg_row = pdata.loc[pdata["hero_damage"].idxmax()]
            rec["Mest hero damage"] = f"{int(dmg_row['hero_damage']):,} ({dmg_row['hero']})"
        records_data.append(rec)
    st.dataframe(pd.DataFrame(records_data), use_container_width=True, hide_index=True)


def show_match_history_page(df):
    """Match history page"""
    st.header("📋 Matches")

    col1, col2, col3 = st.columns(3)
    with col1:
        show_count = st.selectbox("Vis matches", [10, 20, 50, 100], index=1)
    with col2:
        filter_result = st.selectbox("Resultat", ["Alle", "Wins", "Losses"])
    with col3:
        filter_party = st.selectbox("Type", ["Alle", "Party", "Solo"])

    filtered_df = df.copy()
    if filter_result == "Wins":
        filtered_df = filtered_df[filtered_df["is_victory"] == True]
    elif filter_result == "Losses":
        filtered_df = filtered_df[filtered_df["is_victory"] == False]

    if filter_party == "Party":
        filtered_df = filtered_df[filtered_df["is_party"] == True]
    elif filter_party == "Solo":
        filtered_df = filtered_df[filtered_df["is_party"] == False]

    base_cols = ["match_id", "match_date", "player_name", "hero", "role", "lane",
                 "is_victory", "performance_score", "kills", "deaths", "assists", "kda",
                 "is_party", "lane_partner"]

    # Add optional columns when present
    has_gpm = "gold_per_min" in filtered_df.columns and filtered_df["gold_per_min"].notna().any()
    has_items = "item0_id" in filtered_df.columns
    has_game_mode = "game_mode" in filtered_df.columns

    extra_cols = []
    if has_gpm:
        extra_cols.append("gold_per_min")
    if has_items:
        extra_cols += ["item0_id", "item1_id", "item2_id", "item3_id", "item4_id", "item5_id", "neutral_item_id"]
    if has_game_mode:
        extra_cols.append("game_mode")

    recent = filtered_df.sort_values("match_date", ascending=False).head(show_count)[
        base_cols + extra_cols
    ].copy()

    recent["link"] = recent["match_id"].apply(lambda x: f"https://www.dotabuff.com/matches/{x}")
    recent = recent.drop(columns=["match_id"])
    recent["match_date"] = recent["match_date"].dt.strftime("%Y-%m-%d %H:%M")
    recent["is_victory"] = recent["is_victory"].map({True: "✅ Win", False: "❌ Loss"})
    recent["is_party"] = recent["is_party"].map({True: "👥", False: "🧍"})

    col_names = ["Dato", "Spiller", "Hero", "Rolle", "Lane", "Resultat", "Perf",
                 "K", "D", "A", "KDA", "Party", "Lane partner"]
    if has_gpm:
        recent["gold_per_min"] = recent["gold_per_min"].round(0).astype("Int64")
        col_names.append("GPM")
    if has_items:
        item_names = load_item_names()
        item_id_cols = ["item0_id", "item1_id", "item2_id", "item3_id", "item4_id", "item5_id", "neutral_item_id"]
        recent["Items"] = recent.apply(lambda r: format_items(r, item_names), axis=1)
        recent = recent.drop(columns=item_id_cols)
        col_names.append("Items")
    if has_game_mode:
        gm_labels = {"TURBO": "⚡ Turbo", "ALL_PICK_RANKED": "🏅 Ranked", "ALL_PICK": "🎮 Normal",
                     "CAPTAINS_MODE": "⚔️ CM", "ABILITY_DRAFT": "🎲 AD"}
        recent["game_mode"] = recent["game_mode"].apply(
            lambda m: gm_labels.get(m, "🎮 " + (m or "").replace("_", " ").title() if m else "")
        )
        col_names.append("Mode")

    col_names.append("🔗")
    recent.columns = col_names

    st.dataframe(
        recent,
        column_config={"🔗": st.column_config.LinkColumn("🔗", display_text="Dotabuff")},
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("💾 Eksport")
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name=f"brohirim_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )


if __name__ == "__main__":
    main()
