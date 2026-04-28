import datetime as dt
import re
from typing import Any, Dict, List, Optional

import requests


API_BASE = "https://v3.football.api-sports.io"


def sanitize_team_search_name(team_name: str) -> str:
    """
    API-Football team search accepts only alpha-numeric characters and spaces.
    """
    if not team_name:
        return ""

    safe = re.sub(r"[^A-Za-z0-9 ]+", " ", team_name)
    safe = re.sub(r"\s+", " ", safe).strip()

    if len(safe) > 60:
        safe = " ".join(safe.split()[-4:])

    return safe


def normalize_text_for_team_matching(text: str) -> str:
    if not text:
        return ""

    text = text.lower()
    text = text.replace("ü", "u")
    text = text.replace("ö", "o")
    text = text.replace("ä", "a")
    text = text.replace("ß", "ss")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    word_aliases = {
        "munich": "munchen",
        "muenchen": "munchen",
        "münchen": "munchen",
        "psg": "paris saint germain",
        "inter": "internazionale",
        "atletico": "atletico",
        "atlético": "atletico",
    }

    words = []

    for word in text.split():
        words.append(word_aliases.get(word, word))

    return " ".join(words)


def significant_team_words(team_name: str) -> List[str]:
    normalized = normalize_text_for_team_matching(team_name)

    stop_words = {
        "fc",
        "cf",
        "ac",
        "afc",
        "sc",
        "club",
        "football",
        "the",
        "de",
        "del",
        "la",
        "le",
        "real",  # kept out because many clubs include it
    }

    words = [
        word
        for word in normalized.split()
        if word not in stop_words and len(word) >= 3
    ]

    unique_words = []

    for word in words:
        if word not in unique_words:
            unique_words.append(word)

    return unique_words


def generate_team_search_aliases(team_name: str) -> List[str]:
    """
    Generic fallback search names for API-Football.

    Avoids manual per-club replacement.
    Examples:
    FC Arsenal -> Arsenal
    FC Bayern Munich -> Bayern / Bayern Munich
    RCD Espanyol de Barcelona -> Espanyol / Barcelona
    Atletico Madrid -> Atletico Madrid / Atletico / Madrid
    """
    if not team_name:
        return []

    original = team_name.strip()
    words = significant_team_words(original)

    aliases = [original]

    if words:
        # Full significant name.
        aliases.append(" ".join(words))

        # Individual significant words.
        for word in words:
            aliases.append(word.title())

        # Useful two-word combinations.
        if len(words) >= 2:
            for i in range(len(words) - 1):
                aliases.append(f"{words[i].title()} {words[i + 1].title()}")

    # De-duplicate
    unique_aliases = []

    for alias in aliases:
        alias = alias.strip()

        if alias and alias not in unique_aliases:
            unique_aliases.append(alias)

    return unique_aliases


class ApiFootballClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-apisports-key": api_key
        }
        self.debug_calls = []

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        params = params or {}

        response = requests.get(
            url,
            headers=self.headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        self.debug_calls.append(
            {
                "url": url,
                "params": params,
                "errors": data.get("errors"),
                "results": data.get("results"),
                "paging": data.get("paging"),
                "response_count": (
                    len(data.get("response", []))
                    if isinstance(data.get("response"), list)
                    else None
                ),
            }
        )

        errors = data.get("errors")

        if errors and errors != [] and errors != {}:
            raise RuntimeError(
                f"API-Football returned errors for {path} with params {params}: {errors}"
            )

        return data

    def search_team(self, team_name: str) -> List[Dict[str, Any]]:
        aliases = generate_team_search_aliases(team_name)

        all_results = []
        seen_team_ids = set()

        for alias in aliases:
            safe_team_name = sanitize_team_search_name(alias)

            if not safe_team_name:
                continue

            try:
                data = self.get("/teams", {"search": safe_team_name})
            except Exception:
                continue

            results = data.get("response", [])

            for item in results:
                team_id = item.get("team", {}).get("id")

                if team_id and team_id not in seen_team_ids:
                    all_results.append(item)
                    seen_team_ids.add(team_id)

        return all_results

    def get_fixtures_for_team_date(
        self,
        team_id: int,
        date: str,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "team": team_id,
            "date": date,
        }

        if season:
            params["season"] = season

        if league_id:
            params["league"] = league_id

        data = self.get("/fixtures", params)
        return data.get("response", [])

    def get_fixture_candidates_around_date(
        self,
        home_team_id: int,
        away_team_id: int,
        match_date_iso: str,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
        days_before: int = 3,
        days_after: int = 3,
    ) -> List[Dict[str, Any]]:
        match_date = dt.date.fromisoformat(match_date_iso)
        from_date = (match_date - dt.timedelta(days=days_before)).isoformat()
        to_date = (match_date + dt.timedelta(days=days_after)).isoformat()

        params = {
            "team": home_team_id,
            "from": from_date,
            "to": to_date,
        }

        if season:
            params["season"] = season

        if league_id:
            params["league"] = league_id

        data = self.get("/fixtures", params)
        fixtures = data.get("response", [])

        candidates = []

        for fixture in fixtures:
            teams = fixture.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})

            ids = {home.get("id"), away.get("id")}

            if home_team_id in ids and away_team_id in ids:
                candidates.append(fixture)

        return candidates

    def get_fixtures_for_team_range(
        self,
        team_id: int,
        from_date: str,
        to_date: str,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "team": team_id,
            "from": from_date,
            "to": to_date,
        }

        if season:
            params["season"] = season

        if league_id:
            params["league"] = league_id

        data = self.get("/fixtures", params)
        return data.get("response", [])

    def get_last_fixtures_for_team(
        self,
        team_id: int,
        last: int = 5,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "team": team_id,
            "last": last,
        }

        if season:
            params["season"] = season

        if league_id:
            params["league"] = league_id

        data = self.get("/fixtures", params)
        return data.get("response", [])

    def get_head_to_head(self, home_team_id: int, away_team_id: int, last: int = 10) -> List[Dict[str, Any]]:
        data = self.get(
            "/fixtures/headtohead",
            {
                "h2h": f"{home_team_id}-{away_team_id}",
                "last": last,
            },
        )
        return data.get("response", [])

    def get_injuries_for_fixture(self, fixture_id: int) -> List[Dict[str, Any]]:
        data = self.get("/injuries", {"fixture": fixture_id})
        return data.get("response", [])

    def get_standings(self, league_id: int, season: int) -> List[Dict[str, Any]]:
        data = self.get(
            "/standings",
            {
                "league": league_id,
                "season": season,
            },
        )
        return data.get("response", [])


def is_womens_team_name(name: str) -> bool:
    if not name:
        return False

    lower = name.lower()

    womens_markers = [
        " w",
        " women",
        "women",
        "frauen",
        "feminine",
        "femenino",
        "féminin",
    ]

    return any(marker in lower for marker in womens_markers)


def normalize_team_name(name: str) -> str:
    if not name:
        return ""

    normalized = name.lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    removable = [
        "fc",
        "cf",
        "ac",
        "afc",
        "sc",
        "w",
    ]

    words = [word for word in normalized.split() if word not in removable]
    return " ".join(words)


def is_womens_team_name(name: str) -> bool:
    if not name:
        return False

    lower = name.lower().strip()

    womens_markers = [
        " women",
        "women",
        " frauen",
        "frauen",
        " femenino",
        "femenino",
        " fémin",
        "feminine",
    ]

    if lower.endswith(" w"):
        return True

    return any(marker in lower for marker in womens_markers)


def normalize_team_name(name: str) -> str:
    if not name:
        return ""

    normalized = name.lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    removable_words = {"fc", "cf", "ac", "afc", "sc", "club"}

    words = [
        word
        for word in normalized.split()
        if word not in removable_words
    ]

    return " ".join(words)


def is_womens_team_name(name: str) -> bool:
    if not name:
        return False

    lower = name.lower().strip()

    if lower.endswith(" w"):
        return True

    womens_markers = [
        " women",
        "women",
        " frauen",
        "frauen",
        " femenino",
        "femenino",
        "feminine",
        "féminin",
    ]

    return any(marker in lower for marker in womens_markers)


def normalize_team_name(name: str) -> str:
    if not name:
        return ""

    normalized = name.lower()
    normalized = normalized.replace("ü", "u")
    normalized = normalized.replace("ö", "o")
    normalized = normalized.replace("ä", "a")
    normalized = normalized.replace("ß", "ss")
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    removable_words = {"fc", "cf", "ac", "afc", "sc", "club"}

    words = [
        word
        for word in normalized.split()
        if word not in removable_words
    ]

    return " ".join(words)


def is_womens_team_name(name: str) -> bool:
    if not name:
        return False

    lower = name.lower().strip()

    if lower.endswith(" w"):
        return True

    womens_markers = [
        " women",
        "women",
        " frauen",
        "frauen",
        " femenino",
        "femenino",
        "feminine",
        "féminin",
    ]

    return any(marker in lower for marker in womens_markers)


def team_match_score(api_name: str, wanted_name: str) -> int:
    api_words = set(significant_team_words(api_name))
    wanted_words = set(significant_team_words(wanted_name))

    if not api_words or not wanted_words:
        return 0

    overlap = api_words.intersection(wanted_words)

    score = len(overlap) * 10

    api_normalized = normalize_text_for_team_matching(api_name)
    wanted_normalized = normalize_text_for_team_matching(wanted_name)

    if api_normalized == wanted_normalized:
        score += 100

    if wanted_normalized in api_normalized or api_normalized in wanted_normalized:
        score += 30

    # Prefer men's senior teams when names are otherwise similar.
    if is_womens_team_name(api_name):
        score -= 100

    return score


def pick_best_team_match(results: List[Dict[str, Any]], wanted_name: str) -> Optional[Dict[str, Any]]:
    if not results:
        return None

    wanted_is_women = is_womens_team_name(wanted_name)

    candidates = []

    for item in results:
        api_name = item.get("team", {}).get("name") or ""

        if not wanted_is_women and is_womens_team_name(api_name):
            continue

        candidates.append(item)

    if not candidates:
        candidates = results

    candidates = sorted(
        candidates,
        key=lambda item: team_match_score(
            item.get("team", {}).get("name") or "",
            wanted_name,
        ),
        reverse=True,
    )

    return candidates[0]

def find_fixture_between_teams(
    fixtures: List[Dict[str, Any]],
    home_team_id: int,
    away_team_id: int,
) -> Optional[Dict[str, Any]]:
    for fixture in fixtures:
        teams = fixture.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        if home.get("id") == home_team_id and away.get("id") == away_team_id:
            return fixture

        if home.get("id") == away_team_id and away.get("id") == home_team_id:
            return fixture

    return None


def summarize_last_matches(
    fixtures: List[Dict[str, Any]],
    team_id: int,
    limit: int = 5,
    home_away_filter: Optional[str] = None,
) -> Dict[str, Any]:
    finished = []

    for item in fixtures:
        status = item.get("fixture", {}).get("status", {}).get("short")

        if status not in ["FT", "AET", "PEN"]:
            continue

        teams = item.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        is_home = home.get("id") == team_id
        is_away = away.get("id") == team_id

        if home_away_filter == "home" and not is_home:
            continue

        if home_away_filter == "away" and not is_away:
            continue

        finished.append(item)

    finished = sorted(
        finished,
        key=lambda x: x.get("fixture", {}).get("date", ""),
        reverse=True,
    )[:limit]

    wins = draws = losses = goals_for = goals_against = btts = over_2_5 = 0
    clean_sheets = failed_to_score = 0

    matches_summary = []

    for item in finished:
        teams = item.get("teams", {})
        goals = item.get("goals", {})

        home = teams.get("home", {})
        away = teams.get("away", {})

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        is_home = home.get("id") == team_id

        if is_home:
            gf = home_goals
            ga = away_goals
            opponent = away.get("name")
            home_away = "home"
        else:
            gf = away_goals
            ga = home_goals
            opponent = home.get("name")
            home_away = "away"

        goals_for += gf
        goals_against += ga

        if gf > ga:
            wins += 1
            result = "W"
        elif gf == ga:
            draws += 1
            result = "D"
        else:
            losses += 1
            result = "L"

        if gf > 0 and ga > 0:
            btts += 1

        if gf + ga > 2.5:
            over_2_5 += 1

        if ga == 0:
            clean_sheets += 1

        if gf == 0:
            failed_to_score += 1

        matches_summary.append(
            {
                "date": item.get("fixture", {}).get("date"),
                "competition": item.get("league", {}).get("name"),
                "opponent": opponent,
                "home_away": home_away,
                "score_for": gf,
                "score_against": ga,
                "result": result,
            }
        )

    return {
        "matches_used": len(matches_summary),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "btts_count": btts,
        "over_2_5_count": over_2_5,
        "clean_sheets": clean_sheets,
        "failed_to_score": failed_to_score,
        "matches": matches_summary,
    }


def find_team_standing(standings_response: List[Dict[str, Any]], team_id: int) -> Optional[Dict[str, Any]]:
    if not standings_response:
        return None

    for competition_block in standings_response:
        league = competition_block.get("league", {})
        groups = league.get("standings", [])

        for group in groups:
            for row in group:
                team = row.get("team", {})

                if team.get("id") == team_id:
                    all_stats = row.get("all", {}) or {}
                    goals = all_stats.get("goals", {}) or {}

                    return {
                        "rank": row.get("rank"),
                        "team_name": team.get("name"),
                        "points": row.get("points"),
                        "goals_diff": row.get("goalsDiff"),
                        "form": row.get("form"),
                        "description": row.get("description"),
                        "played": all_stats.get("played"),
                        "wins": all_stats.get("win"),
                        "draws": all_stats.get("draw"),
                        "losses": all_stats.get("lose"),
                        "goals_for": goals.get("for"),
                        "goals_against": goals.get("against"),
                    }

    return None


def summarize_h2h(
    fixtures: List[Dict[str, Any]],
    home_team_id: int,
    away_team_id: int,
    home_team_name: str,
    away_team_name: str,
    limit: int = 5,
) -> Dict[str, Any]:
    finished = []

    for item in fixtures:
        status = item.get("fixture", {}).get("status", {}).get("short")

        if status not in ["FT", "AET", "PEN"]:
            continue

        finished.append(item)

    finished = sorted(
        finished,
        key=lambda x: x.get("fixture", {}).get("date", ""),
        reverse=True,
    )[:limit]

    home_team_wins = 0
    away_team_wins = 0
    draws = 0
    btts = 0
    over_2_5 = 0
    matches_summary = []

    for item in finished:
        teams = item.get("teams", {})
        goals = item.get("goals", {})

        actual_home = teams.get("home", {})
        actual_away = teams.get("away", {})

        actual_home_goals = goals.get("home")
        actual_away_goals = goals.get("away")

        if actual_home_goals is None or actual_away_goals is None:
            continue

        if actual_home.get("id") == home_team_id:
            current_home_goals = actual_home_goals
            current_away_goals = actual_away_goals
        else:
            current_home_goals = actual_away_goals
            current_away_goals = actual_home_goals

        if current_home_goals > current_away_goals:
            home_team_wins += 1
        elif current_home_goals < current_away_goals:
            away_team_wins += 1
        else:
            draws += 1

        if current_home_goals > 0 and current_away_goals > 0:
            btts += 1

        if current_home_goals + current_away_goals > 2.5:
            over_2_5 += 1

        matches_summary.append(
            {
                "date": item.get("fixture", {}).get("date"),
                "competition": item.get("league", {}).get("name"),
                "actual_home_team": actual_home.get("name"),
                "actual_away_team": actual_away.get("name"),
                "actual_score": f"{actual_home_goals}-{actual_away_goals}",
            }
        )

    return {
        "matches_used": len(matches_summary),
        "home_team_name": home_team_name,
        "away_team_name": away_team_name,
        "home_team_wins": home_team_wins,
        "away_team_wins": away_team_wins,
        "draws": draws,
        "btts_count": btts,
        "over_2_5_count": over_2_5,
        "matches": matches_summary,
    }