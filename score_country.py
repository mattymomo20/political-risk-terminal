import os
import json
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

# --- Config: change this to score a different country ---
COUNTRY = "Nigeria"
# --------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"
RUBRIC_VERSION = "v1"
DB_PATH = "scores.db"

newsapi_key = os.environ["NEWSAPI_KEY"]
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PERILS = [
    "Expropriation & CEND",
    "Political Violence",
    "Currency Inconvertibility & Transfer Risk",
    "Sovereign Default & Non-Payment",
    "Civil Unrest (SRCC)",
]


def get_news(country):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": country,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 20,
        "apiKey": newsapi_key,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    articles = response.json().get("articles", [])
    headlines = []
    for a in articles:
        title = a.get("title") or ""
        desc = a.get("description") or ""
        headlines.append(f"- {title} | {desc}")
    return headlines


def score_country(country, headlines, rubric):
    headlines_text = "\n".join(headlines)
    peril_list = "\n".join(f"- {p}" for p in PERILS)

    prompt = f"""You are a political risk analyst scoring a country for an insurance underwriting desk.

Here is the scoring rubric you MUST follow:
<rubric>
{rubric}
</rubric>

Here are recent news headlines about {country}:
<headlines>
{headlines_text}
</headlines>

Score {country} on EACH of these five perils:
{peril_list}

Respond with ONLY a JSON object (no markdown, no commentary) in exactly this shape:
{{
  "country": "{country}",
  "perils": [
    {{
      "peril": "<exact peril name from the list>",
      "score": <integer 1-10>,
      "direction": "escalating" | "stable" | "easing",
      "confidence": "high" | "medium" | "low",
      "evidence": "<one sentence citing the headline(s) behind this score, or 'No relevant news' if none>"
    }}
  ]
}}
Include all five perils. Base every score on the headlines and rubric only."""

    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "", 1).strip()
    return json.loads(text)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scored_at TEXT,
            country TEXT,
            peril TEXT,
            score INTEGER,
            direction TEXT,
            confidence TEXT,
            evidence TEXT,
            model TEXT,
            rubric_version TEXT
        )
    """)
    conn.commit()
    return conn


def store_scores(conn, result):
    scored_at = datetime.now(timezone.utc).isoformat()
    for p in result["perils"]:
        conn.execute(
            """INSERT INTO scores
               (scored_at, country, peril, score, direction, confidence, evidence, model, rubric_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scored_at, result["country"], p["peril"], p["score"],
             p["direction"], p["confidence"], p["evidence"], MODEL, RUBRIC_VERSION),
        )
    conn.commit()


def main():
    with open("peril_rubric.md") as f:
        rubric = f.read()

    print(f"Fetching news for {COUNTRY}...")
    headlines = get_news(COUNTRY)
    print(f"Found {len(headlines)} headlines.\n")

    print("Scoring with Claude...\n")
    result = score_country(COUNTRY, headlines, rubric)

    print(f"=== Political Risk Scores: {result['country']} ===\n")
    for p in result["perils"]:
        print(f"{p['peril']}")
        print(f"  Score: {p['score']}/10   Direction: {p['direction']}   Confidence: {p['confidence']}")
        print(f"  Evidence: {p['evidence']}\n")

    conn = init_db()
    store_scores(conn, result)
    total = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    conn.close()
    print(f"Saved to {DB_PATH}. Total rows in database: {total}")


def main_guard():
    main()


if __name__ == "__main__":
    main_guard()