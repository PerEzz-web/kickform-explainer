import json
from typing import Any, Dict, List, Optional

from openai import OpenAI


def usage_to_dict(response):
    usage = getattr(response, "usage", None)
    return usage.model_dump() if usage else None


def validate_explanation(
    openai_api_key: str,
    model: str,
    explanation: str,
    evidence_facts: List[Dict[str, Any]],
    forecast: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = OpenAI(api_key=openai_api_key)

    has_value_bet = False

    if forecast:
        has_value_bet = bool(
            forecast.get("value_tip")
            or forecast.get("confidence")
        )

    instructions = """
You are a strict but fair football fact-checking validator.

Your job:
Check whether the article is safe to publish.

Important:
The article should NOT sound like a forecast table.
It is okay and preferred if the article does not mention forecast percentages.

Forecast validation:
- The forecast is the internal source of truth for expected outcomes.
- Do not require the article to mention exact forecast numbers.
- Instead, check whether the article's direction matches the forecast.
- If the article says the wrong team is more likely, FAIL.
- If the article says the wrong BTTS direction, FAIL.
- If the article says the wrong goals direction, FAIL.
- If the article says the wrong most likely scoreline, FAIL.
- If forecast numbers are mentioned, they must match exactly.
- But the best article will usually avoid forecast percentages.

Robotic wording check:
Forbidden wording in article body only:
- Kickform
- AI
- model
- algorithm
- formula
- API
- evidence
- source
- validation
- data pipeline
- priced at
- forecast gives
- the market says

Important:
Do not apply forbidden-word checks to required section headings.

Allowed natural wording:
- "Atalanta look the more likely winner"
- "a narrow away win looks like the cleanest route"
- "one side failing to score feels slightly more likely"
- "the game should have goals without becoming a shootout"
- "the match probably stays controlled"
- "there is still a route for the underdog"

Factual validation:
- Any player name in the article must appear in approved facts.
- Any injury claim must appear in approved facts.
- Any transfer claim must appear in approved facts.
- Any recent-form claim must appear in approved facts.
- Any all-competitions form claim must appear in approved facts.
- Any current-competition form claim must appear in approved facts.
- Any home-form or away-form claim must appear in approved facts.
- Any league-table claim must appear in approved facts.
- Any head-to-head claim must appear in approved facts.
- Any manager-pressure claim must appear in approved facts.
- Any "worst season", "must win", "crisis", "under pressure", or similar claim must appear in approved facts.
- Match venue and competition are allowed only if they appear in approved match_info facts.
- Any news claim must appear in approved evidence facts.
- Any manager quote must appear in approved evidence facts.
- Any squad/team-news claim must appear in approved evidence facts.
- Any fixture-congestion claim must appear in approved evidence facts.

Correct score validation:
- Correct score format is always HOME goals - AWAY goals.
- The first number belongs to the home team.
- The second number belongs to the away team.
- If the article says 2-1 is an away-team win, FAIL.
- If the article says 1-2 is a home-team win, FAIL.
- If the article assigns a scoreline to the wrong team, FAIL and provide the corrected sentence.
- Alternative scorelines must also be interpreted correctly.

News-source wording:
The article should not mention URLs or source names.
It may use the substance of approved news facts, but not citations inside the final article.

Reasoning validation:
- Do not fail normal football interpretation if it is clearly based on approved facts.
- It is okay to say a team has the edge if the forecast and context support it.
- It is okay to say a match looks controlled/low-scoring if goals expectations and context support it.
- It is okay to mention league table position as context.
- But if league position is used as the only reason for an outcome, request a rewrite.
- Head-to-head should be used where available, especially when it is relevant to the section.
- Recent matches in other competitions may be mentioned if included in all-competitions form.
Concrete examples:
- It is okay for the article to include 2 to 4 short concrete examples from approved facts.
- Do not fail the article for using examples if the scores and opponents match approved facts.
- Do fail the article if it invents a scoreline, opponent, competition, or date.

Required section headings:
- Match Outcome Probability
- Correct Score Probability
- Both Teams to Score
- Match Goals Probability

Optional section:
- Value bet, only when value bet exists.

Value bet rule:
- If has_value_bet is false, do not require a Value bet section.
- If has_value_bet is true, require a Value bet section.

Value bet validation:
- If forecast.value_tip is null or missing, the article must not contain a Value bet section.
- If forecast.value_tip is present, the Value bet section must explain that exact value tip.
- The article must never invent a value bet from match outcome, goals, or BTTS probabilities.
- If the article contains a Value bet section while forecast.value_tip is missing, FAIL.

Example freshness validation:
- Specific match examples against teams other than the current opponent must be within 30 days before the match date.
- Head-to-head examples between the two playing teams may be older.

Section rules:
- 3 to 5 sentences is preferred.
- 6 sentences is acceptable when the extra sentence adds approved news context.
- Do not fail a section only because it has 6 sentences and the extra sentence is useful, approved news context.
- The article should avoid forecast percentages.
- Context stats are allowed if supported by approved facts.

Important section-count rule:
- Section headings are not sentences.
- Do not count headings such as "Value bet", "Match Outcome Probability", "Correct Score Probability", "Both Teams to Score", or "Match Goals Probability" as article sentences.
- When checking whether a section has 3 to 6 sentences, count only the body text below the heading.

- Any specific match-result example in the article must appear in approved facts.
- Specific examples such as "lost 3-1 to Alverca" or "drew 1-1 with Casa Pia" are allowed only if approved evidence contains that result.

News validation:
- Approved news facts are allowed when they are in the approved evidence facts.
- Do not fail a sentence for using news if the claim is supported by an approved news fact.
- News may be blended with API stats and football reasoning.
- Do not require the article to mention source names.
- In fact, source names and URLs should not appear in the final article.
- If a news claim is supported but phrased too strongly, request a softer rewrite rather than removing it.

Examples of acceptable news usage:
- "Vitinha being available helps PSG keep their midfield structure, although the recent foot issue adds a small fitness caveat."
- "Bayern's confirmed absences reduce some squad depth, even if their attacking form remains strong."
- "The comeback against Real Madrid adds to Bayern's confidence."

Output format:
Return exactly this format:

Overall status: PASS or FAIL

Issues:
- If none, write: None
- Otherwise list each issue in this exact format:
  - Sentence: "..."
    Problem: ...
    Correct fact available: yes/no
    Fix action: replace_number_only / replace_phrase / rewrite_sentence / remove_sentence
    Corrected sentence: "..." or None

Forbidden wording:
- If none, write: None

The required section heading "Value bet" is allowed and must never be listed as forbidden wording.

Structure issues:
- If none, write: None

Recommended edits:
- If PASS, write: None
- If FAIL, briefly explain what must be fixed.

Critical consistency rules:
- If there are no real unsupported claims, forbidden words, direction mismatches, or structure issues, status must be PASS.
- Never output FAIL while saying "No issue".
- Never output FAIL while saying the article can pass as written.

False issue prevention:
- Never list a sentence in Issues if the Problem says "No issue", "acceptable", "supported", "consistent", "fine", or "can pass as written".
- If a sentence is directionally correct and supported by approved facts, do not list it as an issue.
- Do not output Fix action: remove_sentence for a sentence that is supported.
- Do not output Corrected sentence: None for a sentence that has no real issue.
- If all potential issues are actually acceptable, the final status must be PASS.

Very important:
If you write "No issue" anywhere in the Issues section, you are making a mistake.
Supported sentences must be omitted from Issues entirely.

Required headings are allowed:
- Match Outcome Probability
- Correct Score Probability
- Both Teams to Score
- Match Goals Probability
- Value bet

Do not treat words inside required headings as forbidden wording.
For example:
- "Probability" is allowed inside "Match Outcome Probability" and "Correct Score Probability".
- "Both Teams to Score" is allowed as a required heading.
Only scan the body text below headings for forbidden wording.

Critical consistency rule:
If every listed issue says "No issue", "acceptable", "consistent", or "can pass as written", the final status must be PASS.
Never output FAIL together with "The article can pass as written."
Never list a sentence as an issue if the Problem field says it is acceptable or consistent.
If there are no actual issues, output exactly:

Overall status: PASS

Issues:
- None

Forbidden wording:
- None

Structure issues:
- None

Recommended edits:
- None
"""

    payload = {
        "article": explanation,
        "approved_context_facts": evidence_facts,
        "forecast_expectations_source_of_truth": forecast or {},
        "has_value_bet": has_value_bet,
    }

    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps(payload, ensure_ascii=False, indent=2),
    )

    return {
        "text": response.output_text,
        "usage": usage_to_dict(response),
        "model": model,
    }