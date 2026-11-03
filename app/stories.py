"""
stories.py - CEFR-graded short stories made by Gemini, plus punctuation clean-up.
"""

from __future__ import annotations

import re
import time

import gemini
from translation import LANGUAGES, STYLES

class StoryError(RuntimeError):
    """A story problem with a message that is safe to show to the learner."""


def clean_story_punctuation(text: str, language: str | None = None) -> str:
    """Normalize common model punctuation artifacts before analysis/rendering."""
    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove spaces before terminal/clause punctuation.
    text = re.sub("\\s+([,.;:!?\\u2026])", r"\1", text)

    # Add one space after punctuation when a word starts immediately after it.
    text = re.sub("([,.;:!?\\u2026])([^\\s\"')\\]\\}\\u00bb\\u201d])", r"\1 \2", text)

    # Collapse repeated horizontal whitespace without removing paragraph breaks.
    text = re.sub(r"[ \t]{2,}", " ", text)

    text = _repair_dialogue_quote_fragments(text)
    text = _clean_straight_quote_spacing(text)
    text = re.sub("([,.;:!?\\u2026])\"(?=\\w)", r'\1 "', text)
    text = re.sub("([\\u201c\\u00ab])\\s+", r"\1", text)
    text = re.sub("\\s+([\\u201d\\u00bb])", r"\1", text)
    text = re.sub("([\\u201d\\u00bb])(?=\\w)", r"\1 ", text)
    if language == "tr":
        text = _repair_turkish_sentence_boundaries(text)

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            stripped = _ensure_terminal_punctuation(stripped)
        lines.append(stripped)

    return "\n".join(lines).strip()


def _repair_dialogue_quote_fragments(text: str) -> str:
    """Repair Gemini's common dialogue artifact: Name," First." Second," dedi."""
    if not text:
        return text

    speech_tags = (
        "dedi",
        "diye sordu",
        "diye yan\u0131tlad\u0131",
        "diye cevap verdi",
        "diye kar\u015f\u0131l\u0131k verdi",
        "diye ekledi",
        "diye seslendi",
        "diye f\u0131s\u0131ldad\u0131",
        "said",
        "asked",
        "replied",
        "answered",
        "added",
        "fragte",
        "sagte",
        "antwortete",
        "\u0441\u043a\u0430\u0437\u0430\u043b",
        "\u0441\u043a\u0430\u0437\u0430\u043b\u0430",
        "\u0441\u043f\u0440\u043e\u0441\u0438\u043b",
        "\u0441\u043f\u0440\u043e\u0441\u0438\u043b\u0430",
    )
    tag_pattern = "|".join(re.escape(tag) for tag in speech_tags)

    def merge_split_quote(match: re.Match) -> str:
        first = match.group("first").strip()
        second = match.group("second").strip()
        tag = match.group("tag").strip()
        return f', "{first}. {second}," {tag}'

    text = re.sub(
        rf',\s*"\s*(?P<first>[^"\n]{{2,220}}?)\."\s+'
        rf'(?P<second>[^"\n]{{2,220}}?),"\s*(?P<tag>{tag_pattern})',
        merge_split_quote,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r',\s*"\s*(?=[A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc\u00c4\u00d6\u00dc\u0410-\u042f\u0401])', ', "', text)
    return text


def _clean_straight_quote_spacing(text: str) -> str:
    result = []
    inside_quote = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            if inside_quote:
                while result and result[-1] in {" ", "\t"}:
                    result.pop()
                result.append(char)
                inside_quote = False
                if i + 1 < len(text) and text[i + 1].isalnum():
                    result.append(" ")
            else:
                result.append(char)
                inside_quote = True
                i += 1
                while i < len(text) and text[i] in {" ", "\t"}:
                    i += 1
                continue
        else:
            result.append(char)
        i += 1
    return "".join(result)


def _repair_turkish_sentence_boundaries(text: str) -> str:
    turkish_letters = (
        "A-Za-z"
        "\\u00c7\\u011e\\u0130\\u00d6\\u015e\\u00dc"
        "\\u00e7\\u011f\\u0131\\u00f6\\u015f\\u00fc"
    )
    upper = "A-Z\\u00c7\\u011e\\u0130\\u00d6\\u015e\\u00dc"
    lower = "a-z\\u00e7\\u011f\\u0131\\u00f6\\u015f\\u00fc"
    endings = (
        "\\u0131yordu|iyordu|uyordu|\\u00fcyordu|yordu|"
        "acakt\\u0131|ecekti|"
        "m\\u0131\\u015ft\\u0131|mi\\u015fti|mu\\u015ftu|m\\u00fc\\u015ft\\u00fc|"
        "d\\u0131|di|du|d\\u00fc|t\\u0131|ti|tu|t\\u00fc"
    )
    pattern = re.compile(
        rf"\b(?P<verb>[{turkish_letters}'\u2019]+(?:{endings}))\s+"
        rf"(?P<next>[{upper}][{turkish_letters}'\u2019]*(?=(?:\s*,|\s+[{upper}]|\s+[{lower}])))"
    )
    speech_verbs = {
        "dedi",
        "sordu",
        "yan\u0131tlad\u0131",
        "cevaplad\u0131",
        "f\u0131s\u0131ldad\u0131",
        "ba\u011f\u0131rd\u0131",
        "ekledi",
        "seslendi",
    }

    def replace(match: re.Match) -> str:
        verb = match.group("verb")
        context = text[max(0, match.start() - 16):match.start()].lower()
        if verb.lower() in speech_verbs or "diye " in context:
            return match.group(0)
        return f"{verb}. {match.group('next')}"

    return pattern.sub(replace, text)


def _ensure_terminal_punctuation(line: str) -> str:
    terminal = ".!?"
    closing = "\"'\u201d\u2019\u00bb)"
    if line[-1] in terminal or line[-1] == "\u2026":
        return line
    if line[-1] in closing:
        before = line[:-1].rstrip()
        if before and (before[-1] in terminal or before[-1] == "\u2026"):
            return line
        return f"{before}.{line[-1]}"
    return f"{line}."


def generate_short_story(
    target_lang: str,
    support_lang: str,
    cefr_level: str,
    theme: str,
    length_label: str,
    style: str,
    variation_id: str = "",
    learner_profile: dict | None = None,
) -> dict:
    """Generate a CEFR-appropriate short story with learning scaffolding."""
    if not gemini.is_ready():
        raise StoryError("Stories need the Gemini API key. Add GEMINI_API_KEY to .env and restart Ivy.")

    target_name = LANGUAGES.get(target_lang, target_lang)
    support_name = LANGUAGES.get(support_lang, support_lang)
    theme = (theme or "daily life").strip()
    length_label = (length_label or "short").strip().lower()
    style = style if style in STYLES else "neutral"
    cefr_level = (cefr_level or "A2").strip().upper()
    variation_id = (variation_id or str(time.time_ns())).strip()

    length_guidance = {
        "short": "90 to 140 words",
        "medium": "140 to 220 words",
        "long": "220 to 320 words",
    }.get(length_label, "90 to 140 words")

    personalization_block = ""
    if learner_profile:
        known = (learner_profile.get("known_words") or [])[:25]
        struggling = (learner_profile.get("struggling_words") or [])[:3]
        if known or struggling:
            personalization_block = "\n\nLearner profile, use carefully:"
            if known:
                known_list = ", ".join(
                    w.get("base_form") or w.get("word") or ""
                    for w in known
                    if (w.get("base_form") or w.get("word"))
                )
                if known_list:
                    personalization_block += (
                        f"\n- Familiar {target_name} words: {known_list}."
                        "\n  Weave several of these into the story naturally so it feels calibrated to the learner."
                        "\n  Aim for 6-8 appearances across this list when it fits, but never force awkward wording."
                    )
            if struggling:
                struggling_list = ", ".join(
                    w.get("base_form") or w.get("word") or ""
                    for w in struggling
                    if (w.get("base_form") or w.get("word"))
                )
                if struggling_list:
                    personalization_block += (
                        f"\n- Stretch words this learner has struggled with: {struggling_list}."
                        "\n  Include 1-2 of these in clear, supportive context and include them in focus_vocabulary."
                    )
            personalization_block += "\n- The story must still read naturally. Coherence beats vocabulary coverage."

    prompt = f"""You are creating a CEFR-graded reading passage for language learners.

Return valid JSON only with this exact schema:
{{
  "title": "string",
  "story_text": "string",
  "summary": "2-3 sentence summary in {support_name}",
  "comprehension_questions": [
    {{"question": "string in {support_name}", "answer": "short string in {support_name}"}}
  ],
  "focus_vocabulary": [
    {{"word": "string in {target_name}", "meaning": "short meaning in {support_name}"}}
  ]
}}

Requirements:
- Write the story in {target_name}.
- CEFR level: {cefr_level}.
- Theme: {theme}.
- Variation seed: {variation_id}.
- Tone/register: {style}.
- Length: about {length_guidance}.
- Use natural but level-appropriate language.
- Keep the plot simple and memorable.
- Create a NEW story every time, even if the theme and level are the same.
- Use different character names, setting, conflict, and ending from any likely previous story.
- Do not write a generic morning routine unless the theme explicitly requires it.
- Include exactly 3 comprehension questions.
- Include 5 to 7 focus vocabulary items that actually appear in the story.
- Do not include markdown, code fences, or commentary.
{personalization_block}

Punctuation rules, strict:
- Every sentence in story_text must end with a period, question mark, or exclamation mark.
- Never put a space before a comma, period, semicolon, colon, question mark, or exclamation mark.
- Always put exactly one space after a comma, period, semicolon, colon, question mark, or exclamation mark unless followed by a closing quote.
- Use standard double quotes ("...") for dialogue.
- Do not put spaces inside opening or closing quotes.
- If a dialogue quote has multiple sentences, keep them inside ONE pair of quotes:
  Correct: Elif Hanım, "Yenilik olmadan ilerleme olmaz. Kasabamızın potansiyelini göstermeliyiz," dedi.
  Incorrect: Elif Hanım," Yenilik olmadan ilerleme olmaz." Kasabamızın potansiyelini göstermeliyiz," dedi.
- For Turkish, German, Russian, and English, use standard punctuation conventions for the target language.
"""

    payload = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            reply = gemini.generate(prompt, temperature=0.8, max_tokens=1200)
            payload = gemini.extract_json_payload(reply)
            if isinstance(payload, dict):
                break
            payload = None
            last_error = RuntimeError("Gemini returned invalid JSON for story generation")
        except Exception as exc:
            last_error = exc
            if gemini.is_rate_limited(exc) or (not gemini.is_transient(exc) and attempt >= 1):
                break

        if attempt < 3:
            time.sleep(1.5 + (attempt * 1.5))

    if not payload:
        print(f"  [Stories] generation failed: {last_error}")
        raise StoryError(gemini.friendly_error(last_error or RuntimeError(), "write a story"))

    story_text = clean_story_punctuation((payload.get("story_text") or "").strip(), target_lang)
    if not story_text:
        raise StoryError("Ivy got an empty story back. Please try again.")

    result = {
        "title": (payload.get("title") or f"{cefr_level} {target_name} story").strip(),
        "story_text": story_text,
        "summary": (payload.get("summary") or "").strip(),
        "target_lang": target_lang,
        "support_lang": support_lang,
        "cefr_level": cefr_level,
        "theme": theme,
        "length_label": length_label,
        "style": style,
        "word_data": [],
        "comprehension_questions": payload.get("comprehension_questions") or [],
        "focus_vocabulary": payload.get("focus_vocabulary") or [],
        "personalized": bool(personalization_block),
    }
    return result
