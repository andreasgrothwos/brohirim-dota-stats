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


@st.cache_data(ttl=3600)
def fetch_all_matches_for_player(steam_id, player_name, cutoff_date):
    """Fetch ALL matches since cutoff_date for a player (using batching)"""
    
    all_matches = []
    skip = 0
    batch_size = 100
    max_batches = 5  # Reduced to 5 batches = 500 matches max to avoid rate limiting
    
    query = """
    query($steamAccountId: Long!, $take: Int!, $skip: Int!) {
      player(steamAccountId: $steamAccountId) {
        steamAccountId
        matches(request: { take: $take, skip: $skip }) {
          id
          startDateTime
          durationSeconds
          didRadiantWin
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
            
            # Check if oldest match in batch is before cutoff
            oldest_match_time = min(m["startDateTime"] for m in matches)
            oldest_match_date = datetime.fromtimestamp(oldest_match_time)
            
            # Filter matches within date range
            valid_matches = [m for m in matches if datetime.fromtimestamp(m["startDateTime"]) >= cutoff_date]
            all_matches.extend(valid_matches)
            
            # Stop if oldest match is before cutoff
            if oldest_match_date < cutoff_date:
                break
            
            # Stop if fewer matches than requested
            if len(matches) < batch_size:
                break
            
            skip += batch_size
            time.sleep(0.5)  # Rate limiting between batches
            
        except Exception as e:
            st.error(f"Exception fetching {player_name}: {str(e)}")
            break
    
    return all_matches


def process_matches(matches, steam_id, player_name, all_steam_ids):
    """Process raw match data into structured format"""
    
    processed_data = []
    
    for match in matches:
        match_id = match["id"]
        match_date = datetime.fromtimestamp(match["startDateTime"])
        duration_min = round(match["durationSeconds"] / 60, 1)
        
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
        
        processed_data.append({
            "player_name": player_name,
            "match_id": match_id,
            "match_date": match_date,
            "duration_min": duration_min,
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
            "lane_partner": ", ".join(lane_partner_names) if lane_partner_names else None
        })
    
    return processed_data


@st.cache_data(ttl=7200)  # Cache for 2 hours
def load_full_year_data(selected_players):
    """Load ALL matches from last year - ONE TIME ONLY"""
    
    cutoff_date = datetime.now() - timedelta(days=365)
    all_data = []
    all_steam_ids = [PLAYERS[p] for p in selected_players]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, player_name in enumerate(selected_players):
        status_text.text(f"📥 Fetching matches for {player_name}...")
        steam_id = PLAYERS[player_name]
        
        try:
            matches = fetch_all_matches_for_player(steam_id, player_name, cutoff_date)
            
            if matches:
                processed = process_matches(matches, steam_id, player_name, all_steam_ids)
                all_data.extend(processed)
                status_text.text(f"✅ {len(processed)} matches for {player_name}")
            else:
                status_text.text(f"⚠️ No matches found for {player_name}")
                st.warning(f"Could not load matches for {player_name}. Check API key or try again.")
        except Exception as e:
            st.error(f"Error loading {player_name}: {str(e)}")
            status_text.text(f"❌ Error for {player_name}")
        
        progress_bar.progress((idx + 1) / len(selected_players))
        time.sleep(1)  # Longer delay between players to avoid rate limiting
    
    status_text.empty()
    progress_bar.empty()
    
    df = pd.DataFrame(all_data)
    
    if not df.empty:
        st.success(f"✅ Loaded {len(df)} matches from {len(df['player_name'].unique())} players! Cached for 2 hours.")
    else:
        st.error("⚠️ No data was loaded. This could be due to:")
        st.info("1. API rate limiting - wait a few minutes and click 'Refresh Data'\n2. API key issues\n3. No matches in the last year")
    
    return df


def display_player_cards(selected_players, df):
    """Display player cards sorted by performance"""
    st.subheader("👥 Spilleroversigt (sorteret efter performance)")
    
    player_stats = []
    for player in selected_players:
        player_data = df[df["player_name"] == player]
        if not player_data.empty:
            matches = len(player_data)
            win_rate = (player_data["is_victory"].sum() / matches * 100)
            avg_perf = player_data["performance_score"].mean()
            player_stats.append({
                "name": player,
                "matches": matches,
                "win_rate": win_rate,
                "avg_perf": avg_perf
            })
    
    player_stats.sort(key=lambda x: x["avg_perf"], reverse=True)
    
    cols = st.columns(len(player_stats))
    
    for idx, player_info in enumerate(player_stats):
        player = player_info["name"]
        with cols[idx]:
            img = load_player_image(player)
            if img:
                st.image(img, use_container_width=True)
            
            if idx == 0:
                st.markdown(f"### 🥇 {player}")
            elif idx == 1:
                st.markdown(f"### 🥈 {player}")
            elif idx == 2:
                st.markdown(f"### 🥉 {player}")
            else:
                st.markdown(f"### {player}")
            
            st.metric("Matches", player_info["matches"])
            st.metric("Win rate", f"{player_info['win_rate']:.1f}%")
            st.metric("Gns. performance", f"{player_info['avg_perf']:.1f}")
    
    st.markdown("---")


def main():
    """Main app"""
    
    st.title("👏 Brohirim Dota")
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Indstillinger")
        
        page = st.selectbox(
            "📄 Vælg side",
            ["🏠 Overblik", "📊 Performance", "🎯 Rolle & position", "🤝 Lanes", "📋 Matches"]
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
            index=3,
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
            "Begræns til seneste N kampe",
            options=["Alle kampe", "Sidste 10", "Sidste 20", "Sidste 50"],
            index=0,
            help="Seneste N kampe per spiller"
        )
        
        st.markdown("---")
        if st.button("🔄 Opdater data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        if st.button("⚡ Quick refresh (seneste timer)", use_container_width=True, help="Indlæser kun matches fra de seneste 3 timer"):
            # Clear only the fetch cache to get fresh recent data
            fetch_all_matches_for_player.clear()
            st.rerun()
        
        st.markdown("---")
        st.caption("💡 Data indlæst én gang, cached 2 timer")
        st.caption(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    
    if not selected_players:
        st.warning("Vælg mindst én spiller")
        return
    
    # Load data once
    with st.spinner("🔄 Indlæser data fra det sidste år..."):
        df_full = load_full_year_data(selected_players)
    
    if df_full.empty:
        st.error("Ingen data tilgængelig")
        return
    
    # Filter in memory - NO API CALLS
    df = df_full.copy()
    
    if filter_start_date:
        df = df[df["match_date"] >= filter_start_date]
    
    if limit_matches != "Alle kampe":
        n = int(limit_matches.split()[-1])
        df = df.sort_values("match_date", ascending=False).groupby("player_name").head(n).reset_index(drop=True)
    
    if df.empty:
        st.warning("Ingen matches med nuværende filtre")
        return
    
    st.info(f"📊 {len(df)} matches | {df['match_date'].min().date()} til {df['match_date'].max().date()}")
    
    # Route to pages
    if page == "🏠 Overblik":
        show_overview_page(df, selected_players)
    elif page == "📊 Performance":
        show_performance_page(df, selected_players)
    elif page == "🎯 Rolle & position":
        show_role_page(df)
    elif page == "🤝 Lanes":
        show_synergy_page(df)
    elif page == "📋 Matches":
        show_match_history_page(df)


def show_overview_page(df, selected_players):
    """Overview page"""
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
    
    st.subheader("📋 Detaljerede statistikker")
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
    st.header("🎯 Role performance")
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
            
            st.subheader("⭐ Bedste role for hver Brohirim spiller")
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
            st.subheader("🏆 Bedste lane combos")
            st.dataframe(laning_stats.nlargest(10, "Gns. perf"), use_container_width=True, hide_index=True)
            
            st.markdown("---")
            
            # Individual graphs for each player
            st.subheader("📊 Individuelle spillergrafer")
            
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
    
    recent = filtered_df.sort_values("match_date", ascending=False).head(show_count)[
        ["match_date", "player_name", "hero", "role", "lane", "is_victory", "performance_score", 
         "kills", "deaths", "assists", "kda", "is_party", "lane_partner"]
    ].copy()
    
    recent["match_date"] = recent["match_date"].dt.strftime("%Y-%m-%d %H:%M")
    recent["is_victory"] = recent["is_victory"].map({True: "✅ Win", False: "❌ Loss"})
    recent["is_party"] = recent["is_party"].map({True: "👥", False: "🧍"})
    recent.columns = ["Dato", "Spiller", "Hero", "Rolle", "Lane", "Resultat", "Perf", 
                     "K", "D", "A", "KDA", "Party", "Lane partner"]
    
    st.dataframe(recent, use_container_width=True, hide_index=True)
    
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
