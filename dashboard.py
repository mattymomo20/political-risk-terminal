import sqlite3
import pandas as pd
import streamlit as st

DB_PATH = "scores.db"

PERIL_ORDER = [
    "Expropriation & CEND",
    "Political Violence",
    "Currency Inconvertibility & Transfer Risk",
    "Sovereign Default & Non-Payment",
    "Civil Unrest (SRCC)",
]

st.set_page_config(page_title="Political Risk Terminal", layout="wide")
st.title("Political Risk Terminal")
st.caption("LLM-scored political risk across watchlist countries. Prototype — public news only.")


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM scores", conn)
    conn.close()
    df["scored_at"] = pd.to_datetime(df["scored_at"])
    return df


df = load_data()

if df.empty:
    st.warning("No scores yet. Run `uv run score_country.py` first.")
    st.stop()

# Most recent score for each country + peril
latest = df.sort_values("scored_at").groupby(["country", "peril"]).tail(1)


def colour(score):
    if pd.isna(score):
        return ""
    if score >= 7:
        return "background-color: #d73027; color: white"   # high — red
    elif score >= 5:
        return "background-color: #fc8d59"                  # elevated — orange
    elif score >= 3:
        return "background-color: #fee08b"                  # watch — yellow
    else:
        return "background-color: #1a9850; color: white"    # low — green


# --- Heatmap: countries x perils ---
st.subheader("Current risk heatmap")
matrix = latest.pivot(index="country", columns="peril", values="score").reindex(columns=PERIL_ORDER)
styled = matrix.style.map(colour).format("{:.0f}", na_rep="–")
st.dataframe(styled, use_container_width=True)

# --- Country detail ---
st.subheader("Country detail")
country = st.selectbox("Select a country", sorted(df["country"].unique()))

cdetail = latest[latest["country"] == country].set_index("peril").reindex(PERIL_ORDER)
for peril in PERIL_ORDER:
    row = cdetail.loc[peril]
    if pd.isna(row["score"]):
        continue
    st.markdown(
        f"**{peril}** — {int(row['score'])}/10 · {row['direction']} · {row['confidence']} confidence"
    )
    st.caption(row["evidence"])

# --- Score history over time ---
st.subheader(f"{country} — score history")
hist = df[df["country"] == country]
chart = hist.pivot_table(index="scored_at", columns="peril", values="score")
st.line_chart(chart)