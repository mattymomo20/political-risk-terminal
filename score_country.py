import os
import json
import time
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from anthropic import Anthropic
from config import WATCHLIST

load_dotenv()

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

# Risk-relevant terms, so we pull political-risk news rather than general noise.
RISK_TERMS = (
    "(protest OR unrest OR coup OR riot OR strike OR sanctions OR default OR "
    "currency OR devaluation OR inflation OR IMF OR expropriation OR "
    "nationalisation OR nationalization OR violence OR insurgency OR militant OR "
    "election OR corruption OR debt OR crisis)"
)


def dedup(headlines):
    """Drop duplicate headlines (sources repeat the same story)."""
    seen = set()
    unique = []
    for h in headlines:
        key = h.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


def get_news_gdelt(country):
    country_q = f'"{country}"' if " " in country else country
    query = f"{country_q} {RISK_TERMS}"
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": 75,
        "timespan": "1w",
        "format": "json",
        "sort": "datedesc",
    }
    headers = {"User-Agent": "Mozilla/5.0 (political-risk-terminal)"}
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=30, headers=headers)
            if response.status_code == 429:  # rate-limited: wait and retry
                time.sleep(6)
                continue
            response.raise_for_status()
            articles = response.json().get("articles", [])
            return [a.get("title", "") for a in articles if a.get("title")]
        except Exception:
            time.sleep(6)
    return []


def get_news_newsapi(country):
    country_q = f'"{country}"' if " " in country else country
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f"{country_q} AND {RISK_TERMS}",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 30,
        "apiKey": newsapi_key,
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        articles = response.json().get("articles", [])
    except Exception:
        return []
    headlines = []
    for a in articles:
        title = a.get("title") or ""
        desc = a.get("description") or ""
        headlines.append(f"{title} | {desc}")
    return headlines


def get_news(country):
    """GDELT is primary; fall back to NewsAPI if GDELT comes back thin."""
    headlines = dedup(get_news_gdelt(country))
    source = "GDELT"
    if len(headlines) < 3:
        headlines = dedup(get_news_newsapi(country))
        source = "NewsAPI (fallback)"
    return headlines, source


def score_country(country, headlines, rubric):
    headlines_text = "\n".join(f"- {h}" for h in headlines)
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

    conn = init_db()
    for country in WATCHLIST:
        try:
            print(f"\n=== {country} ===")
            headlines, source = get_news(country)
            print(f"  {len(headlines)} headlines via {source}, scoring...")
            result = score_country(country, headlines, rubric)
            store_scores(conn, result)
            for p in result["perils"]:
                print(f"  {p['peril']}: {p['score']}/10 ({p['direction']}, {p['confidence']})")
        except Exception as e:
            print(f"  ERROR scoring {country}: {e}")
        time.sleep(6)  # GDELT allows only 1 request per 5 seconds

    total = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    conn.close()
    print(f"\nDone. Total rows in database: {total}")


if __name__ == "__main__":
    main()