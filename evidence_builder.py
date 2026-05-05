from typing import Any, Dict, List, Optional
import datetime as dt


def fact(
    fact_id: str,
    claim: str,
    source: str,
    fact_type: str = "computed",
    category: str = "context",
) -> Dict[str, Any]:
    return {
        "id": fact_id,
        "claim": claim,
        "source": source,
        "type": fact_type,
        "category": category,
        "verification_status": "approved",
    }

def format_date_short(date_text: str) -> str:
    if not date_text:
        return "recently"

    # Input usually looks like: 2026-04-18T19:30:00+00:00
    return date_text[:10]

def parse_iso_date(date_text: str):
    if not date_text:
        return None

    try:
        return dt.date.fromisoformat(date_text[:10])
    except Exception:
        return None


def is_match_recent_enough(
    match: Dict[str, Any],
    match_date_text: str,
    max_age_days: int = 30,
) -> bool:
    """
    Applies only to examples against other teams.
    Head-to-head examples are allowed to be older.
    """
    match_date = parse_iso_date(match_date_text)
    example_date = parse_iso_date(match.get("date"))

    if not match_date or not example_date:
        return False

    age_days = (match_date - example_date).days

    return 0 <= age_days <= max_age_days

def format_team_match_example(team_name: str, match: Dict[str, Any]) -> str:
    opponent = match.get("opponent")
    competition = match.get("competition")
    home_away = match.get("home_away")
    score_for = match.get("score_for")
    score_against = match.get("score_against")
    result = match.get("result")
    date = format_date_short(match.get("date"))

    if not opponent or score_for is None or score_against is None:
        return ""

    location_text = "at home" if home_away == "home" else "away"

    if result == "W":
        result_text = f"beat {opponent} {score_for}-{score_against}"
    elif result == "L":
        result_text = f"lost {score_for}-{score_against} to {opponent}"
    else:
        result_text = f"drew {score_for}-{score_against} with {opponent}"

    if competition:
        return f"On {date}, {team_name} {result_text} {location_text} in the {competition}."

    return f"On {date}, {team_name} {result_text} {location_text}."


def get_first_match_example(
    form: Dict[str, Any],
    team_name: str,
    match_date_text: str = None,
    max_age_days: int = 30,
) -> str:
    matches = form.get("matches") or []

    if match_date_text:
        matches = [
            match
            for match in matches
            if is_match_recent_enough(match, match_date_text, max_age_days)
        ]

    if not matches:
        return ""

    return format_team_match_example(team_name, matches[0])


def get_strong_negative_example(
    form: Dict[str, Any],
    team_name: str,
    match_date_text: str = None,
    max_age_days: int = 30,
) -> str:
    matches = form.get("matches") or []

    if match_date_text:
        matches = [
            match
            for match in matches
            if is_match_recent_enough(match, match_date_text, max_age_days)
        ]

    if not matches:
        return ""

    losses = [m for m in matches if m.get("result") == "L"]

    if not losses:
        return ""

    losses = sorted(
        losses,
        key=lambda m: (m.get("score_against", 0) - m.get("score_for", 0)),
        reverse=True,
    )

    return format_team_match_example(team_name, losses[0])


def get_strong_positive_example(
    form: Dict[str, Any],
    team_name: str,
    match_date_text: str = None,
    max_age_days: int = 30,
) -> str:
    matches = form.get("matches") or []

    if match_date_text:
        matches = [
            match
            for match in matches
            if is_match_recent_enough(match, match_date_text, max_age_days)
        ]

    if not matches:
        return ""

    wins = [m for m in matches if m.get("result") == "W"]

    if not wins:
        return ""

    wins = sorted(
        wins,
        key=lambda m: (m.get("score_for", 0) - m.get("score_against", 0)),
        reverse=True,
    )

    return format_team_match_example(team_name, wins[0])

def interpret_correct_score(score: str, home_team: str, away_team: str) -> str:
    """
    Correct score format is always:
    home goals - away goals
    """
    if not score or "-" not in score:
        return f"{score}"

    try:
        home_goals_text, away_goals_text = score.split("-", 1)
        home_goals = int(home_goals_text.strip())
        away_goals = int(away_goals_text.strip())
    except Exception:
        return f"{score}"

    if home_goals > away_goals:
        return f"{score} means a {home_team} win: {home_team} {home_goals}, {away_team} {away_goals}."

    if away_goals > home_goals:
        return f"{score} means a {away_team} win: {home_team} {home_goals}, {away_team} {away_goals}."

    return f"{score} means a draw: {home_team} {home_goals}, {away_team} {away_goals}."

def format_h2h_example(match: Dict[str, Any]) -> str:
    date = format_date_short(match.get("date"))
    competition = match.get("competition")
    actual_home_team = match.get("actual_home_team")
    actual_away_team = match.get("actual_away_team")
    actual_score = match.get("actual_score")

    if not actual_home_team or not actual_away_team or not actual_score:
        return ""

    if competition:
        return (
            f"The most recent head-to-head example was on {date}, when "
            f"{actual_home_team} and {actual_away_team} finished {actual_score} in the {competition}."
        )

    return (
        f"The most recent head-to-head example was on {date}, when "
        f"{actual_home_team} and {actual_away_team} finished {actual_score}."
    )

def build_evidence(
    match_info: Dict[str, Any],
    forecast: Dict[str, Any],
    home_form: Dict[str, Any],
    away_form: Dict[str, Any],
    home_home_form: Optional[Dict[str, Any]] = None,
    away_away_form: Optional[Dict[str, Any]] = None,
    home_competition_form: Optional[Dict[str, Any]] = None,
    away_competition_form: Optional[Dict[str, Any]] = None,
    home_standing: Optional[Dict[str, Any]] = None,
    away_standing: Optional[Dict[str, Any]] = None,
    h2h_summary: Optional[Dict[str, Any]] = None,
    injuries: Optional[List[Dict[str, Any]]] = None,
    news_facts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    facts = []
    i = 1

    home = match_info.get("home_team") or "Home team"
    away = match_info.get("away_team") or "Away team"
    competition = match_info.get("competition") or "the competition"
    venue = match_info.get("venue")
    match_date = match_info.get("match_date_iso") or match_info.get("match_date_text")

    # -------------------------
    # Match information
    # -------------------------

    if competition:
        facts.append(
            fact(
                f"F{i}",
                f"The match is in the {competition}.",
                "Match information extracted from submitted page",
                "match_info",
                "match_info",
            )
        )
        i += 1

    if venue:
        facts.append(
            fact(
                f"F{i}",
                f"The match is played at {venue}.",
                "Match information extracted from submitted page",
                "match_info",
                "match_info",
            )
        )
        i += 1

    if match_date:
        try:
            parsed_match_date = dt.date.fromisoformat(str(match_date)[:10])
            today = dt.datetime.now(dt.timezone.utc).date()

            if parsed_match_date >= today:
                facts.append(
                    fact(
                        f"F{i}",
                        f"The match date is {match_date}.",
                        "Match information extracted from submitted page or matched fixture",
                        "match_info",
                        "match_info",
                    )
                )
                i += 1
        except Exception:
            pass

    # -------------------------
    # Forecast facts
    # -------------------------

    value_tip = forecast.get("value_tip")
    confidence = forecast.get("confidence")

    if value_tip:
        facts.append(
            fact(
                f"F{i}",
                f"The value tip is {value_tip}.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    if confidence:
        facts.append(
            fact(
                f"F{i}",
                f"The value tip confidence rating is {confidence}.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    home_win = forecast.get("match_outcome", {}).get("home_win")
    draw = forecast.get("match_outcome", {}).get("draw")
    away_win = forecast.get("match_outcome", {}).get("away_win")

    if home_win is not None:
        facts.append(
            fact(
                f"F{i}",
                f"The forecast gives {home} a {home_win}% home-win probability.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    if draw is not None:
        facts.append(
            fact(
                f"F{i}",
                f"The forecast gives the draw a {draw}% probability.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    if away_win is not None:
        facts.append(
            fact(
                f"F{i}",
                f"The forecast gives {away} a {away_win}% away-win probability.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    correct_scores = forecast.get("correct_score") or []

    for index, score_item in enumerate(correct_scores):
        score = score_item.get("score")
        probability = score_item.get("probability")

        if score and probability is not None:
            score_meaning = interpret_correct_score(score, home, away)

            if index == 0:
                claim = (
                    f"The top correct-score expectation is {score}. "
                    f"{score_meaning} "
                    f"This is the main correct-score direction to explain."
                )
            else:
                claim = (
                    f"Another correct-score option is {score}. "
                    f"{score_meaning}"
                )

            facts.append(
                fact(
                    f"F{i}",
                    claim,
                    "Submitted forecast",
                    "forecast",
                    "forecast",
                )
            )
            i += 1

    btts = forecast.get("both_teams_to_score", {}) or {}

    if btts.get("yes") is not None:
        facts.append(
            fact(
                f"F{i}",
                f"The forecast gives Both Teams To Score Yes a {btts.get('yes')}% probability.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    if btts.get("no") is not None:
        facts.append(
            fact(
                f"F{i}",
                f"The forecast gives Both Teams To Score No a {btts.get('no')}% probability.",
                "Submitted forecast",
                "forecast",
                "forecast",
            )
        )
        i += 1

    goals = forecast.get("match_goals", {}) or {}

    goal_labels = {
        "over_1_5": "Over 1.5 Goals",
        "under_1_5": "Under 1.5 Goals",
        "over_2_5": "Over 2.5 Goals",
        "under_2_5": "Under 2.5 Goals",
        "over_3_5": "Over 3.5 Goals",
        "under_3_5": "Under 3.5 Goals",
    }

    for key, label in goal_labels.items():
        value = goals.get(key)

        if value is not None:
            facts.append(
                fact(
                    f"F{i}",
                    f"The forecast gives {label} a {value}% probability.",
                    "Submitted forecast",
                    "forecast",
                    "forecast",
                )
            )
            i += 1

    # -------------------------
    # Standings
    # -------------------------

    if home_standing:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{home} are {home_standing.get('rank')} in the {competition} table with "
                    f"{home_standing.get('points')} points from {home_standing.get('played')} matches. "
                    f"Their league record is {home_standing.get('wins')} wins, {home_standing.get('draws')} draws "
                    f"and {home_standing.get('losses')} losses, with {home_standing.get('goals_for')} goals scored "
                    f"and {home_standing.get('goals_against')} conceded."
                ),
                "API-Football standings endpoint",
                "standings",
                "standings",
            )
        )
        i += 1

    if away_standing:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{away} are {away_standing.get('rank')} in the {competition} table with "
                    f"{away_standing.get('points')} points from {away_standing.get('played')} matches. "
                    f"Their league record is {away_standing.get('wins')} wins, {away_standing.get('draws')} draws "
                    f"and {away_standing.get('losses')} losses, with {away_standing.get('goals_for')} goals scored "
                    f"and {away_standing.get('goals_against')} conceded."
                ),
                "API-Football standings endpoint",
                "standings",
                "standings",
            )
        )
        i += 1

    # -------------------------
    # Overall recent form across competitions
    # -------------------------

    if home_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{home} have {home_form['wins']} wins, {home_form['draws']} draws and "
                    f"{home_form['losses']} losses in the last {home_form['matches_used']} finished matches found "
                    f"across all competitions. They scored {home_form['goals_for']} and conceded "
                    f"{home_form['goals_against']} in that sample."
                ),
                "API-Football fixtures, calculated by app across all competitions",
                "team_form",
                "team_form",
            )
        )
        i += 1

        facts.append(
            fact(
                f"F{i}",
                (
                    f"{home}'s last {home_form['matches_used']} finished matches across all competitions included "
                    f"{home_form['btts_count']} matches where both teams scored, "
                    f"{home_form['over_2_5_count']} matches with over 2.5 total goals, "
                    f"{home_form['clean_sheets']} clean sheets and "
                    f"{home_form['failed_to_score']} matches where they failed to score."
                ),
                "API-Football fixtures, calculated by app across all competitions",
                "goals_trend",
                "team_form",
            )
        )
        i += 1

    if away_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{away} have {away_form['wins']} wins, {away_form['draws']} draws and "
                    f"{away_form['losses']} losses in the last {away_form['matches_used']} finished matches found "
                    f"across all competitions. They scored {away_form['goals_for']} and conceded "
                    f"{away_form['goals_against']} in that sample."
                ),
                "API-Football fixtures, calculated by app across all competitions",
                "team_form",
                "team_form",
            )
        )
        i += 1

        facts.append(
            fact(
                f"F{i}",
                (
                    f"{away}'s last {away_form['matches_used']} finished matches across all competitions included "
                    f"{away_form['btts_count']} matches where both teams scored, "
                    f"{away_form['over_2_5_count']} matches with over 2.5 total goals, "
                    f"{away_form['clean_sheets']} clean sheets and "
                    f"{away_form['failed_to_score']} matches where they failed to score."
                ),
                "API-Football fixtures, calculated by app across all competitions",
                "goals_trend",
                "team_form",
            )
        )
        i += 1

    # -------------------------
    # Home / away form across competitions
    # -------------------------

    if home_home_form and home_home_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{home} have {home_home_form['wins']} wins, {home_home_form['draws']} draws and "
                    f"{home_home_form['losses']} losses in their last {home_home_form['matches_used']} home matches "
                    f"found across all competitions. They scored {home_home_form['goals_for']} and conceded "
                    f"{home_home_form['goals_against']} in those home matches."
                ),
                "API-Football fixtures, home matches calculated by app across all competitions",
                "home_form",
                "home_away_form",
            )
        )
        i += 1

    if away_away_form and away_away_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"{away} have {away_away_form['wins']} wins, {away_away_form['draws']} draws and "
                    f"{away_away_form['losses']} losses in their last {away_away_form['matches_used']} away matches "
                    f"found across all competitions. They scored {away_away_form['goals_for']} and conceded "
                    f"{away_away_form['goals_against']} in those away matches."
                ),
                "API-Football fixtures, away matches calculated by app across all competitions",
                "away_form",
                "home_away_form",
            )
        )
        i += 1

    # -------------------------
    # Current competition form
    # -------------------------

    if home_competition_form and home_competition_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"In the {competition}, {home} have {home_competition_form['wins']} wins, "
                    f"{home_competition_form['draws']} draws and {home_competition_form['losses']} losses "
                    f"in their last {home_competition_form['matches_used']} finished matches found. "
                    f"They scored {home_competition_form['goals_for']} and conceded "
                    f"{home_competition_form['goals_against']} in that competition sample."
                ),
                "API-Football fixtures, current competition calculated by app",
                "competition_form",
                "competition_form",
            )
        )
        i += 1

    if away_competition_form and away_competition_form.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"In the {competition}, {away} have {away_competition_form['wins']} wins, "
                    f"{away_competition_form['draws']} draws and {away_competition_form['losses']} losses "
                    f"in their last {away_competition_form['matches_used']} finished matches found. "
                    f"They scored {away_competition_form['goals_for']} and conceded "
                    f"{away_competition_form['goals_against']} in that competition sample."
                ),
                "API-Football fixtures, current competition calculated by app",
                "competition_form",
                "competition_form",
            )
        )
        i += 1

    # -------------------------
    # Selected example facts
    # These are trust anchors for the writer.
    # The writer should use only a few of them, not all.
    # -------------------------

    example_claims = []

    home_latest_example = get_first_match_example(home_form, home, match_date)
    if home_latest_example:
        example_claims.append(
            (
                home_latest_example,
                "API-Football fixtures, latest overall match example",
                "recent_match_example",
                "examples",
            )
        )

    away_latest_example = get_first_match_example(away_form, away, match_date)
    if away_latest_example:
        example_claims.append(
            (
                away_latest_example,
                "API-Football fixtures, latest overall match example",
                "recent_match_example",
                "examples",
            )
        )

    home_positive_example = get_strong_positive_example(home_home_form or {}, home, match_date)
    if home_positive_example:
        example_claims.append(
            (
                home_positive_example,
                "API-Football fixtures, selected home-form example",
                "home_match_example",
                "examples",
            )
        )

    away_negative_example = get_strong_negative_example(away_away_form or {}, away, match_date)
    if away_negative_example:
        example_claims.append(
            (
                away_negative_example,
                "API-Football fixtures, selected away-form example",
                "away_match_example",
                "examples",
            )
        )

    home_competition_example = get_first_match_example(home_competition_form or {}, home, match_date)
    if home_competition_example:
        example_claims.append(
            (
                home_competition_example,
                "API-Football fixtures, selected current-competition example",
                "competition_match_example",
                "examples",
            )
        )

    away_competition_example = get_first_match_example(away_competition_form or {}, away, match_date)
    if away_competition_example:
        example_claims.append(
            (
                away_competition_example,
                "API-Football fixtures, selected current-competition example",
                "competition_match_example",
                "examples",
            )
        )

    deduped_example_claims = []
    seen_example_claims = set()

    for claim, source, fact_type, category in example_claims:
        normalized_claim = claim.lower().strip()

        if normalized_claim in seen_example_claims:
            continue

        seen_example_claims.add(normalized_claim)
        deduped_example_claims.append((claim, source, fact_type, category))

    for claim, source, fact_type, category in deduped_example_claims[:6]:
        facts.append(
            fact(
                f"F{i}",
                claim,
                source,
                fact_type,
                category,
            )
        )
        i += 1

    # -------------------------
    # Head-to-head
    # -------------------------

    if h2h_summary and h2h_summary.get("matches_used", 0) > 0:
        facts.append(
            fact(
                f"F{i}",
                (
                    f"In the last {h2h_summary['matches_used']} head-to-head matches found, "
                    f"{home} won {h2h_summary['home_team_wins']}, "
                    f"{away} won {h2h_summary['away_team_wins']} and "
                    f"{h2h_summary['draws']} ended in a draw. "
                    f"{h2h_summary['btts_count']} of those matches had both teams scoring and "
                    f"{h2h_summary['over_2_5_count']} had over 2.5 total goals."
                ),
                "API-Football head-to-head fixtures, calculated by app",
                "head_to_head",
                "head_to_head",
            )
        )
        i += 1

        h2h_matches = h2h_summary.get("matches") or []

        if h2h_matches:
            h2h_example = format_h2h_example(h2h_matches[0])

            if h2h_example:
                facts.append(
                    fact(
                        f"F{i}",
                        h2h_example,
                        "API-Football head-to-head fixtures, latest example",
                        "head_to_head_example",
                        "examples",
                    )
                )
                i += 1

    # -------------------------
    # Injuries
    # -------------------------
    # Do not add raw injury facts yet.
    #
    # Injury facts should only be used when the injured player is:
    # - top 3 scorer,
    # - top 3 assister,
    # - key defender who played >80% of matches this season,
    # - or main goalkeeper who played >80% of matches this season.
    #
    # Until we add player-stat qualification, raw injury data is excluded
    # to avoid overvaluing irrelevant absences.
    # -------------------------
    # News facts
    # -------------------------

    if news_facts:
        for news_item in news_facts[:10]:
            claim = news_item.get("claim")
            source_title = news_item.get("source_title")
            source_url = news_item.get("source_url")
            news_type = news_item.get("type", "news")
            confidence = news_item.get("confidence", "medium")
            why_it_matters = news_item.get("why_it_matters")
            published_date = news_item.get("published_date")

            if claim:
                facts.append(
                    fact(
                        f"F{i}",
                        (
                            f"Fresh news context from {published_date}: {claim} "
                            f"Why it matters: {why_it_matters or 'Relevant to the match context.'} "
                            f"(confidence: {confidence})."
                        ),
                        source_url or "Web news research",
                        f"news_{news_type}",
                        "news",
                    )
                )
                i += 1

    return facts