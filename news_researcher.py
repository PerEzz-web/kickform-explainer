import json
import re
from typing import Any, Dict, List

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


def research_match_news(
    openai_api_key: str,
    model: str,
    home_team: str,
    away_team: str,
    competition: str,
    match_date_iso: str,
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
Find recent, relevant, pre-match news facts for a football match.

Return ONLY verified facts that could affect match reasoning:
- injuries
- suspensions
- rotation hints
- manager quotes
- recent pressure/morale stories
- fixture congestion
- official squad/team news
- major tactical/team availability news

Hard rules:
- Do not include rumours unless a reliable source clearly reports them as confirmed.
- Do not include post-match information.
- Do not include betting tips or predictions from other sites.
- Do not include generic historical facts.
- Do not include fan blogs, forums, Reddit, or social media.
- Do not include a claim unless the source is recent and relevant.
- Prefer official club/league sources, Reuters/AP/BBC/Sky/Guardian/ESPN, or reputable local sports outlets.
- If no reliable news is found, return an empty facts list.
- Do not invent anything.

Date rule:
The match date is provided. News should be from before the match date.
For injuries/team news, prefer articles from the last 14 days before the match.
For broader pressure/morale stories, prefer the last 30 days before the match.

Return strict JSON only, with this shape:
{
  "facts": [
    {
      "claim": "...",
      "team": "...",
      "type": "injury|suspension|manager_quote|rotation|morale|fixture_congestion|team_news|other",
      "source_title": "...",
      "source_url": "...",
      "published_date": "YYYY-MM-DD or unknown",
      "confidence": "high|medium|low"
    }
  ],
  "notes": "short explanation of search quality"
}
"""

    query = f"""
Match: {home_team} vs {away_team}
Competition: {competition}
Match date: {match_date_iso}

Search for reliable recent team news before this match.
Focus on injuries, suspensions, manager quotes, rotation, morale, fixture congestion, and team availability.
Return only verified facts as JSON.
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

        if not claim or not source_url:
            continue

        approved_facts.append(item)

    return {
        "facts": approved_facts[:6],
        "notes": parsed.get("notes", ""),
        "raw_text": raw_text,
        "usage": usage_to_dict(response),
        "model": model,
        "web_search_calls": web_search_calls,
    }