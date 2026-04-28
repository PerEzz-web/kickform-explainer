import datetime as dt
import os

import streamlit as st

from api_football import (
    ApiFootballClient,
    pick_best_team_match,
    find_fixture_between_teams,
    summarize_last_matches,
    find_team_standing,
    summarize_h2h,
)
from cost_tracker import estimate_openai_cost
from evidence_builder import build_evidence
from kickform_scraper import extract_kickform_page
from llm_writer import generate_explanation
from validator import validate_explanation
from llm_repair import repair_explanation
from news_researcher import research_match_news


st.set_page_config(page_title="Kickform Forecast Explainer POC", layout="wide")

st.title("Kickform Forecast Explainer POC")

st.write(
    "Paste a Kickform match URL. The app will extract the forecast, "
    "collect structured football facts from API-Football, and generate a human-style explanation."
)

def get_secret(name: str, default=None):
    """
    Reads secrets locally from .streamlit/secrets.toml
    and online from environment variables, e.g. Render.
    """
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)

def convert_date_text_to_iso(date_text: str):
    if not date_text:
        return None

    cleaned = (
        date_text.replace("st", "")
        .replace("nd", "")
        .replace("rd", "")
        .replace("th", "")
    )

    try:
        parsed = dt.datetime.strptime(cleaned, "%d %B %Y")
        return parsed.date().isoformat()
    except Exception:
        return None


def get_api_football_league_id(competition_name: str):
    if not competition_name:
        return None

    name = competition_name.lower()

    mapping = {
        "premier league": 39,
        "english premier league": 39,
        "champions league": 2,
        "uefa champions league": 2,
        "bundesliga": 78,
        "2. bundesliga": 79,
        "la liga": 140,
        "serie a": 135,
        "ligue 1": 61,
        "europa league": 3,
        "portuguese primeira liga": 94,
        "primeira liga": 94,
    }

    return mapping.get(name)


def get_api_football_season(match_date_iso: str):
    if not match_date_iso:
        return None

    match_date = dt.date.fromisoformat(match_date_iso)

    if match_date.month >= 7:
        return match_date.year

    return match_date.year - 1

def validation_passed(validation_text: str) -> bool:
    if not validation_text:
        return False

    normalized = validation_text.lower()

    if "overall status: pass" not in normalized:
        return False

    if "overall status: fail" in normalized:
        return False

    return True

def safe_get_range_fixtures(api, team_id, from_date, to_date, api_season=None, api_league_id=None):
    """
    Tries to fetch fixtures across all competitions first.
    If API-Football requires season or league, it falls back safely.
    """
    attempts = [
        {"season": None, "league_id": None},
        {"season": api_season, "league_id": None},
        {"season": api_season, "league_id": api_league_id},
    ]

    for attempt in attempts:
        try:
            fixtures = api.get_fixtures_for_team_range(
                team_id=team_id,
                from_date=from_date,
                to_date=to_date,
                season=attempt["season"],
                league_id=attempt["league_id"],
            )

            if fixtures:
                return fixtures
        except Exception:
            pass

    return []


def safe_get_last_fixtures(api, team_id, api_season=None, api_league_id=None, last=15):
    """
    Fallback for recent fixtures.
    Tries all competitions first, then season, then current league.
    """
    attempts = [
        {"season": None, "league_id": None},
        {"season": api_season, "league_id": None},
        {"season": api_season, "league_id": api_league_id},
    ]

    for attempt in attempts:
        try:
            fixtures = api.get_last_fixtures_for_team(
                team_id=team_id,
                last=last,
                season=attempt["season"],
                league_id=attempt["league_id"],
            )

            if fixtures:
                return fixtures
        except Exception:
            pass

    return []

url = st.text_input(
    "Kickform URL",
    value="https://www.sportwettenvergleich.net/kickform/premier-league/manchester-united-vs-brentford-fc/koenj/",
)

run_button = st.button("Generate explanation")

use_news_research = st.checkbox(
    "Use trusted web news research",
    value=False,
    help="Searches trusted news sources for team news, injuries, suspensions, manager quotes, and other current context."
)

if run_button:
    api_football_key = get_secret("API_FOOTBALL_KEY")
    openai_api_key = get_secret("OPENAI_API_KEY")

    if not api_football_key:
        st.error("Missing API_FOOTBALL_KEY. Add it to .streamlit/secrets.toml locally or Render environment variables online.")
        st.stop()

    if not openai_api_key:
        st.error("Missing OPENAI_API_KEY. Add it to .streamlit/secrets.toml locally or Render environment variables online.")
        st.stop()

    openai_writer_model = get_secret("OPENAI_WRITER_MODEL", "gpt-5.4")
    openai_validator_model = get_secret("OPENAI_VALIDATOR_MODEL", "gpt-5.4-mini")
    openai_repair_model = get_secret("OPENAI_REPAIR_MODEL", "gpt-5.4-mini")

    openai_writer_input_cost_per_1m = float(get_secret("OPENAI_WRITER_INPUT_COST_PER_1M", 0))
    openai_writer_output_cost_per_1m = float(get_secret("OPENAI_WRITER_OUTPUT_COST_PER_1M", 0))

    openai_validator_input_cost_per_1m = float(get_secret("OPENAI_VALIDATOR_INPUT_COST_PER_1M", 0))
    openai_validator_output_cost_per_1m = float(get_secret("OPENAI_VALIDATOR_OUTPUT_COST_PER_1M", 0))

    openai_repair_input_cost_per_1m = float(get_secret("OPENAI_REPAIR_INPUT_COST_PER_1M", 0))
    openai_repair_output_cost_per_1m = float(get_secret("OPENAI_REPAIR_OUTPUT_COST_PER_1M", 0))

    openai_web_search_cost_per_1k = float(get_secret("OPENAI_WEB_SEARCH_COST_PER_1K", 10.0))
    api_football_cost_per_call = float(get_secret("API_FOOTBALL_COST_PER_CALL", 0))

    openai_news_model = get_secret("OPENAI_NEWS_MODEL", "gpt-5.4-mini")
    openai_news_input_cost_per_1m = float(get_secret("OPENAI_NEWS_INPUT_COST_PER_1M", 0.75))
    openai_news_output_cost_per_1m = float(get_secret("OPENAI_NEWS_OUTPUT_COST_PER_1M", 4.50))

    writer_usage_items = []
    validator_usage_items = []
    repair_usage_items = []
    news_usage_items = []
    openai_web_search_calls = 0

    with st.spinner("Extracting forecast page..."):
        kickform_data = extract_kickform_page(url)

    match_info = kickform_data["match_info"]
    forecast = kickform_data["forecast"]

    st.subheader("1. Extracted forecast data")
    st.json(kickform_data)

    if kickform_data.get("debug", {}).get("value_tip_source"):
        st.error(
            "A value tip was derived instead of scraped. This should not happen. "
            "The app will ignore derived value tips because they can be wrong."
        )

    home_team = match_info.get("home_team")
    away_team = match_info.get("away_team")

    st.write("Detected home team:", home_team)
    st.write("Detected away team:", away_team)

    match_date_iso = match_info.get("match_date_iso") or convert_date_text_to_iso(
        match_info.get("match_date_text")
    )

    if not home_team or not away_team:
        st.error(
            "Could not detect teams from the page. "
            "Open data/debug_kickform_rendered_text.txt and we will adjust the parser."
        )
        st.stop()

    if len(home_team) > 60 or len(away_team) > 60:
        st.error(
            "Detected team name is too long, which means the parser captured page navigation text."
        )
        st.write("Home team detected:", home_team)
        st.write("Away team detected:", away_team)
        st.stop()

    if not match_date_iso:
        st.warning(
            "Could not parse match date. The app will continue, but API-Football matching may be weaker."
        )

    api = ApiFootballClient(api_football_key)

    with st.spinner("Resolving teams in API-Football..."):
        home_results = api.search_team(home_team)
        away_results = api.search_team(away_team)

        home_api_team = pick_best_team_match(home_results, home_team)
        away_api_team = pick_best_team_match(away_results, away_team)

    if not home_api_team or not away_api_team:
        st.error("Could not resolve one or both teams in API-Football.")
        st.write("Home results:", home_results)
        st.write("Away results:", away_results)
        st.stop()

    home_team_id = home_api_team["team"]["id"]
    away_team_id = away_api_team["team"]["id"]

    api_league_id = get_api_football_league_id(match_info.get("competition"))
    api_season = get_api_football_season(match_date_iso)

    st.subheader("2. API-Football team resolution")
    st.write("Home:", home_api_team["team"]["name"], home_team_id)
    st.write("Away:", away_api_team["team"]["name"], away_team_id)
    st.write("API-Football league ID:", api_league_id)
    st.write("API-Football season:", api_season)

    with st.expander("Team resolution debug"):
        st.write("Home API search results")
        st.json(home_results)

        st.write("Away API search results")
        st.json(away_results)

    fixture = None
    injuries = []

    if match_date_iso:
        with st.spinner("Finding fixture in API-Football..."):
            candidate_fixtures = api.get_fixtures_for_team_date(
                team_id=home_team_id,
                date=match_date_iso,
                season=api_season,
                league_id=api_league_id,
            )

            fixture = find_fixture_between_teams(
                candidate_fixtures,
                home_team_id,
                away_team_id,
            )

            if not fixture:
                wider_candidates = api.get_fixture_candidates_around_date(
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    match_date_iso=match_date_iso,
                    season=api_season,
                    league_id=api_league_id,
                    days_before=3,
                    days_after=3,
                )

                fixture = find_fixture_between_teams(
                    wider_candidates,
                    home_team_id,
                    away_team_id,
                )

        if fixture:
            st.subheader("3. Matched fixture")
            st.json(fixture)

            fixture_id = fixture["fixture"]["id"]

            try:
                with st.spinner("Fetching injuries for fixture..."):
                    injuries = api.get_injuries_for_fixture(fixture_id)
            except Exception as e:
                st.warning(f"Could not fetch injuries: {e}")
        else:
            st.warning(
                "Could not find exact fixture in API-Football. "
                "The app will continue with team context only."
            )

    if match_date_iso:
        match_date = dt.date.fromisoformat(match_date_iso)
        from_date = (match_date - dt.timedelta(days=120)).isoformat()
        to_date = (match_date - dt.timedelta(days=1)).isoformat()
    else:
        today = dt.date.today()
        from_date = (today - dt.timedelta(days=120)).isoformat()
        to_date = today.isoformat()

    with st.spinner("Fetching recent form from API-Football..."):
        # Overall recent form across all competitions.
        home_all_fixtures = safe_get_range_fixtures(
            api=api,
            team_id=home_team_id,
            from_date=from_date,
            to_date=to_date,
            api_season=api_season,
            api_league_id=api_league_id,
        )

        away_all_fixtures = safe_get_range_fixtures(
            api=api,
            team_id=away_team_id,
            from_date=from_date,
            to_date=to_date,
            api_season=api_season,
            api_league_id=api_league_id,
        )

        # Current tournament / competition form.
        try:
            home_competition_fixtures = api.get_fixtures_for_team_range(
                team_id=home_team_id,
                from_date=from_date,
                to_date=to_date,
                season=api_season,
                league_id=api_league_id,
            )
        except Exception:
            home_competition_fixtures = []

        try:
            away_competition_fixtures = api.get_fixtures_for_team_range(
                team_id=away_team_id,
                from_date=from_date,
                to_date=to_date,
                season=api_season,
                league_id=api_league_id,
            )
        except Exception:
            away_competition_fixtures = []

        if not home_all_fixtures:
            home_all_fixtures = safe_get_last_fixtures(
                api=api,
                team_id=home_team_id,
                api_season=api_season,
                api_league_id=api_league_id,
                last=15,
            )

        if not away_all_fixtures:
            away_all_fixtures = safe_get_last_fixtures(
                api=api,
                team_id=away_team_id,
                api_season=api_season,
                api_league_id=api_league_id,
                last=15,
            )

        home_form = summarize_last_matches(home_all_fixtures, home_team_id, limit=5)
        away_form = summarize_last_matches(away_all_fixtures, away_team_id, limit=5)

        home_home_form = summarize_last_matches(
            home_all_fixtures,
            home_team_id,
            limit=5,
            home_away_filter="home",
        )

        away_away_form = summarize_last_matches(
            away_all_fixtures,
            away_team_id,
            limit=5,
            home_away_filter="away",
        )

        home_competition_form = summarize_last_matches(
            home_competition_fixtures,
            home_team_id,
            limit=5,
        )

        away_competition_form = summarize_last_matches(
            away_competition_fixtures,
            away_team_id,
            limit=5,
        )

    st.subheader("4. Deterministic form summaries")

    col1, col2 = st.columns(2)

    with col1:
        st.write(home_team)
        st.write("Overall form across competitions")
        st.json(home_form)

        st.write("Home-only form across competitions")
        st.json(home_home_form)

        st.write(f"{match_info.get('competition')} form")
        st.json(home_competition_form)

    with col2:
        st.write(away_team)
        st.write("Overall form across competitions")
        st.json(away_form)

        st.write("Away-only form across competitions")
        st.json(away_away_form)

        st.write(f"{match_info.get('competition')} form")
        st.json(away_competition_form)

    home_standing = None
    away_standing = None

    if api_league_id and api_season:
        try:
            with st.spinner("Fetching league standings..."):
                standings_response = api.get_standings(
                    league_id=api_league_id,
                    season=api_season,
                )

                home_standing = find_team_standing(standings_response, home_team_id)
                away_standing = find_team_standing(standings_response, away_team_id)

            st.subheader("5. League standings")
            scol1, scol2 = st.columns(2)

            with scol1:
                st.write(home_team)
                st.json(home_standing)

            with scol2:
                st.write(away_team)
                st.json(away_standing)

        except Exception as e:
            st.warning(f"Could not fetch standings: {e}")

    h2h_summary = None

    try:
        with st.spinner("Fetching head-to-head matches..."):
            h2h_fixtures = api.get_head_to_head(
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                last=10,
            )

            h2h_summary = summarize_h2h(
                fixtures=h2h_fixtures,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_team_name=home_team,
                away_team_name=away_team,
                limit=5,
            )

        st.subheader("6. Head-to-head summary")
        st.json(h2h_summary)

    except Exception as e:
        st.warning(f"Could not fetch head-to-head data: {e}")

    with st.expander("API-Football debug calls"):
        st.json(api.debug_calls)

    news_facts = []
    news_result = None

    if use_news_research:
        with st.spinner("Researching trusted news sources..."):
            news_result = research_match_news(
                openai_api_key=openai_api_key,
                model=openai_news_model,
                home_team=home_team,
                away_team=away_team,
                competition=match_info.get("competition"),
                match_date_iso=match_date_iso,
            )

        news_facts = news_result.get("facts", [])
        news_usage_items.append(news_result.get("usage"))
        openai_web_search_calls += news_result.get("web_search_calls", 0)

        st.subheader("7a. Approved news facts")
        st.json(news_facts)

        with st.expander("News research raw output"):
            st.write("Notes:", news_result.get("notes"))
            st.write("Web search calls:", news_result.get("web_search_calls"))
            st.write("Raw response:")
            st.text(news_result.get("raw_text", ""))

    with st.spinner("Building approved evidence facts..."):
        evidence = build_evidence(
            match_info=match_info,
            forecast=forecast,
            home_form=home_form,
            away_form=away_form,
            home_home_form=home_home_form,
            away_away_form=away_away_form,
            home_competition_form=home_competition_form,
            away_competition_form=away_competition_form,
            home_standing=home_standing,
            away_standing=away_standing,
            h2h_summary=h2h_summary,
            injuries=injuries,
            news_facts=news_facts,
        )

    st.subheader("7. Approved evidence facts")
    st.json(evidence)

    example_facts = [item for item in evidence if item.get("category") == "examples"]

    if example_facts:
        st.subheader("7b. Selected example facts")
        st.json(example_facts)

    with st.spinner("Generating draft explanation with OpenAI..."):
        writer_result = generate_explanation(
            openai_api_key=openai_api_key,
            model=openai_writer_model,
            match_info=match_info,
            forecast=forecast,
            evidence_facts=evidence,
        )

    draft_explanation = writer_result["text"]
    writer_usage_items.append(writer_result.get("usage"))

    st.subheader("8. Draft explanation")
    st.markdown(draft_explanation)

    with st.spinner("Validating draft explanation..."):
        draft_validation_result = validate_explanation(
            openai_api_key=openai_api_key,
            model=openai_validator_model,
            explanation=draft_explanation,
            evidence_facts=evidence,
            forecast=forecast,
        )

    draft_validation = draft_validation_result["text"]
    validator_usage_items.append(draft_validation_result.get("usage"))

    st.subheader("9. Draft validation report")
    st.markdown(draft_validation)

    final_explanation = draft_explanation
    final_validation = draft_validation

    repair_history = [
        {
            "round": 0,
            "text": draft_explanation,
            "validation": draft_validation,
        }
    ]

    max_repair_rounds = 5
    repair_round = 0

    while not validation_passed(final_validation) and repair_round < max_repair_rounds:
        repair_round += 1

        with st.spinner(f"Repairing unsupported claims, round {repair_round}..."):
            repair_result = repair_explanation(
                openai_api_key=openai_api_key,
                model=openai_repair_model,
                draft_text=final_explanation,
                validation_report=final_validation,
                match_info=match_info,
                forecast=forecast,
                evidence_facts=evidence,
            )
        final_explanation = repair_result["text"]
        repair_usage_items.append(repair_result.get("usage"))

        with st.spinner(f"Validating repaired explanation, round {repair_round}..."):
            final_validation_result = validate_explanation(
                openai_api_key=openai_api_key,
                model=openai_validator_model,
                explanation=final_explanation,
                evidence_facts=evidence,
                forecast=forecast,
            )

        final_validation = final_validation_result["text"]
        validator_usage_items.append(final_validation_result.get("usage"))

        repair_history.append(
            {
                "round": repair_round,
                "text": final_explanation,
                "validation": final_validation,
            }
        )

    approved = validation_passed(final_validation)

    st.subheader("10. Final explanation")

    if approved:
        st.success("Approved by validation.")
    else:
        st.warning(
            "Validation did not pass automatically. Review the validation details below. "
            "This is usually caused by the validator being too strict or by a sentence needing another prompt adjustment."
        )

    st.markdown(final_explanation)

    st.subheader("11. Final validation report")
    st.markdown(final_validation)

    with st.expander("Repair history"):
        st.json(repair_history)

    writer_cost_report = estimate_openai_cost(
        usage_items=writer_usage_items,
        input_cost_per_1m=openai_writer_input_cost_per_1m,
        output_cost_per_1m=openai_writer_output_cost_per_1m,
        web_search_calls=0,
        web_search_cost_per_1k=openai_web_search_cost_per_1k,
    )

    validator_cost_report = estimate_openai_cost(
        usage_items=validator_usage_items,
        input_cost_per_1m=openai_validator_input_cost_per_1m,
        output_cost_per_1m=openai_validator_output_cost_per_1m,
        web_search_calls=0,
        web_search_cost_per_1k=openai_web_search_cost_per_1k,
    )

    news_cost_report = estimate_openai_cost(
        usage_items=news_usage_items,
        input_cost_per_1m=openai_news_input_cost_per_1m,
        output_cost_per_1m=openai_news_output_cost_per_1m,
        web_search_calls=openai_web_search_calls,
        web_search_cost_per_1k=openai_web_search_cost_per_1k,
    )

    repair_cost_report = estimate_openai_cost(
        usage_items=repair_usage_items,
        input_cost_per_1m=openai_repair_input_cost_per_1m,
        output_cost_per_1m=openai_repair_output_cost_per_1m,
        web_search_calls=0,
        web_search_cost_per_1k=openai_web_search_cost_per_1k,
    )

    total_openai_cost = (
        writer_cost_report["total_openai_cost_usd"]
        + validator_cost_report["total_openai_cost_usd"]
        + repair_cost_report["total_openai_cost_usd"]
        + news_cost_report["total_openai_cost_usd"]
    )

    total_input_tokens = (
        writer_cost_report["input_tokens"]
        + validator_cost_report["input_tokens"]
        + repair_cost_report["input_tokens"]
        + news_cost_report["input_tokens"]
    )

    total_output_tokens = (
        writer_cost_report["output_tokens"]
        + validator_cost_report["output_tokens"]
        + repair_cost_report["output_tokens"]
        + news_cost_report["output_tokens"]
    )

    total_tokens = total_input_tokens + total_output_tokens

    api_football_total_cost = round(
        len(api.debug_calls) * api_football_cost_per_call,
        6,
    )

    total_generation_cost = round(
        total_openai_cost + api_football_total_cost,
        6,
    )

    st.subheader("12. Cost report")

    st.json(
        {
            "generation_cost_summary": {
                "total_generation_cost_usd": total_generation_cost,
                "openai_total_cost_usd": round(total_openai_cost, 6),
                "api_football_total_cost_usd": api_football_total_cost,
                "note": "Total generation cost includes OpenAI token/tool costs plus estimated API-Football calls.",
            },
            "openai": {
                "total": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_tokens,
                    "total_openai_cost_usd": round(total_openai_cost, 6),
                    "web_search_calls": openai_web_search_calls,
                    "web_search_cost_usd": 0,
                },
                "writer": {
                    "model": openai_writer_model,
                    "calls": len([item for item in writer_usage_items if item]),
                    **writer_cost_report,
                },
                "validator": {
                    "model": openai_validator_model,
                    "calls": len([item for item in validator_usage_items if item]),
                    **validator_cost_report,
                },
                "repair": {
                    "model": openai_repair_model,
                    "calls": len([item for item in repair_usage_items if item]),
                    **repair_cost_report,
                },
                "news": {
                    "model": openai_news_model,
                    "calls": len([item for item in news_usage_items if item]),
                    **news_cost_report,
                },
            },
            "api_football": {
                "calls": len(api.debug_calls),
                "estimated_cost_usd": api_football_total_cost,
                "debug_calls": api.debug_calls,
            },
        }
    )
