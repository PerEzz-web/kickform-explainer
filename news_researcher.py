import json
import re
from typing import Any, Dict, List
import datetime as dt

from openai import OpenAI


TRUSTED_NEWS_DOMAINS = [
    # Broad football / sports news
    "bbc.com",
    "skysports.com",
    "reuters.com",
    "apnews.com",
    "theguardian.com",
    "espn.com",

    # Competition / official sources
    "premierleague.com",
    "uefa.com",
    "laliga.com",
    "legaseriea.it",
    "bundesliga.com",
    "ligue1.com",
    "ligaportugal.pt",

    # Portuguese football sources
    "abola.pt",
    "record.pt",
    "ojogo.pt",
    "maisfutebol.iol.pt",
    "zerozero.pt",

    # Spanish sources
    "marca.com",
    "as.com",
    "mundodeportivo.com",

    # German sources
    "kicker.de",
    "sport1.de",

    # Italian sources
    "football-italia.net",
    "gazzetta.it",
]

def parse_news_date(date_text: str):
    if not date_text or date_text == "unknown":
        return None

    try:
        return dt.date.fromisoformat(date_text[:10])
    except Exception:
        return None


def is_news_recent_enough(published_date: str, match_date_iso: str, max_age_days: int = 3) -> bool:
    news_date = parse_news_date(published_date)
    match_date = parse_news_date(match_date_iso)

    if not news_date or not match_date:
        return False

    age_days = (match_date - news_date).days

    return 0 <= age_days <= max_age_days

def usage_to_dict(response):
    usage = getattr(response, "usage", None)
    return usage.model_dump() if usage else None


def count_web_search_calls(response) -> int:
    count = 0

    try:
        output_items = response.output
    except Exception:
        return 0

    for item in output_items:
        try:
            item_dict = item.model_dump()
        except Exception:
            item_dict = item if isinstance(item, dict) else {}

        if item_dict.get("type") == "web_search_call":
            count += 1

    return count


def clean_json_text(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    return text

def parse_date_safe(date_text: str):
    if not date_text or date_text == "unknown":
        return None

    try:
        return dt.date.fromisoformat(date_text[:10])
    except Exception:
        return None


def is_news_fresh_for_generation(
    published_date: str,
    generation_date_iso: str,
    max_age_days: int = 7,
) -> bool:
    """
    News freshness is based on the generation date, not the match date.

    Example:
    Match is on April 30.
    Text is generated on April 27.
    News window is April 20-April 27.
    Relative to match date, that means up to 10 days before match.
    """
    news_date = parse_date_safe(published_date)
    generation_date = parse_date_safe(generation_date_iso)

    if not news_date or not generation_date:
        return False

    age_days = (generation_date - news_date).days

    return 0 <= age_days <= max_age_days

def research_match_news(
    openai_api_key: str,
    model: str,
    home_team: str,
    away_team: str,
    competition: str,
    match_date_iso: str,
    generation_date_iso: str,
) -> Dict[str, Any]:
    """
    Searches trusted sources for recent team news and returns approved facts only.

    Output facts are intentionally short and cautious.
    The article writer will not see raw articles, only these approved facts.
    """
    client = OpenAI(api_key=openai_api_key)

    instructions = """
You are a strict football news researcher.

Your job:
Find fresh, relevant, reputable pre-match news facts that can affect the reasoning for a football forecast explanation.

Freshness rule:
- Use the generation date as the freshness anchor, not the match date.
- Only return news published within 7 days before the generation date.
- Do not return old news from previous months, previous seasons, or old transfer windows.
- If an older article is superseded by a newer update, keep only the newer update.
- If the published date is unknown, do not include the fact.

Relevance rule:
Every fact must be clearly related to:
- this exact match,
- one of the two teams,
- a player from one of the two teams,
- a manager from one of the two teams,
- or a recent event that affects this match.

Research topics:
Look for all of these, not only injuries:
- injuries
- suspensions
- player availability
- players returning from injury
- transfers / player sales / recent squad departures
- personal news affecting key players
- disciplinary issues
- manager quotes
- player quotes
- rotation risk
- fixture congestion
- morale after recent important matches
- tactical/team-selection news
- key goalkeeper or defender availability
- top attacker or playmaker availability
- official predicted lineups when from reputable sources

Key-player rule:
Only include injury, personal-news, or absence claims if the player is important.
A player is important if the source or context clearly suggests one of:
- regular starter
- captain
- top scorer
- important assister/creator
- main goalkeeper
- key defender
- named in predicted lineup
- widely described as important/key

Source quality:
Prefer:
- official club sites
- UEFA / FIFA / league sites
- Reuters / AP / BBC / Sky Sports / ESPN
- reputable local sports outlets
- reputable national sports outlets

Reject:
- fan blogs
- forums
- Reddit
- social media-only rumours
- unverified transfer rumours
- betting-tip sites
- outdated articles
- articles not clearly related to this match or these teams

Return 6 to 10 useful facts if available.
If fewer reliable facts exist, return fewer.
Do not invent anything.

Each fact should be useful for explaining the forecast.
Avoid generic schedule facts unless they add real context.

Return strict JSON only, with this shape:
{
  "facts": [
    {
      "claim": "...",
      "team": "...",
      "type": "injury|suspension|return|transfer|personal|manager_quote|player_quote|rotation|morale|fixture_congestion|team_news|tactical|other",
      "source_title": "...",
      "source_url": "...",
      "published_date": "YYYY-MM-DD",
      "confidence": "high|medium|low",
      "why_it_matters": "short explanation of why this can affect this match"
    }
  ],
  "notes": "short explanation of search quality"
}
"""

    query = f"""
Match: {home_team} vs {away_team}
Competition: {competition}
Match date: {match_date_iso}
Generation date: {generation_date_iso}

Search fresh reputable news published within 7 days before the generation date.

Research both teams deeply:
1. injuries and player availability
2. suspensions and disciplinary issues
3. player returns from injury
4. transfers, player sales, or recent squad departures
5. personal news affecting key players
6. manager and player quotes
7. rotation and predicted lineup news
8. fixture congestion
9. morale after recent matches
10. tactical/team-selection news

Only return facts clearly related to this match, these teams, or important players/managers.
Return 6 to 10 verified facts if available.
Return strict JSON only.
"""

    response = client.responses.create(
        model=model,
        tools=[
            {
                "type": "web_search",
                "filters": {
                    "allowed_domains": TRUSTED_NEWS_DOMAINS
                },
            }
        ],
        tool_choice="auto",
        include=["web_search_call.action.sources"],
        input=[
            {
                "role": "system",
                "content": instructions,
            },
            {
                "role": "user",
                "content": query,
            },
        ],
    )

    raw_text = response.output_text
    web_search_calls = count_web_search_calls(response)

    try:
        parsed = json.loads(clean_json_text(raw_text))
    except Exception:
        parsed = {
            "facts": [],
            "notes": "Could not parse news response as JSON.",
            "raw_text": raw_text,
        }

    facts = parsed.get("facts", [])

    # Keep only facts that have at least claim + source_url.
    approved_facts = []

    for item in facts:
        claim = item.get("claim")
        source_url = item.get("source_url")
        published_date = item.get("published_date")
        confidence = item.get("confidence", "medium")
        why_it_matters = item.get("why_it_matters")

        if not claim or not source_url:
            continue

        # Must have a clear published date.
        if not published_date or published_date == "unknown":
            continue

        # Freshness is based on generation date, not match date.
        if not is_news_fresh_for_generation(
            published_date=published_date,
            generation_date_iso=generation_date_iso,
            max_age_days=7,
        ):
            continue

        # Avoid weak facts.
        if confidence not in ["high", "medium"]:
            continue

        # Keep only facts with match relevance.
        if not why_it_matters:
            item["why_it_matters"] = "Relevant to team news or match context."

        approved_facts.append(item)

    return {
        "facts": approved_facts[:10],
        "notes": parsed.get("notes", ""),
        "raw_text": raw_text,
        "usage": usage_to_dict(response),
        "model": model,
        "web_search_calls": web_search_calls,
    }