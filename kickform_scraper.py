import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def german_date_to_iso(date_text: str):
    if not date_text:
        return None

    months = {
        "januar": "01",
        "februar": "02",
        "märz": "03",
        "maerz": "03",
        "april": "04",
        "mai": "05",
        "juni": "06",
        "juli": "07",
        "august": "08",
        "september": "09",
        "oktober": "10",
        "november": "11",
        "dezember": "12",
    }

    m = re.search(
        r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s+(\d{4})",
        date_text,
        re.IGNORECASE,
    )

    if not m:
        return None

    day = int(m.group(1))
    month_name = m.group(2).lower()
    year = int(m.group(3))

    month = months.get(month_name)

    if not month:
        return None

    return f"{year}-{month}-{day:02d}"


def team_name_from_slug(slug: str) -> str:
    name = slug.replace("-", " ").strip()
    name = name.title()

    replacements = {
        " Fc": " FC",
        " Afc": " AFC",
        " Utd": " Utd",
        " Psg": "PSG",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    return name


def extract_teams_from_url(url: str):
    """
    Fallback parser from URL.

    Example:
    /kickform/premier-league/manchester-united-vs-brentford-fc/koenj/
    """
    m = re.search(r"/kickform/[^/]+/([^/]+)/", url)

    if not m:
        return None, None

    match_slug = m.group(1)

    if "-vs-" not in match_slug:
        return None, None

    home_slug, away_slug = match_slug.split("-vs-", 1)

    return team_name_from_slug(home_slug), team_name_from_slug(away_slug)


def german_date_to_iso(date_text: str):
    if not date_text:
        return None

    months = {
        "januar": "01",
        "februar": "02",
        "märz": "03",
        "maerz": "03",
        "april": "04",
        "mai": "05",
        "juni": "06",
        "juli": "07",
        "august": "08",
        "september": "09",
        "oktober": "10",
        "november": "11",
        "dezember": "12",
    }

    m = re.search(
        r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s+(\d{4})",
        date_text,
        re.IGNORECASE,
    )

    if not m:
        return None

    day = int(m.group(1))
    month_name = m.group(2).lower()
    year = int(m.group(3))

    month = months.get(month_name)

    if not month:
        return None

    return f"{year}-{month}-{day:02d}"


def extract_match_info_from_text(text: str, url: str) -> Dict[str, Any]:
    """
    Extract basic match info from rendered Kickform page text.

    Important:
    This parses line by line to avoid accidentally capturing the whole page menu.
    """
    result = {
        "url": url,
        "home_team": None,
        "away_team": None,
        "competition": None,
        "match_date_text": None,
        "match_date_iso": None,
        "kickoff_time_text": None,
        "venue": None,
    }

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1) Best text pattern:
    # Manchester United vs. Brentford – Tipp, Statistiken...
    for line in lines:
        m = re.match(
            r"^(.+?)\s+vs\.?\s+(.+?)\s+[–-]\s+(?:Tipp|Predictions|Statistiken|Prognosen)",
            line,
            re.IGNORECASE,
        )

        if m:
            result["home_team"] = clean_text(m.group(1))
            result["away_team"] = clean_text(m.group(2))
            break

    # 2) Breadcrumb/simple line fallback:
    # Manchester United vs Brentford
    if not result["home_team"] or not result["away_team"]:
        for line in lines:
            m = re.match(
                r"^([A-Za-zÀ-ÿ0-9\s\.\-&']{2,60}?)\s+vs\.?\s+([A-Za-zÀ-ÿ0-9\s\.\-&']{2,60}?)$",
                line,
                re.IGNORECASE,
            )

            if m:
                result["home_team"] = clean_text(m.group(1))
                result["away_team"] = clean_text(m.group(2))
                break

    # 3) German sentence fallback:
    # Spiel Manchester United gegen Brentford am 27. April 2026
    if not result["home_team"] or not result["away_team"]:
        for line in lines:
            m = re.search(
                r"Spiel\s+(.+?)\s+gegen\s+(.+?)\s+am\s+\d{1,2}\.",
                line,
                re.IGNORECASE,
            )

            if m:
                result["home_team"] = clean_text(m.group(1))
                result["away_team"] = clean_text(m.group(2))
                break

    # 4) URL fallback.
    if not result["home_team"] or not result["away_team"]:
        home_from_url, away_from_url = extract_teams_from_url(url)
        result["home_team"] = result["home_team"] or home_from_url
        result["away_team"] = result["away_team"] or away_from_url

    # Safety cleanup: if a team name is clearly too long, use URL fallback.
    if result["home_team"] and len(result["home_team"]) > 60:
        home_from_url, away_from_url = extract_teams_from_url(url)
        result["home_team"] = home_from_url
        result["away_team"] = away_from_url

    # Date:
    german_date_match = re.search(
        r"(\d{1,2}\.\s*[A-Za-zÄÖÜäöüß]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )

    if german_date_match:
        result["match_date_text"] = german_date_match.group(1)
        result["match_date_iso"] = german_date_to_iso(result["match_date_text"])

    # ISO date fallback, useful when network JSON is used.
    if not result["match_date_iso"]:
        iso_date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)

        if iso_date_match:
            result["match_date_text"] = iso_date_match.group(1)
            result["match_date_iso"] = iso_date_match.group(1)

    # English date fallback:
    if not result["match_date_text"]:
        english_date_match = re.search(
            r"([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4})",
            text,
            re.IGNORECASE,
        )

        if english_date_match:
            result["match_date_text"] = english_date_match.group(1)

    # Time:
    time_match = re.search(r"um\s+([0-9]{1,2}:[0-9]{2})\s+Uhr", text, re.IGNORECASE)

    if time_match:
        result["kickoff_time_text"] = time_match.group(1)

    if not result["kickoff_time_text"]:
        time_match = re.search(r"at\s+([0-9]{1,2}:[0-9]{2})", text, re.IGNORECASE)

        if time_match:
            result["kickoff_time_text"] = time_match.group(1)

    # Venue:
    venue_match = re.search(r"Spielort:\s*([^\n/]+)", text, re.IGNORECASE)

    if venue_match:
        result["venue"] = clean_text(venue_match.group(1))

    # Competition from URL.
    if "/premier-league/" in url:
        result["competition"] = "Premier League"
    elif "/champions-league/" in url:
        result["competition"] = "Champions League"
    elif "/bundesliga/" in url:
        result["competition"] = "Bundesliga"
    elif "/2-bundesliga/" in url:
        result["competition"] = "2. Bundesliga"
    elif "/la-liga/" in url:
        result["competition"] = "La Liga"
    elif "/serie-a/" in url:
        result["competition"] = "Serie A"
    elif "/ligue-1/" in url:
        result["competition"] = "Ligue 1"

    return result


def collect_json_network_responses(url: str) -> Dict[str, Any]:
    """
    Runs Playwright in a separate Python process.

    This avoids the Windows + Streamlit + Playwright asyncio issue.
    """
    worker_path = Path(__file__).parent / "scrape_kickform_worker.py"

    result = subprocess.run(
        [sys.executable, str(worker_path), url],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Playwright worker failed.\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}"
        )

    try:
        worker_result = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise RuntimeError(
            "Could not parse worker output.\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}\n\n"
            f"Error: {e}"
        )

    if not worker_result.get("ok"):
        raise RuntimeError(
            "Playwright worker returned an error:\n"
            f"{worker_result.get('error')}"
        )

    output_file = Path(worker_result["output_file"])

    if not output_file.exists():
        raise RuntimeError(f"Worker output file not found: {output_file}")

    browser_data = json.loads(output_file.read_text(encoding="utf-8"))

    return browser_data

def round_probability(value):
    if value is None:
        return None
    return round(float(value))


def round_probability_1dp(value):
    if value is None:
        return None
    return round(float(value), 1)


def find_fixture_payload(json_hits):
    """
    Finds the useful WIS fixture JSON inside captured network responses.
    This is the cleanest source for Kickform data.
    """
    for hit in json_hits:
        data = hit.get("data")

        if not isinstance(data, dict):
            continue

        has_fixture = (
            "home_team" in data
            and "away_team" in data
            and "predictions" in data
        )

        if has_fixture:
            return data

    return None


def extract_from_fixture_payload(payload, original_url):
    predictions = payload.get("predictions", {}) or {}

    trend = predictions.get("trend", {}) or {}
    btts = predictions.get("btts", {}) or {}
    goals = predictions.get("over-under_goals", {}) or {}
    result = predictions.get("result", {}) or {}
    tip = predictions.get("tip", {}) or {}

    home_team = payload.get("home_team", {}) or {}
    away_team = payload.get("away_team", {}) or {}
    competition = payload.get("competition", {}) or {}

    correct_score = []

    for key in ["result1", "result2", "result3"]:
        item = result.get(key)
        if not item:
            continue

        home_goals = item.get("home_goals")
        away_goals = item.get("away_goals")
        percent = item.get("percent")

        if home_goals is not None and away_goals is not None and percent is not None:
            correct_score.append(
                {
                    "score": f"{home_goals}-{away_goals}",
                    "probability": round_probability_1dp(percent),
                }
            )

    # value_tips can be empty. In that case, do not invent a value tip.
    value_tips = payload.get("value_tips") or []
    value_tip = None
    confidence = None

    if value_tips:
        first_tip = value_tips[0]
        value_tip = (
            first_tip.get("tip")
            or first_tip.get("selection")
            or first_tip.get("name")
            or first_tip.get("title")
        )
        confidence = (
            first_tip.get("confidence")
            or first_tip.get("rating")
            or first_tip.get("score")
        )

    # fallback to internal tip recommendation if it exists
    if not value_tip:
        value_tip = tip.get("tip_recommendation")

    return {
        "match_info": {
            "url": original_url,
            "fixture_id": payload.get("id"),
            "hash_id": payload.get("hash_id"),
            "home_team": home_team.get("display_name") or home_team.get("name"),
            "away_team": away_team.get("display_name") or away_team.get("name"),
            "home_team_id": home_team.get("id"),
            "away_team_id": away_team.get("id"),
            "competition": competition.get("display_name") or competition.get("name"),
            "competition_id": competition.get("id"),
            "season_id": payload.get("season_id"),
            "match_date_text": payload.get("date"),
            "match_date_iso": payload.get("date"),
            "kickoff_time_text": payload.get("time"),
            "timezone": payload.get("timezone"),
            "venue": payload.get("venue"),
            "referee": payload.get("referee"),
            "status": payload.get("status"),
        },
        "forecast": {
            "value_tip": value_tip,
            "confidence": confidence,
            "top_prediction": tip.get("top_prediction"),
            "match_outcome": {
                "home_win": round_probability(trend.get("1")),
                "draw": round_probability(trend.get("X")),
                "away_win": round_probability(trend.get("2")),
            },
            "correct_score": correct_score,
            "both_teams_to_score": {
                "yes": round_probability(btts.get("btts_yes")),
                "no": round_probability(btts.get("btts_no")),
            },
            "match_goals": {
                "over_1_5": round_probability(goals.get("over_1_5")),
                "under_1_5": round_probability(goals.get("under_1_5")),
                "over_2_5": round_probability(goals.get("over_2_5")),
                "under_2_5": round_probability(goals.get("under_2_5")),
                "over_3_5": round_probability(goals.get("over_3_5")),
                "under_3_5": round_probability(goals.get("under_3_5")),
            },
        },
    }

def parse_percent_value(value: str):
    if value is None:
        return None

    value = value.replace("%", "").replace(",", ".").strip()

    try:
        number = float(value)

        if number.is_integer():
            return int(number)

        return number
    except Exception:
        return None


def get_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip()]


def find_line_index(lines, label):
    label_lower = label.lower()

    for index, line in enumerate(lines):
        if label_lower in line.lower():
            return index

    return -1


def next_percentages_after(lines, start_index, count=3, max_scan=20):
    values = []

    for line in lines[start_index + 1:start_index + 1 + max_scan]:
        m = re.search(r"([0-9]+(?:[\.,][0-9]+)?)\s*%", line)

        if m:
            values.append(parse_percent_value(m.group(1)))

        if len(values) >= count:
            break

    return values


def try_extract_forecast_from_text(text: str) -> Dict[str, Any]:
    """
    Extract forecast values from rendered text.

    Supports German SWV labels:
    - Wahrscheinlichkeit Spielausgang
    - Wahrscheinlichkeit des exakten Ergebnisses
    - Beide Teams treffen
    - Wahrscheinlichkeit Anzahl der Tore
    """
    forecast = {
        "value_tip": None,
        "confidence": None,
        "top_prediction": None,
        "match_outcome": {
            "home_win": None,
            "draw": None,
            "away_win": None,
        },
        "correct_score": [],
        "both_teams_to_score": {
            "yes": None,
            "no": None,
        },
        "match_goals": {
            "over_1_5": None,
            "under_1_5": None,
            "over_2_5": None,
            "under_2_5": None,
            "over_3_5": None,
            "under_3_5": None,
        },
    }

    lines = get_lines(text)

    # 1X2 probabilities
    idx = find_line_index(lines, "Wahrscheinlichkeit Spielausgang")
    if idx == -1:
        idx = find_line_index(lines, "Match Outcome Probability")

    if idx != -1:
        values = next_percentages_after(lines, idx, count=3, max_scan=10)

        if len(values) >= 3:
            forecast["match_outcome"]["home_win"] = values[0]
            forecast["match_outcome"]["draw"] = values[1]
            forecast["match_outcome"]["away_win"] = values[2]

    # Correct score probabilities
    idx = find_line_index(lines, "Wahrscheinlichkeit des exakten Ergebnisses")
    if idx == -1:
        idx = find_line_index(lines, "Correct Score Probability")

    if idx != -1:
        correct_scores = []
        scan_lines = lines[idx + 1:idx + 12]

        i = 0
        while i < len(scan_lines) - 1:
            score_line = scan_lines[i]
            probability_line = scan_lines[i + 1]

            score_match = re.search(r"\b([0-9]+)\s*[-:]\s*([0-9]+)\b", score_line)
            probability_match = re.search(
                r"([0-9]+(?:[\.,][0-9]+)?)\s*%",
                probability_line,
            )

            if score_match and probability_match:
                home_goals = score_match.group(1)
                away_goals = score_match.group(2)

                correct_scores.append(
                    {
                        "score": f"{home_goals}-{away_goals}",
                        "probability": parse_percent_value(probability_match.group(1)),
                    }
                )

                i += 2
            else:
                i += 1

        forecast["correct_score"] = correct_scores[:3]

        if correct_scores:
            forecast["top_prediction"] = correct_scores[0]["score"]

    # Both teams to score
    idx = find_line_index(lines, "Beide Teams treffen")
    if idx == -1:
        idx = find_line_index(lines, "Both Teams to Score")

    if idx != -1:
        # German structure:
        # Beide Teams treffen
        # Ja
        # 64%
        # Nein
        # 36%
        yes_value = None
        no_value = None

        for i in range(idx + 1, min(idx + 10, len(lines))):
            current_line = lines[i].lower()

            if current_line in ["ja", "yes"] and i + 1 < len(lines):
                m = re.search(r"([0-9]+(?:[\.,][0-9]+)?)\s*%", lines[i + 1])
                if m:
                    yes_value = parse_percent_value(m.group(1))

            if current_line in ["nein", "no"] and i + 1 < len(lines):
                m = re.search(r"([0-9]+(?:[\.,][0-9]+)?)\s*%", lines[i + 1])
                if m:
                    no_value = parse_percent_value(m.group(1))

        forecast["both_teams_to_score"]["yes"] = yes_value
        forecast["both_teams_to_score"]["no"] = no_value

    # Match goals probabilities
    idx = find_line_index(lines, "Wahrscheinlichkeit Anzahl der Tore")
    if idx == -1:
        idx = find_line_index(lines, "Match Goals Probability")

    if idx != -1:
        scan_lines = lines[idx + 1:idx + 30]

        for i, line in enumerate(scan_lines):
            line_lower = line.lower()

            # German labels: Über 1.5 / Unter 1.5
            # English labels: Over 1.5 / Under 1.5
            over_match = re.search(r"(?:über|over)\s+([123]\.5)", line_lower)
            under_match = re.search(r"(?:unter|under)\s+([123]\.5)", line_lower)

            if over_match:
                goals_line = over_match.group(1).replace(".", "_")
                key = f"over_{goals_line}"

                # Usually the percentage is 2 lines later:
                # Über 1.5
                # Unter 1.5
                # 84%
                for possible_line in scan_lines[i + 1:i + 5]:
                    m = re.search(r"([0-9]+(?:[\.,][0-9]+)?)\s*%", possible_line)
                    if m:
                        forecast["match_goals"][key] = parse_percent_value(m.group(1))
                        break

            if under_match:
                goals_line = under_match.group(1).replace(".", "_")
                key = f"under_{goals_line}"

                # Usually the percentage is 2 lines later after over percentage:
                # Unter 1.5
                # 84%
                # 16%
                percentages_after = []
                for possible_line in scan_lines[i + 1:i + 6]:
                    m = re.search(r"([0-9]+(?:[\.,][0-9]+)?)\s*%", possible_line)
                    if m:
                        percentages_after.append(parse_percent_value(m.group(1)))

                if len(percentages_after) >= 2:
                    forecast["match_goals"][key] = percentages_after[1]
                elif len(percentages_after) == 1:
                    forecast["match_goals"][key] = percentages_after[0]

    return forecast

def is_missing(value):
    return value is None or value == "" or value == [] or value == {}


def merge_missing_values(base, fallback):
    """
    Fill missing values in base using fallback.
    Keeps existing good values from network JSON.
    Adds missing values from rendered text.
    """
    if not isinstance(base, dict) or not isinstance(fallback, dict):
        return base

    for key, fallback_value in fallback.items():
        base_value = base.get(key)

        if isinstance(base_value, dict) and isinstance(fallback_value, dict):
            merge_missing_values(base_value, fallback_value)
        elif is_missing(base_value) and not is_missing(fallback_value):
            base[key] = fallback_value

    return base


def extract_value_tip_from_text(text: str) -> Dict[str, Any]:
    """
    Extracts visible Kickform Value Tip from rendered page text.

    Supports:
    KICKFORM VALUE TIP
    Gil Vicente to Win
    18/25
    CONFIDENCE RATING

    Also supports when the text is flattened into one line.
    """
    result = {
        "value_tip": None,
        "confidence": None,
    }

    normalized = re.sub(r"\s+", " ", text).strip()

    marker_match = re.search(
        r"(kickform\s+value\s+tip|value\s+tip)",
        normalized,
        re.IGNORECASE,
    )

    if marker_match:
        after_marker = normalized[marker_match.end():marker_match.end() + 800]

        confidence_match = re.search(r"\b([0-9]{1,2}/[0-9]{1,2})\b", after_marker)

        if confidence_match:
            result["confidence"] = confidence_match.group(1)
            candidate_area = after_marker[:confidence_match.start()]
        else:
            candidate_area = after_marker

        candidate_area = re.split(
            r"confidence\s+rating|confidence",
            candidate_area,
            flags=re.IGNORECASE,
        )[0]

        candidate_area = clean_text(candidate_area)

        candidate_area = re.sub(
            r"^(kickform\s+value\s+tip|value\s+tip)\s*",
            "",
            candidate_area,
            flags=re.IGNORECASE,
        ).strip()

        value_tip_patterns = [
            r"([A-Za-zÀ-ÿ0-9 .'\-&]+?\s+to\s+Win)",
            r"([A-Za-zÀ-ÿ0-9 .'\-&]+?\s+Win)",
            r"(Both Teams to Score\s*:?\s*(?:Yes|No))",
            r"(Both Teams Score\s*:?\s*(?:Yes|No))",
            r"(BTTS\s*:?\s*(?:Yes|No))",
            r"(Over\s+\d+(?:\.\d+)?\s+Goals?)",
            r"(Under\s+\d+(?:\.\d+)?\s+Goals?)",
            r"(Home Win)",
            r"(Away Win)",
            r"(Draw)",
        ]

        for pattern in value_tip_patterns:
            m = re.search(pattern, candidate_area, re.IGNORECASE)

            if m:
                result["value_tip"] = clean_text(m.group(1))
                break

        if result["value_tip"] is None and candidate_area:
            # Final fallback: use short readable text before the confidence score.
            if len(candidate_area) <= 80 and re.search(r"[A-Za-z]", candidate_area):
                result["value_tip"] = candidate_area

    # Line-by-line fallback
    if result["value_tip"] is None or result["confidence"] is None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        value_tip_index = -1

        for index, line in enumerate(lines):
            lower = line.lower()

            if "kickform value tip" in lower or lower == "value tip":
                value_tip_index = index
                break

        if value_tip_index != -1:
            scan_lines = lines[value_tip_index + 1:value_tip_index + 12]

            for line in scan_lines:
                clean_line = clean_text(line)
                lower = clean_line.lower()

                if "confidence rating" in lower:
                    break

                if any(
                    bad in lower
                    for bad in [
                        "kickform value tip",
                        "value tip",
                        "confidence",
                        "rating",
                    ]
                ):
                    continue

                score_match = re.search(r"\b([0-9]{1,2}/[0-9]{1,2})\b", clean_line)

                if score_match and result["confidence"] is None:
                    result["confidence"] = score_match.group(1)
                    continue

                if not re.search(r"[A-Za-z]", clean_line):
                    continue

                if result["value_tip"] is None:
                    result["value_tip"] = clean_line

    return result

def is_plausible_value_tip(text: str) -> bool:
    if not text:
        return False

    lower = text.lower().strip()

    blocked_fragments = [
        "probability",
        "percentage",
        "market probability",
        "match goals probability",
        "correct score probability",
    ]

    if any(fragment in lower for fragment in blocked_fragments):
        return False

    patterns = [
        r"\b.+\s+to\s+win\b",
        r"\bboth teams to score\s*:?\s*(yes|no)\b",
        r"\bbtts\s*:?\s*(yes|no)\b",
        r"\bover\s+\d+(?:\.\d+)?\s+goals?\b",
        r"\bunder\s+\d+(?:\.\d+)?\s+goals?\b",
        r"\bhome win\b",
        r"\baway win\b",
        r"\bdraw\b",
    ]

    return any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns)

def find_value_tip_in_json_object(obj) -> Dict[str, Any]:
    """
    Recursively searches captured JSON responses for real value-tip fields.

    Strict rule:
    Do NOT use generic "name", "title", or "market" fields unless the surrounding
    object clearly looks like a value-tip object.
    """
    result = {
        "value_tip": None,
        "confidence": None,
    }

    def looks_like_value_tip_object(value: Dict[str, Any]) -> bool:
        keys = {str(k).lower() for k in value.keys()}

        value_tip_markers = [
            "value_tip",
            "valuetip",
            "value_tips",
            "valuetips",
            "tip_recommendation",
            "recommendation",
            "confidence",
            "confidence_rating",
            "confidencerating",
        ]

        return any(marker in keys for marker in value_tip_markers)

    def extract_from_dict(value: Dict[str, Any]):
        if not looks_like_value_tip_object(value):
            return

        possible_tip_keys = [
            "value_tip",
            "valueTip",
            "tip_recommendation",
            "recommendation",
            "selection",
            "tip",
            "name",
            "title",
        ]

        possible_confidence_keys = [
            "confidence",
            "confidence_rating",
            "confidenceRating",
        ]

        for key in possible_tip_keys:
            if key in value and result["value_tip"] is None:
                candidate = value.get(key)

                if isinstance(candidate, str):
                    candidate_clean = clean_text(candidate)

                    if is_plausible_value_tip(candidate_clean):
                        result["value_tip"] = candidate_clean

        for key in possible_confidence_keys:
            if key in value and result["confidence"] is None:
                candidate = value.get(key)

                if candidate is not None:
                    result["confidence"] = str(candidate)

    def walk(value):
        if isinstance(value, dict):
            extract_from_dict(value)

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)

    return result


def extract_value_tip_from_json_hits(json_hits) -> Dict[str, Any]:
    result = {
        "value_tip": None,
        "confidence": None,
    }

    for hit in json_hits:
        data = hit.get("data")
        found = find_value_tip_in_json_object(data)

        if found.get("value_tip") and result["value_tip"] is None:
            result["value_tip"] = found["value_tip"]

        if found.get("confidence") and result["confidence"] is None:
            result["confidence"] = found["confidence"]

    return result

def derive_value_tip_from_forecast_if_clear(forecast: Dict[str, Any], match_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Last-resort fallback.

    Important:
    Do NOT derive value tips from goals markets or BTTS.
    That can create wrong value tips, e.g. Under 3.5 instead of Arsenal to Win.

    Only derive a winner tip when the match-outcome forecast is very clearly dominant.
    If not clear, return None and let the app show no value bet instead of a wrong one.
    """
    result = {
        "value_tip": None,
        "confidence": None,
        "derived": False,
    }

    outcome = forecast.get("match_outcome", {}) or {}

    home_win = outcome.get("home_win")
    draw = outcome.get("draw")
    away_win = outcome.get("away_win")

    if home_win is None or draw is None or away_win is None:
        return result

    values = [
        ("home", home_win),
        ("draw", draw),
        ("away", away_win),
    ]

    values = sorted(values, key=lambda item: item[1], reverse=True)

    top_label, top_value = values[0]
    second_label, second_value = values[1]

    # Conservative threshold:
    # Only infer a value tip when one result is clearly ahead.
    if top_value < 60:
        return result

    if top_value - second_value < 15:
        return result

    if top_label == "home":
        home_team = match_info.get("home_team")

        if home_team:
            result["value_tip"] = f"{home_team} to Win"
            result["derived"] = True

    elif top_label == "away":
        away_team = match_info.get("away_team")

        if away_team:
            result["value_tip"] = f"{away_team} to Win"
            result["derived"] = True

    elif top_label == "draw":
        result["value_tip"] = "Draw"
        result["derived"] = True

    return result

def extract_kickform_page(url: str) -> Dict[str, Any]:
    browser_data = collect_json_network_responses(url)

    json_hits = browser_data.get("json_hits", [])
    rendered_text = browser_data["rendered_text"]

    value_tip_debug_lines = []

    for line in rendered_text.splitlines():
        lower = line.lower()

        if (
            "value tip" in lower
            or "kickform" in lower
            or "confidence" in lower
            or "rating" in lower
            or "to win" in lower
            or lower.strip() == "win"
            or "both teams" in lower
            or "both teams to score" in lower
            or "over" in lower
            or "under" in lower
            or "draw" == lower.strip()
            or "/10" in lower
            or "/25" in lower
        ):
            value_tip_debug_lines.append(line)

    # Also save a wider text slice around any confidence score.
    normalized_debug_text = re.sub(r"\s+", " ", rendered_text)

    for score_match in re.finditer(r"\b[0-9]{1,2}/[0-9]{1,2}\b", normalized_debug_text):
        start = max(0, score_match.start() - 250)
        end = min(len(normalized_debug_text), score_match.end() + 250)
        value_tip_debug_lines.append("\n--- SCORE CONTEXT ---\n")
        value_tip_debug_lines.append(normalized_debug_text[start:end])


    (DATA_DIR / "debug_value_tip_candidates.txt").write_text(
        "\n".join(value_tip_debug_lines),
        encoding="utf-8",
    )

    fixture_payload = find_fixture_payload(json_hits)

    # Text fallback is always useful because some values are visible on the page
    # even when the network JSON does not include them.
    text_match_info = extract_match_info_from_text(rendered_text, url)
    text_forecast = try_extract_forecast_from_text(rendered_text)
    text_value_tip = extract_value_tip_from_text(rendered_text)
    json_value_tip = extract_value_tip_from_json_hits(json_hits)

    value_tip = text_value_tip.get("value_tip") or json_value_tip.get("value_tip")
    confidence = text_value_tip.get("confidence") or json_value_tip.get("confidence")

    if value_tip:
        text_forecast["value_tip"] = value_tip

    if confidence:
        text_forecast["confidence"] = confidence

    # Best case: parse clean WIS fixture JSON, then fill missing values from rendered text.
    if fixture_payload:
        extracted = extract_from_fixture_payload(fixture_payload, url)

        extracted["match_info"] = merge_missing_values(
            extracted.get("match_info", {}),
            text_match_info,
        )

        extracted["forecast"] = merge_missing_values(
            extracted.get("forecast", {}),
            text_forecast,
        )


        value_tip_source = None

        # Important:
        # Do NOT derive value tips from forecast probabilities.
        # Value tip is not always the most probable outcome.
        # If the real value tip is not scraped, leave it empty and skip the Value bet section.
        if is_missing(extracted["forecast"].get("value_tip")):
            extracted["forecast"]["value_tip"] = None

        extracted["debug"] = {
            "source": "network_json_fixture_payload_plus_rendered_text_fallback",
            "value_tip_source": value_tip_source,
            "json_network_hits_count": len(json_hits),
            "debug_files": [
                "data/debug_kickform_rendered_text.txt",
                "data/debug_kickform_rendered_html.html",
                "data/debug_kickform_network.json",
                "data/debug_value_tip_candidates.txt",
            ],
        }

        return extracted

    # Fallback: rendered-text parser only.
    return {
        "match_info": text_match_info,
        "forecast": text_forecast,
        "debug": {
            "source": "rendered_text_fallback",
            "json_network_hits_count": len(json_hits),
            "debug_files": [
                "data/debug_kickform_rendered_text.txt",
                "data/debug_kickform_rendered_html.html",
                "data/debug_kickform_network.json",
            ],
        },
    }