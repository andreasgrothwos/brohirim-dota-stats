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

# Page configuration
st.set_page_config(
    page_title="Brohirim Dota 2 Stats",
    page_icon="🎮",
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
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJTdWJqZWN0IjoiYjc5NjU4N2EtY2M3Mi00MGQ1LThmMzktM2I0ZWU2ZjNkOGEzIiwiU3RlYW1JZCI6IjMzMzYyNjQiLCJBUElVc2VyIjoidHJ1ZSIsIm5iZiI6MTc2NTE0MDAxMCwiZXhwIjoxNzk2Njc2MDEwLCJpYXQiOjE3NjUxNDAwMTAsImlzcyI6Imh0dHBzOi8vYXBpLnN0cmF0ei5jb20ifQ.Cs97lOQWaxAvZlIwW2YKrKIt6niGTw6B9_Q4YbW1ZYc"


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_player_matches(steam_id, player_name, num_matches=100):
    """Fetch match data for a single player from Stratz API"""
    
    query = """
    query($steamAccountId: Long!, $take: Int!) {
      player(steamAccountId: $steamAccountId) {
        steamAccountId
        matches(request: { take: $take }) {
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
    
    variables = {
        "steamAccountId": steam_id,
        "take": min(num_matches, 100)  # API limit
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "STRATZ_API",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            "https://api.stratz.com/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 200:
            st.error(f"HTTP error for {player_name}: {response.status_code}")
            return None
        
        data = response.json()
        
        if "errors" in data:
            st.error(f"GraphQL errors for {player_name}: {data['errors']}")
            return None
        
        if not data.get("data", {}).get("player", {}).get("matches"):
            st.warning(f"No matches found for {player_name}")
            return None
        
        return data["data"]["player"]["matches"]
    
    except Exception as e:
        st.error(f"Error for {player_name}: {str(e)}")
        return None


def process_matches(matches, steam_id, player_name, all_steam_ids):
    """Process raw match data into a structured format"""
    
    processed_data = []
    
    for match in matches:
        match_id = match["id"]
        match_date = datetime.fromtimestamp(match["startDateTime"])
        duration_min = round(match["durationSeconds"] / 60, 1)
        
        players = match["players"]
        
        # Find this player's data
        player_data = next((p for p in players if p["steamAccountId"] == steam_id), None)
        
        if not player_data:
            continue
        
        # Find Brohirim teammates
        is_radiant = player_data["isRadiant"]
        teammates = [p for p in players if p["isRadiant"] == is_radiant and p["steamAccountId"] != steam_id]
        brohirim_teammates = [t for t in teammates if t["steamAccountId"] in all_steam_ids]
        
        # Party detection
        is_party = len(brohirim_teammates) > 0
        friend_names = [list(PLAYERS.keys())[list(PLAYERS.values()).index(t["steamAccountId"])] 
                       for t in brohirim_teammates]
        
        # Calculate KDA
        kills = player_data["kills"]
        deaths = max(player_data["deaths"], 1)
        assists = player_data["assists"]
        kda = round((kills + assists) / deaths, 2)
        
        # Map position to role name
        position_map = {
            "POSITION_1": "Carry (Pos 1)",
            "POSITION_2": "Mid (Pos 2)",
            "POSITION_3": "Offlane (Pos 3)",
            "POSITION_4": "Soft Support (Pos 4)",
            "POSITION_5": "Hard Support (Pos 5)",
            "UNKNOWN": "Unknown"
        }
        
        position = player_data.get("position", "UNKNOWN")
        role = position_map.get(position, "Unknown")
        
        # Get lane info for laning analysis
        lane_map = {
            "SAFE_LANE": "Safe Lane",
            "MID_LANE": "Mid Lane",
            "OFF_LANE": "Off Lane",
            "JUNGLE": "Jungle",
            "ROAMING": "Roaming",
            "UNKNOWN": "Unknown"
        }
        lane = player_data.get("lane", "UNKNOWN")
        lane_name = lane_map.get(lane, "Unknown")
        
        # Find teammates in same lane (for laning partner analysis)
        same_lane_teammates = [
            t for t in brohirim_teammates 
            if t.get("lane") == lane and lane != "UNKNOWN"
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
            "position": position,
            "role": role,
            "lane": lane_name,
            "is_party": is_party,
            "party_with": ", ".join(friend_names) if friend_names else None,
            "lane_partner": ", ".join(lane_partner_names) if lane_partner_names else None
        })
    
    return processed_data


@st.cache_data(ttl=3600)
def load_all_data(selected_players, num_matches=100):
    """Load data for all selected players"""
    
    all_data = []
    all_steam_ids = [PLAYERS[p] for p in selected_players]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, player_name in enumerate(selected_players):
        status_text.text(f"Fetching data for {player_name}...")
        steam_id = PLAYERS[player_name]
        
        matches = fetch_player_matches(steam_id, player_name, num_matches)
        
        if matches:
            processed = process_matches(matches, steam_id, player_name, all_steam_ids)
            all_data.extend(processed)
        
        progress_bar.progress((idx + 1) / len(selected_players))
        time.sleep(0.5)  # Rate limiting
    
    status_text.empty()
    progress_bar.empty()
    
    return pd.DataFrame(all_data)


def main():
    """Main Streamlit app"""
    
    # Header
    st.title("🎮 Brohirim Dota 2 Statistics Dashboard")
    st.markdown("---")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        selected_players = st.multiselect(
            "Select Players",
            options=list(PLAYERS.keys()),
            default=list(PLAYERS.keys())
        )
        
        num_matches = st.slider(
            "Number of matches to fetch (per player)",
            min_value=10,
            max_value=100,
            value=100,
            step=10,
            help="API limit is 100 matches per player"
        )
        
        date_filter = st.selectbox(
            "Date Filter",
            options=["All time", "Last 7 days", "Last 30 days", "2025 only", "Custom"],
            index=0
        )
        
        start_date = None
        if date_filter == "Last 7 days":
            start_date = datetime.now() - timedelta(days=7)
        elif date_filter == "Last 30 days":
            start_date = datetime.now() - timedelta(days=30)
        elif date_filter == "2025 only":
            start_date = datetime(2025, 1, 1)
        elif date_filter == "Custom":
            start_date = st.date_input("Start date", value=datetime(2025, 1, 1))
            start_date = datetime.combine(start_date, datetime.min.time())
        
        st.markdown("---")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("---")
        st.caption("Data updates hourly automatically")
        st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")
    
    if not selected_players:
        st.warning("Please select at least one player")
        return
    
    # Load data
    with st.spinner("Loading match data..."):
        df = load_all_data(selected_players, num_matches)
    
    if df.empty:
        st.error("No data available. Check your API key or try again later.")
        return
    
    # Apply date filter
    if start_date:
        df = df[df["match_date"] >= start_date]
        if df.empty:
            st.warning(f"No matches found since {start_date.date()}")
            return
    
    # Display summary metrics
    st.header("📊 Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Matches", len(df))
    with col2:
        win_rate = (df["is_victory"].sum() / len(df) * 100)
        st.metric("Overall Win Rate", f"{win_rate:.1f}%")
    with col3:
        avg_perf = df["performance_score"].mean()
        st.metric("Avg Performance", f"{avg_perf:.1f}")
    with col4:
        party_rate = (df["is_party"].sum() / len(df) * 100)
        st.metric("Party Game Rate", f"{party_rate:.1f}%")
    
    st.markdown("---")
    
    # Player comparison
    st.header("👥 Player Comparison")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Performance scores bar chart
        player_stats = df.groupby("player_name").agg({
            "performance_score": "mean",
            "match_id": "count"
        }).round(2).reset_index()
        player_stats.columns = ["Player", "Avg Performance", "Matches"]
        player_stats = player_stats.sort_values("Avg Performance", ascending=True)
        
        fig1 = px.bar(
            player_stats,
            x="Avg Performance",
            y="Player",
            orientation="h",
            title="Average Performance Score by Player",
            text="Avg Performance",
            color="Avg Performance",
            color_continuous_scale="RdYlGn"
        )
        fig1.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig1.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig1, use_container_width=True)
    
    with col2:
        # Win rate comparison
        win_stats = df.groupby("player_name").agg({
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count"
        }).round(1).reset_index()
        win_stats.columns = ["Player", "Win Rate %", "Matches"]
        win_stats = win_stats.sort_values("Win Rate %", ascending=True)
        
        fig2 = px.bar(
            win_stats,
            x="Win Rate %",
            y="Player",
            orientation="h",
            title="Win Rate by Player",
            text="Win Rate %",
            color="Win Rate %",
            color_continuous_scale="RdYlGn"
        )
        fig2.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig2.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig2, use_container_width=True)
    
    # Performance distribution
    st.header("📈 Performance Distribution")
    
    fig3 = px.box(
        df,
        x="player_name",
        y="performance_score",
        color="player_name",
        title="Performance Score Distribution (Box Plot)",
        labels={"player_name": "Player", "performance_score": "Performance Score"}
    )
    fig3.update_layout(showlegend=False, height=400)
    st.plotly_chart(fig3, use_container_width=True)
    
    # Party vs Solo
    st.header("👥 Party vs Solo Performance")
    
    party_comparison = df.groupby(["player_name", "is_party"]).agg({
        "performance_score": "mean",
        "is_victory": lambda x: (x.sum() / len(x) * 100),
        "match_id": "count"
    }).round(2).reset_index()
    party_comparison.columns = ["Player", "Is Party", "Avg Performance", "Win Rate %", "Matches"]
    party_comparison["Game Type"] = party_comparison["Is Party"].map({True: "Party", False: "Solo"})
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig4 = px.bar(
            party_comparison,
            x="Player",
            y="Avg Performance",
            color="Game Type",
            barmode="group",
            title="Performance: Party vs Solo",
            text="Avg Performance"
        )
        fig4.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        st.plotly_chart(fig4, use_container_width=True)
    
    with col2:
        fig5 = px.bar(
            party_comparison,
            x="Player",
            y="Win Rate %",
            color="Game Type",
            barmode="group",
            title="Win Rate: Party vs Solo",
            text="Win Rate %"
        )
        fig5.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        st.plotly_chart(fig5, use_container_width=True)
    
    # Party combinations
    if df["is_party"].any():
        st.header("🤝 Party Combinations")
        
        party_games = df[df["is_party"] & df["party_with"].notna()].copy()
        
        if not party_games.empty:
            party_combos = party_games.groupby(["player_name", "party_with"]).size().reset_index(name="Games Together")
            party_combos = party_combos.sort_values("Games Together", ascending=False)
            
            st.dataframe(
                party_combos,
                use_container_width=True,
                hide_index=True
            )
    
    # Performance over time
    st.header("📅 Performance Over Time")
    
    df_sorted = df.sort_values("match_date")
    
    fig6 = px.line(
        df_sorted,
        x="match_date",
        y="performance_score",
        color="player_name",
        title="Performance Score Trend",
        labels={"match_date": "Date", "performance_score": "Performance Score", "player_name": "Player"}
    )
    fig6.add_hline(y=df["performance_score"].mean(), line_dash="dash", annotation_text="Overall Average")
    st.plotly_chart(fig6, use_container_width=True)
    
    # ROLE PERFORMANCE ANALYSIS
    st.header("🎯 Role Performance Analysis")
    
    # Filter out Unknown roles for cleaner analysis
    df_with_roles = df[df["role"] != "Unknown"].copy()
    
    if not df_with_roles.empty:
        role_stats = df_with_roles.groupby(["player_name", "role"]).agg({
            "performance_score": "mean",
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count",
            "kda": "mean"
        }).round(2).reset_index()
        role_stats.columns = ["Player", "Role", "Avg Performance", "Win Rate %", "Games", "Avg KDA"]
        
        # Only show roles with at least 3 games
        role_stats = role_stats[role_stats["Games"] >= 3]
        
        if not role_stats.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Performance by role
                fig_role_perf = px.bar(
                    role_stats,
                    x="Role",
                    y="Avg Performance",
                    color="Player",
                    barmode="group",
                    title="Average Performance by Role",
                    text="Avg Performance"
                )
                fig_role_perf.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig_role_perf.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_role_perf, use_container_width=True)
            
            with col2:
                # Win rate by role
                fig_role_wr = px.bar(
                    role_stats,
                    x="Role",
                    y="Win Rate %",
                    color="Player",
                    barmode="group",
                    title="Win Rate by Role",
                    text="Win Rate %"
                )
                fig_role_wr.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_role_wr.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_role_wr, use_container_width=True)
            
            # Heatmap showing best roles for each player
            st.subheader("🔥 Role Performance Heatmap")
            
            pivot_perf = role_stats.pivot(index="Player", columns="Role", values="Avg Performance")
            pivot_games = role_stats.pivot(index="Player", columns="Role", values="Games")
            
            # Create custom text showing performance and game count
            custom_text = []
            for i, player in enumerate(pivot_perf.index):
                row_text = []
                for role in pivot_perf.columns:
                    perf = pivot_perf.loc[player, role]
                    games = pivot_games.loc[player, role]
                    if pd.notna(perf):
                        row_text.append(f"{perf:.1f}<br>({int(games)} games)")
                    else:
                        row_text.append("")
                custom_text.append(row_text)
            
            fig_heatmap = go.Figure(data=go.Heatmap(
                z=pivot_perf.values,
                x=pivot_perf.columns,
                y=pivot_perf.index,
                text=custom_text,
                texttemplate='%{text}',
                colorscale='RdYlGn',
                colorbar=dict(title="Performance"),
                hoverongaps=False
            ))
            
            fig_heatmap.update_layout(
                title="Performance Score by Player and Role (min 3 games)",
                xaxis_title="Role",
                yaxis_title="Player",
                height=400
            )
            
            st.plotly_chart(fig_heatmap, use_container_width=True)
            
            # Best role for each player
            st.subheader("⭐ Best Role for Each Player")
            
            best_roles = role_stats.loc[role_stats.groupby("Player")["Avg Performance"].idxmax()]
            best_roles_display = best_roles[["Player", "Role", "Avg Performance", "Win Rate %", "Games", "Avg KDA"]]
            
            st.dataframe(
                best_roles_display,
                use_container_width=True,
                hide_index=True
            )
            
            # Role distribution
            st.subheader("📊 Role Distribution")
            
            role_distribution = df_with_roles.groupby(["player_name", "role"]).size().reset_index(name="Games")
            
            fig_role_dist = px.sunburst(
                role_distribution,
                path=["player_name", "role"],
                values="Games",
                title="How Often Each Player Plays Each Role"
            )
            st.plotly_chart(fig_role_dist, use_container_width=True)
        else:
            st.info("Not enough games per role for analysis (minimum 3 games required)")
    else:
        st.info("No role information available in the data")
    
    # LANING PARTNER ANALYSIS
    st.header("🤝 Laning Partner Analysis")
    
    df_with_partners = df[df["lane_partner"].notna()].copy()
    
    if not df_with_partners.empty:
        st.write("Analysis of performance when laning with teammates")
        
        # Create laning partner combinations
        laning_stats = df_with_partners.groupby(["player_name", "lane_partner", "lane"]).agg({
            "performance_score": "mean",
            "is_victory": lambda x: (x.sum() / len(x) * 100),
            "match_id": "count",
            "kda": "mean"
        }).round(2).reset_index()
        laning_stats.columns = ["Player", "Lane Partner", "Lane", "Avg Performance", "Win Rate %", "Games", "Avg KDA"]
        
        # Filter for at least 2 games together
        laning_stats = laning_stats[laning_stats["Games"] >= 2].sort_values("Avg Performance", ascending=False)
        
        if not laning_stats.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Performance with lane partners
                fig_lane_perf = px.bar(
                    laning_stats.head(15),
                    x="Avg Performance",
                    y="Player",
                    color="Lane Partner",
                    title="Top 15 Laning Partnerships by Performance",
                    text="Avg Performance",
                    orientation="h",
                    hover_data=["Lane", "Games", "Win Rate %"]
                )
                fig_lane_perf.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                st.plotly_chart(fig_lane_perf, use_container_width=True)
            
            with col2:
                # Win rate with lane partners
                fig_lane_wr = px.bar(
                    laning_stats.head(15),
                    x="Win Rate %",
                    y="Player",
                    color="Lane Partner",
                    title="Top 15 Laning Partnerships by Win Rate",
                    text="Win Rate %",
                    orientation="h",
                    hover_data=["Lane", "Games", "Avg Performance"]
                )
                fig_lane_wr.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                st.plotly_chart(fig_lane_wr, use_container_width=True)
            
            # Best laning partnerships table
            st.subheader("🏆 Best Laning Partnerships")
            
            best_partnerships = laning_stats.nlargest(10, "Avg Performance")
            
            st.dataframe(
                best_partnerships,
                use_container_width=True,
                hide_index=True
            )
            
            # Lane preference analysis
            st.subheader("🗺️ Lane Performance by Player")
            
            lane_perf = df[df["lane"] != "Unknown"].groupby(["player_name", "lane"]).agg({
                "performance_score": "mean",
                "is_victory": lambda x: (x.sum() / len(x) * 100),
                "match_id": "count"
            }).round(2).reset_index()
            lane_perf.columns = ["Player", "Lane", "Avg Performance", "Win Rate %", "Games"]
            lane_perf = lane_perf[lane_perf["Games"] >= 3]
            
            if not lane_perf.empty:
                fig_lane_pref = px.bar(
                    lane_perf,
                    x="Lane",
                    y="Avg Performance",
                    color="Player",
                    barmode="group",
                    title="Performance by Lane (min 3 games)",
                    text="Avg Performance"
                )
                fig_lane_pref.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig_lane_pref.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_lane_pref, use_container_width=True)
        else:
            st.info("Not enough games with lane partners for analysis (minimum 2 games required)")
    else:
        st.info("No laning partner data available")
    
    st.markdown("---")
    
    # Detailed statistics table
    st.header("📋 Detailed Statistics")
    
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
    
    detailed_stats.columns = ["Matches", "Wins", "Win Rate %", "Avg Perf", "Min Perf", "Max Perf", 
                              "Avg KDA", "Avg Kills", "Avg Deaths", "Avg Assists", "Party Games"]
    detailed_stats = detailed_stats.sort_values("Avg Perf", ascending=False)
    
    st.dataframe(detailed_stats, use_container_width=True)
    
    # Recent matches
    st.header("🕐 Recent Matches")
    
    recent_matches = df.sort_values("match_date", ascending=False).head(20)[
        ["match_date", "player_name", "hero", "role", "lane", "is_victory", "performance_score", 
         "kills", "deaths", "assists", "kda", "is_party", "lane_partner"]
    ].copy()
    
    recent_matches["match_date"] = recent_matches["match_date"].dt.strftime("%Y-%m-%d %H:%M")
    recent_matches["is_victory"] = recent_matches["is_victory"].map({True: "✅ Win", False: "❌ Loss"})
    recent_matches["is_party"] = recent_matches["is_party"].map({True: "👥", False: "🧍"})
    
    recent_matches.columns = ["Date", "Player", "Hero", "Role", "Lane", "Result", "Performance", 
                             "K", "D", "A", "KDA", "Party", "Lane Partner"]
    
    st.dataframe(
        recent_matches,
        use_container_width=True,
        hide_index=True
    )
    
    # Download data
    st.header("💾 Export Data")
    
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name=f"brohirim_stats_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )


if __name__ == "__main__":
    main()