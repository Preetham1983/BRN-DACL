"""
Fact Extractor — Lightweight LLM call at inference time.

This is the ONLY LLM call during inference — it extracts structured facts
from the natural language query. The actual reasoning/decision is done
deterministically by the DACL Rete engine.
"""
from __future__ import annotations

import json
import logging
import os
import time

from openai import AzureOpenAI
from dotenv import load_dotenv
from dacl_agent.models.schemas import ExtractedFacts

load_dotenv()
log = logging.getLogger(__name__)

from langsmith import wrappers
client = wrappers.wrap_openai(
    AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
)
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

_MAX_RETRIES = 2
_RETRY_DELAY = 1.0  # seconds

FACT_EXTRACTOR_SYSTEM = """
You are a fact extractor for a DACL (Deterministic AI Contract Logic) engine.

Your job is to identify the user's intent and extract ALL relevant structured facts.
If the user mentions multiple topics (e.g., life insurance and business protection), extract facts for both.

Output JSON with this exact schema:
{
  "intent": "brief description of what the user wants",
  "domain": "the primary business domain",
  "query_summary": "one-line summary",
  "facts": {
    "field_name": value,
    ...
  }
}

CRITICAL RULES:
- use EXACT field names from the "Required field names" list.
- If a value is implied (e.g. "I'm a smoker"), set the field to "Y" (or True if numeric).
- If a user mentions a topic but omits the actual value (e.g. "for my storefront" but no size given), do NOT invent the value. Leave it out.
- Map synonyms (e.g. "body mass index" -> "bmi", "tobacco" -> "smoker").
- Output ONLY raw JSON. No markdown, no explanation.
""".strip()


def extract_facts(
    query: str,
    domain_hint: str = "",
    required_fields: list[str] | None = None,
) -> ExtractedFacts:
    """INFERENCE TIME: Lightweight LLM call to extract structured facts.

    Retries up to _MAX_RETRIES times on malformed JSON or Pydantic validation
    errors so a single LLM hiccup does not crash the entire request.

    Args:
        query:           Natural language user query.
        domain_hint:     Domain context string.
        required_fields: Exact field names from compiled DACL graph.

    Returns:
        ExtractedFacts — validated, ready for the Rete engine.

    Raises:
        RuntimeError if all retries are exhausted.
    """
    # Build system prompt with domain and field hints
    context_parts: list[str] = []
    if domain_hint:
        context_parts.append(f"Domain context: {domain_hint}")
    if required_fields:
        fields_str = ", ".join(required_fields)
        context_parts.append(
            f"\nRequired field names (use EXACTLY these names in 'facts'):\n  {fields_str}\n"
            f"Map any synonyms from the query to these exact names."
        )

    system_prompt = FACT_EXTRACTOR_SYSTEM
    if context_parts:
        system_prompt += "\n\n" + "\n".join(context_parts)

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=DEPLOYMENT,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract facts from this query:\n\n{query}"},
                ],
            )
            raw  = response.choices[0].message.content
            data = json.loads(raw)

            # Validate that all returned fact keys are in required_fields
            # (catches LLM hallucinating field names that the engine won't know)
            if required_fields:
                unknown = set(data.get("facts", {}).keys()) - set(required_fields)
                if unknown:
                    log.warning(
                        "[FACT-EXTRACTOR] LLM returned unknown fields %s — stripping them",
                        unknown,
                    )
                    for k in unknown:
                        data["facts"].pop(k, None)

            return ExtractedFacts(**data)

        except (json.JSONDecodeError, KeyError, ValueError) as err:
            last_error = err
            log.warning(
                "[FACT-EXTRACTOR] Attempt %d/%d failed: %s",
                attempt + 1, _MAX_RETRIES + 1, err,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)

    raise RuntimeError(
        f"Fact extraction failed after {_MAX_RETRIES + 1} attempts: {last_error}"
    )
