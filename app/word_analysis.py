"""
word_analysis.py - Analyze words in translated sentences using Gemini.

Returns per-word: meaning, part of speech, grammatical case, gender,
difficulty level, and vulgarity flag.
"""

import json
import re
import time

analysis_cache = {}
MAX_ANALYSIS_ATTEMPTS = 5
MAX_OTHER_RATIO = 0.12
VALID_POS = {
    "noun", "verb", "adj", "adv", "prep", "conj",
    "pron", "det", "num", "part", "interj", "other",
}
POS_ALIASES = {
    "adjective": "adj",
    "adverb": "adv",
    "preposition": "prep",
    "conjunction": "conj",
    "pronoun": "pron",
    "determiner": "det",
    "number": "num",
    "numeral": "num",
    "particle": "part",
    "interjection": "interj",
    "proper noun": "noun",
    "proper_noun": "noun",
    "name": "noun",
    "aux": "verb",
    "auxiliary": "verb",
}


def _normalize_pos(pos: str) -> str:
    cleaned = (pos or "").strip().lower().replace("-", " ")
    cleaned = POS_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in VALID_POS else "other"


def _too_many_other(cleaned: list[dict]) -> bool:
    lexical_items = [
        item for item in cleaned
        if re.search(r"\w", item.get("word", ""))
    ]
    if not lexical_items:
        return False
    other_count = sum(1 for item in lexical_items if item.get("pos") == "other")
    return other_count > max(1, int(len(lexical_items) * MAX_OTHER_RATIO))


def _fallback_words(sentence: str) -> list[dict]:
    return [
        {
            "word": w,
            "meaning": "",
            "pos": "other",
            "case": None,
            "gender": None,
            "base_form": w,
            "difficulty": "",
            "vulgar": False,
        }
        for w in sentence.split()
    ]


def analyze_words(sentence: str, language: str, gemini_client, languages_map: dict) -> list[dict]:
    """
    Analyze every word in a sentence.
    Returns a list of dicts, one per word.
    """
    if gemini_client is None:
        return _fallback_words(sentence)

    cache_key = f"{sentence}|{language}"
    if cache_key in analysis_cache:
        return analysis_cache[cache_key]

    lang_name = languages_map.get(language, language)

    case_instruction = '- "case": use null unless the language-specific rules below apply.'
    if language == "ru":
        case_instruction = """- "case": grammatical case of the word in this sentence. Use one of:
    "imenitelnyy", "roditelnyy", "datelnyy", "vinitelnyy", "tvoritelnyy", "predlozhnyy", or null.
  Only nouns, pronouns, and adjectives have case. Verbs, adverbs, conjunctions -> null."""
    elif language == "de":
        case_instruction = """- "case": grammatical case of the word in this sentence. Use one of:
    "Nominativ", "Akkusativ", "Dativ", "Genitiv", or null.
  Only nouns, pronouns, and adjectives have case. Verbs, adverbs, conjunctions -> null."""
    elif language == "tr":
        case_instruction = """- "case": grammatical case or suffix role for Turkish. Use one of:
    "yalin", "belirtme", "yonelme", "bulunma", "ayrilma", "tamlayan", or null.
  Only nouns and pronouns have case. Verbs, adverbs, conjunctions -> null."""

    prompt_base = f"""You are a linguistics expert. Analyze each word in this {lang_name} sentence and return a JSON array.

Sentence: "{sentence}"

Return a JSON array with one object per word in order. Each object must have exactly these keys:
{{
  "word": "the exact word as written",
  "meaning": "1-3 word English translation",
  "pos": "one of: noun/verb/adj/adv/prep/conj/pron/det/num/part/interj/other",
  "base_form": "dictionary form of the word",
  "case": "grammatical case or null",
  "gender": "m/f/n or null",
  "difficulty": "A1/A2/B1/B2/C1",
  "vulgar": true if the word is profanity/vulgar/offensive, false otherwise
}}

Rules:
- Keep the original tokenization and order from the sentence.
- Use "other" only for punctuation, symbols, obvious typos, or tokens you truly cannot classify.
- Proper names are nouns.
- Inflected Turkish words must still be classified by their base function. For example, "uyanir" is verb and "genellikle" is adv.
- Always provide a short English meaning for lexical words.
- Always provide a CEFR difficulty for lexical words.

For "case":
{case_instruction}

For "gender": only for nouns/adjectives in Russian/German. Use "m", "f", or "n". Null for Turkish and other POS.

Respond with ONLY the JSON array. No markdown fences, no explanation."""

    last_cleaned = None
    for attempt in range(MAX_ANALYSIS_ATTEMPTS):
        try:
            from google.genai import types

            retry_instruction = ""
            if attempt > 0:
                retry_instruction = f"""

Your previous response used too many "other" POS labels or left lexical fields incomplete.
Try again and classify every normal lexical word.
Return a meaning and CEFR difficulty for every lexical word.
For Turkish especially: proper names are noun, finite verbs are verb, and frequency words like "genellikle" are adv.
Attempt {attempt + 1} of {MAX_ANALYSIS_ATTEMPTS}."""

            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt_base + retry_instruction,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )

            text = (response.text or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            data = json.loads(text)
            if isinstance(data, list) and len(data) > 0:
                cleaned = []
                for item in data:
                    word = item.get("word", "")
                    cleaned.append(
                        {
                            "word": word,
                            "meaning": (item.get("meaning") or "").strip(),
                            "pos": _normalize_pos(item.get("pos", "other")),
                            "case": item.get("case", None),
                            "gender": item.get("gender", None),
                            "base_form": item.get("base_form", item.get("word", "")),
                            "difficulty": (item.get("difficulty") or "").strip(),
                            "vulgar": item.get("vulgar", False),
                        }
                    )
                last_cleaned = cleaned

                incomplete_lexical = any(
                    re.search(r"\w", item.get("word", ""))
                    and item.get("pos") != "other"
                    and (not item.get("meaning") or not item.get("difficulty"))
                    for item in cleaned
                )
                if _too_many_other(cleaned) or incomplete_lexical:
                    print(f"  [WordAnalysis] Quality retry attempt {attempt + 1}")
                    time.sleep(0.7 + attempt * 0.4)
                    continue

                analysis_cache[cache_key] = cleaned
                return cleaned
        except json.JSONDecodeError as exc:
            print(f"  [WordAnalysis] JSON error attempt {attempt + 1}: {exc}")
        except Exception as exc:
            print(f"  [WordAnalysis] Error attempt {attempt + 1}: {exc}")
            time.sleep(1)

    if last_cleaned:
        analysis_cache[cache_key] = last_cleaned
        return last_cleaned

    return _fallback_words(sentence)
