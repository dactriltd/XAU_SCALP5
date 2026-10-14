#!/usr/bin/env python3
"""
XAU_SCALP5 Real-time Trading Dashboard
Built with Streamlit + Plotly + Material Design 3 styling
Connects directly to SQLite database (data/scalp5.db)
Auto-refreshes every 5 minutes (aligned with scalp5_verify cycle)
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

# ─────────────────────────── CONFIG ───────────────────────────
DB_PATH = Path(__file__).resolve().parent / "data" / "scalp5.db"
REFRESH_SECONDS = 300  # 5 minutes = matches scalp5_verify cycle

# Material Design 3 Color Palette
MD3_COLORS = {
    "primary": "#6750A4",
    "on_primary": "#FFFFFF",
    "primary_container": "#EADDFF",
    "on_primary_container": "#21005D",
    "secondary": "#625B71",
    "on_secondary": "#FFFFFF",
    "secondary_container": "#E8DEF8",
    "on_secondary_container": "#1D192B",
    "tertiary": "#7D5260",
    "on_tertiary": "#FFFFFF",
    "tertiary_container": "#FFD8E4",
    "on_tertiary_container": "#31111D",
    "error": "#B3261E",
    "on_error": "#FFFFFF",
    "error_container": "#F9DEDC",
    "on_error_container": "#410E0B",
    "background": "#FFFBFE",
    "on_background": "#1C1B1F",
    "surface": "#FFFBFE",
    "on_surface": "#1C1B1F",
    "surface_variant": "#E7E0EC",
    "on_surface_variant": "#49454F",
    "outline": "#79747E",
    "outline_variant": "#CAC4D0",
    "shadow": "#000000",
    "scrim": "#000000",
    "inverse_surface": "#313033",
    "inverse_on_surface": "#F4EFF4",
    "inverse_primary": "#D0BCFF",
    # Trading specific
    "bullish": "#00C853",
    "bearish": "#FF3D00",
    "neutral": "#6200EE",
    "warning": "#FFAB00",
}

# ─────────────────────────── PAGE CONFIG ───────────────────────────
st.set_page_config(
    page_title="XAU_SCALP5 Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────── CUSTOM CSS (Material Design 3) ───────────────────────────
st.markdown(f"""
<style>
    /* Material Design 3 Variables */
    :root {{
        --md-primary: {MD3_COLORS['primary']};
        --md-on-primary: {MD3_COLORS['on_primary']};
        --md-primary-container: {MD3_COLORS['primary_container']};
        --md-secondary: {MD3_COLORS['secondary']};
        --md-surface: {MD3_COLORS['surface']};
        --md-on-surface: {MD3_COLORS['on_surface']};
        --md-surface-variant: {MD3_COLORS['surface_variant']};
        --md-outline: {MD3_COLORS['outline']};
        --md-bullish: {MD3_COLORS['bullish']};
        --md-bearish: {MD3_COLORS['bearish']};
        --md-warning: {MD3_COLORS['warning']};
    }}
    
    /* Global styling */
    .stApp {{
        background-color: var(--md-surface);
        color: var(--md-on-surface);
    }}
    
    /* Card styling */
    .metric-card {{
        background: var(--md-surface);
        border: 1px solid var(--md-outline-variant);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
        transition: box-shadow 0.2s ease;
    }}
    .metric-card:hover {{
        box-shadow: 0 4px 12px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06);
    }}
    
    .metric-value {{
        font-size: 2.5rem;
        font-weight: 600;
        font-family: 'Google Sans', 'Roboto', sans-serif;
        line-height: 1.2;
    }}
    .metric-label {{
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--md-on-surface-variant);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .metric-delta {{
        font-size: 0.875rem;
        font-weight: 500;
        margin-top: 8px;
    }}
    .bullish {{ color: var(--md-bullish); }}
    .bearish {{ color: var(--md-bearish); }}
    .warning {{ color: var(--md-warning); }}
    
    /* Section headers */
    .section-header {{
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--md-on-surface);
        margin: 24px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid var(--md-primary);
        display: inline-block;
    }}
    
    /* Status badges */
    .status-badge {{
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .status-pass {{ background: #E8F5E9; color: #2E7D32; }}
    .status-warn {{ background: #FFF8E1; color: #F57F17; }}
    .status-fail {{ background: #FBE9E7; color: #C62828; }}
    
    /* Sidebar */
    .css-1d391kg {{ background: var(--md-surface-variant); }}
    
    /* Dataframe styling */
    .stDataFrame {{ border-radius: 12px; overflow: hidden; }}
    
    /* Hide streamlit branding */
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    header {{ visibility: hidden; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────── DATA LOADERS ───────────────────────────

@st.cache_data(ttl=60)  # Cache for 1 minute
def load_candles_1m(hours_back: int = 6) -> pd.DataFrame:
    """Load 1-minute candles from SQLite"""
    conn = sqlite3.connect(str(DB_PATH))
    now = int(datetime.now(timezone.utc).timestamp())
    start_ts = now - hours_back * 3600
    
    query = """
        SELECT timestamp, open, high, low, close, tick_volume
        FROM candles 
        WHERE timeframe = '1m' AND timestamp >= ? 
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, params=(start_ts,))
    conn.close()
    
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    return df

@st.cache_data(ttl=60)
def load_candles_m5(hours_back: int = 6) -> pd.DataFrame:
    """Load 5-minute candles from SQLite"""
    conn = sqlite3.connect(str(DB_PATH))
    now = int(datetime.now(timezone.utc).timestamp())
    start_ts = now - hours_back * 3600
    
    query = """
        SELECT timestamp, open, high, low, close, tick_volume
        FROM candles 
        WHERE timeframe = 'M5' AND timestamp >= ? 
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, params=(start_ts,))
    conn.close()
    
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    return df

@st.cache_data(ttl=60)
def load_entries_today() -> pd.DataFrame:
    """Load today's entry logs"""
    conn = sqlite3.connect(str(DB_PATH))
    now = int(datetime.now(timezone.utc).timestamp())
    day_start = now - (now % 86400)
    
    query = """
        SELECT ts, pos_id, kind, entry, tp, drift5m, anchor, touch
        FROM entry_log WHERE ts >= ? ORDER BY ts
    """
    df = pd.read_sql_query(query, conn, params=(day_start,))
    conn.close()
    
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['ts'], unit='s', utc=True)
        df['time_str'] = df['datetime'].dt.strftime('%H:%M')
        df['direction'] = df['kind'].map({'ENTER_LONG': 'LONG', 'ENTER_SHORT': 'SHORT'})
        df['color'] = df['direction'].map({'LONG': MD3_COLORS['bullish'], 'SHORT': MD3_COLORS['bearish']})
    return df

@st.cache_data(ttl=60)
def load_exits_today() -> pd.DataFrame:
    """Load today's exit logs"""
    conn = sqlite3.connect(str(DB_PATH))
    now = int(datetime.now(timezone.utc).timestamp())
    day_start = now - (now % 86400)
    
    query = """
        SELECT ts, pos_id, reason, exit_px, pnl
        FROM exit_log WHERE ts >= ? ORDER BY ts
    """
    df = pd.read_sql_query(query, conn, params=(day_start,))
    conn.close()
    
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['ts'], unit='s', utc=True)
        df['time_str'] = df['datetime'].dt.strftime('%H:%M')
        df['pnl'] = df['pnl'].fillna(0)
        df['result'] = df['pnl'].apply(lambda x: 'WIN' if x > 0 else ('LOSS' if x < 0 else 'FLAT'))
        df['color'] = df['result'].map({'WIN': MD3_COLORS['bullish'], 'LOSS': MD3_COLORS['bearish'], 'FLAT': MD3_COLORS['neutral']})
    return df

@st.cache_data(ttl=60)
def load_status_json() -> dict:
    """Load current bot status from JSON"""
    status_path = Path(__file__).resolve().parent / "logs" / "scalp5.status.json"
    if status_path.exists():
        with open(status_path) as f:
            return json.load(f)
    return {}

@st.cache_data(ttl=60)
def load_verify_report() -> dict:
    """Load verification report"""
    report_path = Path(__file__).resolve().parent / "logs" / "scalp5_verify_report.json"
    if report_path.exists():
        with open(report_path) as f:
            return json.load(f)
    return {}

@st.cache_data(ttl=60)
def load_price_chart_report() -> dict:
    """Load price chart verification report"""
    report_path = Path(__file__).resolve().parent / "logs" / "price_chart_report.json"
    if report_path.exists():
        with open(report_path) as f:
            return json.load(f)
    return {}

# ─────────────────────────── CHART BUILDERS ───────────────────────────

def build_candlestick_chart(candles_m5: pd.DataFrame, entries: pd.DataFrame, exits: pd.DataFrame) -> go.Figure:
    """Build main candlestick chart with entries/exits"""
    if candles_m5.empty:
        return go.Figure().add_annotation(text="No candle data available", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.75, 0.25],
        subplot_titles=("Price (5-min candles)", "Volume")
    )
    
    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=candles_m5['datetime'],
        open=candles_m5['open'],
        high=candles_m5['high'],
        low=candles_m5['low'],
        close=candles_m5['close'],
        name="Price",
        increasing_line_color=MD3_COLORS['bullish'],
        decreasing_line_color=MD3_COLORS['bearish'],
        increasing_fillcolor=MD3_COLORS['bullish'],
        decreasing_fillcolor=MD3_COLORS['bearish'],
    ), row=1, col=1)
    
    # Entries
    if not entries.empty:
        longs = entries[entries['direction'] == 'LONG']
        shorts = entries[entries['direction'] == 'SHORT']
        
        if not longs.empty:
            fig.add_trace(go.Scatter(
                x=longs['datetime'],
                y=longs['entry'],
                mode='markers',
                marker=dict(symbol='triangle-up', size=12, color=MD3_COLORS['bullish'], line=dict(width=1, color='white')),
                name='LONG Entry',
                hovertemplate='LONG<br>Time: %{x}<br>Price: %{y:.2f}<br>Pos: %{customdata}<extra></extra>',
                customdata=longs['pos_id']
            ), row=1, col=1)
        
        if not shorts.empty:
            fig.add_trace(go.Scatter(
                x=shorts['datetime'],
                y=shorts['entry'],
                mode='markers',
                marker=dict(symbol='triangle-down', size=12, color=MD3_COLORS['bearish'], line=dict(width=1, color='white')),
                name='SHORT Entry',
                hovertemplate='SHORT<br>Time: %{x}<br>Price: %{y:.2f}<br>Pos: %{customdata}<extra></extra>',
                customdata=shorts['pos_id']
            ), row=1, col=1)
    
    # Exits (TP/TIME)
    if not exits.empty:
        tp_exits = exits[exits['reason'] == 'TP']
        time_exits = exits[exits['reason'] == 'TIME']
        other_exits = exits[~exits['reason'].isin(['TP', 'TIME'])]
        
        for subset, name, symbol, color in [
            (tp_exits, 'TP Exit', 'circle', MD3_COLORS['bullish']),
            (time_exits, 'TIME Exit', 'x', MD3_COLORS['warning']),
            (other_exits, 'Other Exit', 'diamond', MD3_COLORS['neutral'])
        ]:
            if not subset.empty:
                fig.add_trace(go.Scatter(
                    x=subset['datetime'],
                    y=subset['exit_px'],
                    mode='markers',
                    marker=dict(symbol=symbol, size=10, color=color, line=dict(width=1, color='white')),
                    name=name,
                    hovertemplate=f'{name}<br>Time: %{{x}}<br>Price: %{{y:.2f}}<br>PnL: %{{customdata[0]:+.2f}}<br>Reason: %{{customdata[1]}}<extra></extra>',
                    customdata=list(zip(subset['pnl'], subset['reason']))
                ), row=1, col=1)
    
    # Volume bars
    colors = ['rgba(0,200,83,0.5)' if c >= o else 'rgba(255,61,0,0.5)' 
              for c, o in zip(candles_m5['close'], candles_m5['open'])]
    fig.add_trace(go.Bar(
        x=candles_m5['datetime'],
        y=candles_m5['tick_volume'],
        name='Volume',
        marker_color=colors,
        showlegend=False
    ), row=2, col=1)
    
    # Layout
    fig.update_layout(
        template='plotly_white',
        paper_bgcolor=MD3_COLORS['surface'],
        plot_bgcolor=MD3_COLORS['surface'],
        font=dict(family="'Google Sans', 'Roboto', sans-serif", color=MD3_COLORS['on_surface']),
        xaxis_rangeslider_visible=False,
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor='rgba(255,251,254,0.9)',
            bordercolor=MD3_COLORS['outline_variant'],
            borderwidth=1
        ),
        margin=dict(l=40, r=40, t=40, b=20),
        height=600,
        xaxis=dict(
            gridcolor=MD3_COLORS['outline_variant'],
            showspikes=True,
            spikecolor=MD3_COLORS['outline'],
            spikethickness=1
        ),
        yaxis=dict(
            gridcolor=MD3_COLORS['outline_variant'],
            side='right',
            showspikes=True,
            spikecolor=MD3_COLORS['outline'],
            spikethickness=1
        )
    )
    
    fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    
    return fig


def build_pnl_chart(exits: pd.DataFrame) -> go.Figure:
    """Build cumulative PnL chart"""
    if exits.empty:
        return go.Figure().add_annotation(text="No exit data", xref="paper", yref="paper", x=0.5, y=0.5)
    
    df = exits.copy()
    df = df.sort_values('ts')
    df['cumulative_pnl'] = df['pnl'].cumsum()
    
    fig = go.Figure()
    
    # Cumulative PnL line
    fig.add_trace(go.Scatter(
        x=df['datetime'],
        y=df['cumulative_pnl'],
        mode='lines',
        name='Cumulative PnL',
        line=dict(color=MD3_COLORS['primary'], width=3),
        fill='tozeroy',
        fillcolor=f'rgba(103, 80, 164, 0.1)',
        hovertemplate='Time: %{x}<br>Cumulative PnL: %{y:.2f}$<extra></extra>'
    ))
    
    # Individual trade markers
    colors = [MD3_COLORS['bullish'] if p > 0 else MD3_COLORS['bearish'] for p in df['pnl']]
    fig.add_trace(go.Scatter(
        x=df['datetime'],
        y=df['cumulative_pnl'],
        mode='markers',
        marker=dict(size=8, color=colors, line=dict(width=1, color='white')),
        name='Trades',
        hovertemplate='Time: %{x}<br>Cum PnL: %{y:.2f}$<br>Trade PnL: %{customdata:+.2f}$<extra></extra>',
        customdata=df['pnl'],
        showlegend=False
    ))
    
    fig.update_layout(
        template='plotly_white',
        paper_bgcolor=MD3_COLORS['surface'],
        plot_bgcolor=MD3_COLORS['surface'],
        font=dict(family="'Google Sans', 'Roboto', sans-serif", color=MD3_COLORS['on_surface']),
        height=300,
        margin=dict(l=40, r=40, t=30, b=20),
        yaxis=dict(title="Cumulative PnL ($)", gridcolor=MD3_COLORS['outline_variant']),
        xaxis=dict(gridcolor=MD3_COLORS['outline_variant']),
        hovermode='x unified'
    )
    
    return fig


def build_distribution_chart(exits: pd.DataFrame) -> go.Figure:
    """Build exit reason distribution"""
    if exits.empty:
        return go.Figure().add_annotation(text="No exit data", xref="paper", yref="paper", x=0.5, y=0.5)
    
    reason_counts = exits['reason'].value_counts()
    reason_pnl = exits.groupby('reason')['pnl'].sum()
    
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Exit Count by Reason", "PnL by Reason"),
        specs=[[{"type": "pie"}, {"type": "bar"}]]
    )
    
    # Pie chart - count
    fig.add_trace(go.Pie(
        labels=reason_counts.index,
        values=reason_counts.values,
        hole=0.5,
        marker=dict(colors=px.colors.qualitative.Set3),
        textinfo='label+percent',
        textfont_size=11,
        hovertemplate='%{label}: %{value} (%{percent})<extra></extra>'
    ), row=1, col=1)
    
    # Bar chart - PnL
    colors = [MD3_COLORS['bullish'] if v > 0 else MD3_COLORS['bearish'] for v in reason_pnl.values]
    fig.add_trace(go.Bar(
        x=reason_pnl.index,
        y=reason_pnl.values,
        marker_color=colors,
        name='PnL',
        hovertemplate='%{x}: %{y:.2f}$<extra></extra>',
        showlegend=False
    ), row=1, col=2)
    
    fig.update_layout(
        template='plotly_white',
        paper_bgcolor=MD3_COLORS['surface'],
        plot_bgcolor=MD3_COLORS['surface'],
        font=dict(family="'Google Sans', 'Roboto', sans-serif", color=MD3_COLORS['on_surface']),
        height=300,
        margin=dict(l=40, r=40, t=50, b=20),
        showlegend=True
    )
    
    return fig


def build_sr_levels_chart(price_chart_report: dict, current_price: float) -> go.Figure:
    """Build support/resistance levels visualization"""
    sr_levels = price_chart_report.get('sr_levels', [])
    if not sr_levels:
        return go.Figure().add_annotation(text="No S/R data", xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    
    for level in sr_levels:
        color = MD3_COLORS['bearish'] if level['type'] == 'RESISTANCE' else MD3_COLORS['bullish']
        width = 3 if level['strong'] else 1
        dash = 'solid' if level['strong'] else 'dash'
        
        fig.add_shape(
            type="line",
            x0=0, x1=1, xref="paper",
            y0=level['price'], y1=level['price'], yref="y",
            line=dict(color=color, width=width, dash=dash)
        )
        
        # Label
        fig.add_annotation(
            x=1.02, xref="paper",
            y=level['price'], yref="y",
            text=f"{level['type']} {level['price']:.2f} ({level['touches']}T)",
            showarrow=False,
            font=dict(size=10, color=color),
            xanchor='left',
            bgcolor=MD3_COLORS['surface'],
            bordercolor=color,
            borderwidth=1
        )
    
    # Current price line
    fig.add_shape(
        type="line",
        x0=0, x1=1, xref="paper",
        y0=current_price, y1=current_price, yref="y",
        line=dict(color=MD3_COLORS['primary'], width=2, dash='dot')
    )
    fig.add_annotation(
        x=1.02, xref="paper",
        y=current_price, yref="y",
        text=f"CURRENT {current_price:.2f}",
        showarrow=False,
        font=dict(size=10, color=MD3_COLORS['primary'], weight='bold'),
        xanchor='left',
        bgcolor=MD3_COLORS['primary_container'],
        bordercolor=MD3_COLORS['primary'],
        borderwidth=1
    )
    
    # Price range
    price_range = price_chart_report.get('price_range', {})
    y_min = price_range.get('low', current_price - 10)
    y_max = price_range.get('high', current_price + 10)
    
    fig.update_layout(
        template='plotly_white',
        paper_bgcolor=MD3_COLORS['surface'],
        plot_bgcolor=MD3_COLORS['surface'],
        font=dict(family="'Google Sans', 'Roboto', sans-serif", color=MD3_COLORS['on_surface']),
        height=400,
        margin=dict(l=40, r=180, t=30, b=20),
        yaxis=dict(
            title="Price (USD)",
            range=[y_min - 1, y_max + 1],
            gridcolor=MD3_COLORS['outline_variant']
        ),
        xaxis=dict(visible=False),
        showlegend=False
    )
    
    return fig


# ─────────────────────────── METRIC CARDS ───────────────────────────

def render_metric_card(label: str, value: str, delta: str = None, delta_color: str = "normal", icon: str = "") -> str:
    """Render a Material Design 3 metric card as HTML"""
    delta_html = ""
    if delta:
        delta_class = "bullish" if "bullish" in delta_color or "+" in delta else ("bearish" if "bearish" in delta_color or "-" in delta else "warning")
        delta_html = f'<div class="metric-delta {delta_class}">{delta}</div>'
    
    return f"""
    <div class="metric-card">
        <div class="metric-label">{icon} {label}</div>
        <div class="metric-value">{value}</div>
        {delta_html}
    </div>
    """

# ─────────────────────────── MAIN DASHBOARD ───────────────────────────

def main():
    # Sidebar
    with st.sidebar:
        st.markdown("### 🎛️ XAU_SCALP5 Dashboard")
        st.markdown("---")
        
        # Time range selector
        hours_back = st.select_slider(
            "Time Range",
            options=[1, 2, 4, 6, 12, 24],
            value=4,
            format_func=lambda x: f"{x}h"
        )
        
        st.markdown("---")
        
        # Bot status
        status = load_status_json()
        if status:
            st.markdown("**🤖 Bot Status**")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Mode", status.get('mode', 'N/A'))
                st.metric("Drift5m", f"{status.get('drift5m', 0):+.2f}")
            with col2:
                st.metric("Open Pos", len(status.get('open', [])))
                st.metric("Day PnL", f"{status.get('day_loss', 0):+.2f}")
            
            # Last update
            ts = status.get('ts', 0)
            if ts:
                last_update = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M:%S UTC')
                st.caption(f"Last update: {last_update}")
        
        st.markdown("---")
        
        # Verification status
        verify = load_verify_report()
        if verify:
            st.markdown("**🔍 7-Block Verify**")
            overall = verify.get('overall', 'UNKNOWN')
            status_class = {"PASS": "status-pass", "WARN": "status-warn", "FAIL": "status-fail"}.get(overall, "")
            st.markdown(f'<span class="status-badge {status_class}">{overall}</span>', unsafe_allow_html=True)
            
            for check in verify.get('checks', []):
                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(check['status'], "❓")
                st.caption(f"{icon} {check['block']}: {check['observed'][:50]}...")
        
        st.markdown("---")
        
        # Price chart verify status
        chart_report = load_price_chart_report()
        if chart_report:
            st.markdown("**📊 Price Chart Verify (Blocks 8-10)**")
            for block_name, block in chart_report.get('blocks', {}).items():
                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(block['status'], "❓")
                st.caption(f"{icon} {block_name}: {block['status']}")
        
        st.markdown("---")
        st.caption(f"Auto-refresh: {REFRESH_SECONDS}s | {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        # Manual refresh button
        if st.button("🔄 Refresh Now", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    # Main content
    st.markdown("# 📈 XAU_SCALP5 Real-time Trading Dashboard")
    st.caption(f"Data from SQLite • 5-min candles • Auto-refresh every {REFRESH_SECONDS//60} min • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Load data
    candles_m5 = load_candles_m5(hours_back)
    entries = load_entries_today()
    exits = load_exits_today()
    status = load_status_json()
    
    # ─── TOP METRICS ROW ───
    st.markdown("## 📊 Session Overview")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    # Calculate metrics
    total_entries = len(entries)
    total_exits = len(exits)
    total_pnl = exits['pnl'].sum() if not exits.empty else 0
    wins = len(exits[exits['pnl'] > 0]) if not exits.empty else 0
    losses = len(exits[exits['pnl'] < 0]) if not exits.empty else 0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    open_positions = len(status.get('open', []))
    day_loss = status.get('day_loss', 0)
    current_price = status.get('px', candles_m5['close'].iloc[-1] if not candles_m5.empty else 0)
    drift = status.get('drift5m', 0)
    
    with col1:
        st.markdown(render_metric_card("Current Price", f"${current_price:,.2f}", 
            delta=f"Drift: {drift:+.2f}", delta_color="normal", icon="💰"), unsafe_allow_html=True)
    
    with col2:
        pnl_color = "bullish" if total_pnl >= 0 else "bearish"
        st.markdown(render_metric_card("Session PnL", f"${total_pnl:+.2f}", 
            delta=f"{win_rate:.1f}% WR", delta_color=pnl_color, icon="💵"), unsafe_allow_html=True)
    
    with col3:
        st.markdown(render_metric_card("Open Positions", f"{open_positions} / 4", 
            delta=f"Day Loss: ${day_loss:+.2f}", delta_color="bearish" if day_loss < -20 else "normal", icon="📍"), unsafe_allow_html=True)
    
    with col4:
        st.markdown(render_metric_card("Trades Today", f"{total_exits} closed / {total_entries} opened", 
            delta=f"{wins}W / {losses}L", delta_color="bullish" if wins >= losses else "bearish", icon="📝"), unsafe_allow_html=True)
    
    with col5:
        avg_pnl = exits['pnl'].mean() if not exits.empty else 0
        st.markdown(render_metric_card("Avg Trade", f"${avg_pnl:+.2f}", 
            delta=f"Best: ${exits['pnl'].max():.2f}" if not exits.empty else "", delta_color="normal", icon="📈"), unsafe_allow_html=True)
    
    with col6:
        # Status indicator
        verify = load_verify_report()
        overall = verify.get('overall', 'N/A')
        status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(overall, "❓")
        st.markdown(render_metric_card("System Health", f"{status_icon} {overall}", 
            delta=f"F={verify.get('n_fail', 0)} W={verify.get('n_warn', 0)}", delta_color="normal", icon="🏥"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ─── MAIN CHART ───
    st.markdown('<div class="section-header">📈 Price Action (5-min Candles)</div>', unsafe_allow_html=True)
    
    chart = build_candlestick_chart(candles_m5, entries, exits)
    st.plotly_chart(chart, use_container_width=True, config={'displayModeBar': False})
    
    # ─── SECONDARY ROW ───
    col_left, col_right = st.columns([2, 1])
    
    with col_left:
        st.markdown('<div class="section-header">💰 Cumulative PnL</div>', unsafe_allow_html=True)
        pnl_chart = build_pnl_chart(exits)
        st.plotly_chart(pnl_chart, use_container_width=True, config={'displayModeBar': False})
    
    with col_right:
        st.markdown('<div class="section-header">🎯 Exit Distribution</div>', unsafe_allow_html=True)
        dist_chart = build_distribution_chart(exits)
        st.plotly_chart(dist_chart, use_container_width=True, config={'displayModeBar': False})
    
    # ─── S/R LEVELS ───
    chart_report = load_price_chart_report()
    if chart_report and chart_report.get('sr_levels'):
        st.markdown('<div class="section-header">🎯 Support / Resistance Levels</div>', unsafe_allow_html=True)
        sr_chart = build_sr_levels_chart(chart_report, current_price)
        st.plotly_chart(sr_chart, use_container_width=True, config={'displayModeBar': False})
    
    # ─── DATA TABLES ───
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Entries", "📋 Exits", "🕯️ Candles (M5)", "🔍 Verification Details"])
    
    with tab1:
        if not entries.empty:
            display_cols = ['time_str', 'direction', 'entry', 'tp', 'drift5m', 'anchor', 'touch', 'pos_id']
            df_display = entries[display_cols].copy()
            df_display.columns = ['Time', 'Dir', 'Entry', 'TP', 'Drift', 'Anchor', 'Touch', 'Pos ID']
            st.dataframe(df_display, use_container_width=True, hide_index=True,
                column_config={
                    "Entry": st.column_config.NumberColumn(format="$%.2f"),
                    "TP": st.column_config.NumberColumn(format="$%.2f"),
                    "Drift": st.column_config.NumberColumn(format="%.2f"),
                    "Touch": st.column_config.NumberColumn(format="%.2f"),
                })
        else:
            st.info("No entries today")
    
    with tab2:
        if not exits.empty:
            display_cols = ['time_str', 'reason', 'exit_px', 'pnl', 'result', 'pos_id']
            df_display = exits[display_cols].copy()
            df_display.columns = ['Time', 'Reason', 'Exit', 'PnL', 'Result', 'Pos ID']
            st.dataframe(df_display, use_container_width=True, hide_index=True,
                column_config={
                    "Exit": st.column_config.NumberColumn(format="$%.2f"),
                    "PnL": st.column_config.NumberColumn(format="$%+.2f"),
                })
        else:
            st.info("No exits today")
    
    with tab3:
        if not candles_m5.empty:
            display_cols = ['time_str', 'open', 'high', 'low', 'close', 'tick_volume']
            df_display = candles_m5[display_cols].copy()
            df_display.columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Vol']
            st.dataframe(df_display, use_container_width=True, hide_index=True,
                column_config={
                    "Open": st.column_config.NumberColumn(format="$%.2f"),
                    "High": st.column_config.NumberColumn(format="$%.2f"),
                    "Low": st.column_config.NumberColumn(format="$%.2f"),
                    "Close": st.column_config.NumberColumn(format="$%.2f"),
                })
        else:
            st.info("No M5 candle data")
    
    with tab4:
        verify = load_verify_report()
        if verify:
            st.json(verify)
        else:
            st.info("No verification report available")
        
        if chart_report:
            st.markdown("### Price Chart Verification (Blocks 8-10)")
            st.json(chart_report.get('blocks', {}))
    
    # ─── AUTO REFRESH ───
    # Use st.fragment for partial refresh every 5 minutes
    @st.fragment(run_every=REFRESH_SECONDS)
    def auto_refresh():
        st.empty()  # This triggers a rerun of the fragment
    
    auto_refresh()

if __name__ == "__main__":
    main()