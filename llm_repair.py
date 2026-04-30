import json
from typing import Any, Dict, List

from openai import OpenAI


def usage_to_dict(response):
    usage = getattr(response, "usage", None)
    return usage.model_dump() if usage else None


def repair_explanation(
    openai_api_key: str,
    model: str,
    draft_text: str,
    validation_report: str,
    match_info: Dict[str, Any],
    forecast: Dict[str, Any],
    evidence_facts: List[Dict[str, Any]],
    output_language: str = "en",
) -> Dict[str, Any]:
    client = OpenAI(api_key=openai_api_key)

    instructions = """
You are a strict football editor.

Revise the draft so it becomes safe and natural to publish.

Goal:
Create a clean, final, fan-facing football explanation that:
- matches the internal forecast direction,
- uses only approved context facts,
- sounds like a human football expert,
- does not sound like a forecast table.

Very important:
Do not use robotic forecast-table wording.
Avoid:
- percentages
- "probability"
- "priced at"
- "forecast gives"
- "market"
- "Both Teams To Score No at"
- "Over 1.5 Goals at"
- "Under 3.5 Goals at"
- "top correct score is ... at 15.0%"

Use natural wording:
- "Atalanta look the more likely winner"
- "a narrow away win looks the cleanest route"
- "one side failing to score feels slightly more likely"
- "the game looks more likely to have a couple of goals than finish flat"
- "a shootout feels less likely"
- "the underdog still has a route if they keep it tight"

Language rule:
- Preserve the requested output language.
- If output_language is "de", the repaired article must be in German.
- If output_language is "en", the repaired article must be in English.
- Do not translate team names, player names, stadium names, or competition names.

Repair rules:
- Fix every issue in the validation report.
- Do not add new facts.
- Use only approved context facts.
- Use the forecast only as internal expectation, not as public source text.
- Do not challenge the forecast.
- Do not suggest alternative predictions.
- If a sentence sounds robotic, rewrite it naturally.
- If a sentence has unsupported facts, remove or rewrite it.
- If a section lacks reasoning, add reasoning from approved facts.
- Prioritize head-to-head where relevant.
- Mention other tournaments when they appear in recent all-competitions form.
- Do not use league position alone as the reason for an outcome.

News preservation:
- Do not remove approved news insights just to make the text shorter.
- If a news claim is supported by approved facts and relevant to the match, keep it where possible.
- If the validation issue is only wording, rewrite the sentence but preserve the news insight.
- Use 2 to 3 approved recent news insights across the final article when available.
- Remove news only if it is unsupported, outdated, irrelevant, or too speculative.

Correct score repair:
- Correct score format is always HOME goals - AWAY goals.
- If the draft assigns a scoreline to the wrong team, correct it.
- For example, in PSG vs Bayern Munich, 1-2 is a Bayern win, 2-1 is a PSG win, and 2-2 is a draw.
- Do not leave incorrect scoreline ownership in the final text.

Output structure:
Use the heading set that matches output_language.

If output_language is "de":
Value-Tipp
Spielausgang
Korrektes Ergebnis
Beide Teams treffen
Tore im Spiel

If output_language is "en":
Value bet
Match Outcome Probability
Correct Score Probability
Both Teams to Score
Match Goals Probability

Only include the Value-Tipp / Value bet section if a value tip exists in the forecast.
If there is no value tip, do not include that section.

Each section:
- 3 to 5 sentences
- natural football language
- no citations
- no source names
- no evidence IDs
- no internal notes

Final output:
Only the corrected fan-facing article text.
"""

    payload = {
        "draft_text": draft_text,
        "validation_report": validation_report,
        "match_info": match_info,
        "forecast_expectations_source_of_truth": forecast,
        "approved_context_facts": evidence_facts,
        "output_language": output_language,
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