"""
pages/1_📊_Ops_Dashboard.py

Streamlit multipage app — auto-discovered as a sidebar page alongside
app.py's review dashboard. Read-only: volume, latency, token cost, and
IMAP/SMTP health, plus an audit trail of auto-sent replies (which bypass
the human review queue in app.py entirely).
"""

import os
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from agent.db import (
    get_today_stats, get_health, get_daily_volume,
    get_latency_summary, get_latency_percentiles, get_cost_summary,
    get_recent_auto_sent, load_pending_drafts, count_recent_auto_sends,
    get_data_date_range,
)

# Mirrors agent/email_handler.py's AUTO_SEND_MAX_PER_HOUR — read directly
# rather than importing email_handler here, which would drag in the heavy
# classifier/rag_chain import chain just to show one number.
AUTO_SEND_MAX_PER_HOUR = int(os.getenv("AUTO_SEND_MAX_PER_HOUR", "20"))

st.set_page_config(page_title="Ops Dashboard — Dental CS Agent", layout="wide")
st.title("Ops Dashboard")

# ── KPI row ──────────────────────────────────────────────────────────────────

today = get_today_stats()
pending_count = len(load_pending_drafts())

escalation_rate = (today["escalated"] / today["total"] * 100) if today["total"] else 0.0
auto_send_rate = (today["auto_sent"] / today["total"] * 100) if today["total"] else 0.0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Emails today", today["total"])
k2.metric("Escalation rate", f"{escalation_rate:.0f}%")
k3.metric("Auto-send rate", f"{auto_send_rate:.0f}%")
k4.metric("Avg latency", f"{today['avg_total_elapsed']:.1f}s")
k5.metric("Est. cost today", f"${today['cost_usd']:.4f}")

st.divider()

# ── System health ───────────────────────────────────────────────────────────

st.subheader("System health")
health = get_health()

hc1, hc2, hc3, hc4, hc5 = st.columns(5)

if health["last_poll_ts"]:
    last_poll = datetime.fromisoformat(health["last_poll_ts"])
    age_s = (datetime.now(timezone.utc) - last_poll).total_seconds()
    hc1.metric("Last poll", f"{age_s:.0f}s ago")
else:
    hc1.metric("Last poll", "never")

hc2.metric("IMAP status", health["imap_status"])
hc3.metric("SMTP status", health["smtp_status"])
hc4.metric("Consecutive errors", health["consecutive_errors"])
hc5.metric("DeepSeek fallback today", today["fallback_count"])

if health["last_error"]:
    st.warning(f"Last error: {health['last_error']}")

st.markdown("**Auto-send safety**")
st.caption("Shadow mode is always on — 'would qualify' is computed for every "
           "email regardless of whether AUTO_SEND_ENABLED is set.")

recent_auto_sends = count_recent_auto_sends(60)
breaker_tripped = recent_auto_sends >= AUTO_SEND_MAX_PER_HOUR

sc1, sc2 = st.columns(2)
sc1.metric("Would qualify today (shadow mode)", today["would_auto_send_count"])
sc2.metric(
    "Circuit breaker (last hour)",
    f"{recent_auto_sends} / {AUTO_SEND_MAX_PER_HOUR}",
    delta="TRIPPED" if breaker_tripped else None,
    delta_color="inverse",
)

st.divider()

# ── Historical trends date range ────────────────────────────────────────────
# Applies to Volume/Latency/Cost below only. KPI row and System Health above
# are always "right now" snapshots — a date range wouldn't mean anything there.

data_min, data_max = get_data_date_range()
if data_min and data_max:
    default_range = (date.fromisoformat(data_min), date.fromisoformat(data_max))
else:
    today_date = date.today()
    default_range = (today_date - timedelta(days=7), today_date)

st.subheader("Historical trends")
picked_range = st.date_input("Date range", value=default_range)
if isinstance(picked_range, tuple) and len(picked_range) == 2:
    range_start, range_end = picked_range
else:
    # Streamlit returns a single date until both ends of the range are picked
    range_start, range_end = default_range
start_str, end_str = range_start.isoformat(), range_end.isoformat()

st.divider()

# ── Volume over time ────────────────────────────────────────────────────────

st.subheader("Volume over time")
volume = get_daily_volume(start_str, end_str)

if not volume:
    st.info("No processed emails yet — this fills in once the agent has run.")
else:
    df_vol = pd.DataFrame(volume)
    chart = (
        alt.Chart(df_vol)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("count:Q", title="Emails"),
            color=alt.Color("status:N", title="Status"),
            tooltip=["date", "status", "count"],
        )
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True)

st.divider()

# ── Latency ──────────────────────────────────────────────────────────────────

st.subheader("Latency")
latency = get_latency_summary(start_str, end_str)

if not latency:
    st.info("No timing data yet.")
else:
    df_lat = pd.DataFrame(latency).melt(
        id_vars="date",
        value_vars=["avg_classify", "avg_rag", "avg_total"],
        var_name="stage", value_name="seconds",
    )
    chart = (
        alt.Chart(df_lat)
        .mark_line(point=True)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("seconds:Q", title="Avg seconds"),
            color=alt.Color("stage:N", title="Stage"),
            tooltip=["date", "stage", "seconds"],
        )
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True)

st.caption("Averages above can hide tail latency — a handful of slow outliers "
           "a day won't move the average much, but shows up clearly below.")
percentiles = get_latency_percentiles(start_str, end_str)

if percentiles:
    df_pct = pd.DataFrame(percentiles).melt(
        id_vars="date",
        value_vars=["p50_total", "p95_total", "p99_total"],
        var_name="percentile", value_name="seconds",
    )
    chart = (
        alt.Chart(df_pct)
        .mark_line(point=True)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("seconds:Q", title="Total latency (s)"),
            color=alt.Color("percentile:N", title="Percentile",
                             sort=["p50_total", "p95_total", "p99_total"]),
            tooltip=["date", "percentile", "seconds"],
        )
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True)

st.divider()

# ── Cost ─────────────────────────────────────────────────────────────────────

st.subheader("Token cost")
st.caption("Estimated from gemini-2.5-flash list pricing — see agent/api_client.py. "
           "Excludes embedding calls.")
cost = get_cost_summary(start_str, end_str)

cc1, cc2 = st.columns(2)

with cc1:
    st.markdown("**Daily cost**")
    if not cost["daily"]:
        st.info("No cost data yet.")
    else:
        df_cost = pd.DataFrame(cost["daily"])
        chart = (
            alt.Chart(df_cost)
            .mark_bar()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("cost_usd:Q", title="USD"),
                tooltip=["date", "prompt_tokens", "output_tokens", "cost_usd"],
            )
            .properties(height=280)
        )
        st.altair_chart(chart, use_container_width=True)

with cc2:
    st.markdown("**Cost by intent**")
    if not cost["by_intent"]:
        st.info("No cost data yet.")
    else:
        df_intent = pd.DataFrame(cost["by_intent"])
        st.dataframe(df_intent, use_container_width=True, hide_index=True)

st.divider()

# ── Auto-sent audit trail ───────────────────────────────────────────────────

st.subheader("Recent auto-sent replies (audit)")
st.caption("These bypassed human review — see AUTO_SEND_* settings in .env.")

auto_sent = get_recent_auto_sent(limit=20)

if not auto_sent:
    st.info("No auto-sent replies yet. Auto-send is off by default "
            "(AUTO_SEND_ENABLED=false).")
else:
    for row in auto_sent:
        with st.expander(
            f"[{row['intent']}] {row['subject'][:60]} — "
            f"confidence={row['confidence']:.2f} score={row['retrieval_score']:.2f}"
        ):
            st.caption(f"From {row['from']} | {row['timestamp']}")
            st.text(row["final_reply"] or row["draft_reply"])
