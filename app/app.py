"""
Style-Aware Translator — Flask Backend (v3 - Hybrid Pipeline)

Architecture:
  1. opus-mt (local) — accurate base translation
  2. Gemini API (cloud) — intelligent style restyling
  3. BERT classifier (local) — tone analysis & style detection

Usage:
    pip install flask torch transformers sentencepiece google-genai
    python app/app.py --gemini_key YOUR_KEY
"""

from __future__ import annotations

import os
import sys
import json
import torch
import argparse
import time
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    pipeline,
    MarianMTModel,
    MarianTokenizer,
)
from database import (
    init_db,
    get_saved_story,
    get_story_audio,
    set_story_audio,
    get_story_narration,
    set_story_narration,
)
from auth_routes import auth_bp, get_current_user
from word_analysis import analyze_words

ROOT_DIR = Path(__file__).parent.parent


def load_local_env() -> None:
    """Load simple KEY=VALUE pairs from a local .env file if present."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret-change-me")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.register_blueprint(auth_bp)

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = ROOT_DIR
CLASSIFIER_MODEL_PATH = BASE_DIR / "models" / "style-classifier-final"

# ──────────────────────────────────────────────
# opus-mt models
# ──────────────────────────────────────────────
OPUS_MODELS = {
    ("en", "tr"): "Helsinki-NLP/opus-mt-tc-big-en-tr",
    ("tr", "en"): "Helsinki-NLP/opus-mt-tc-big-tr-en",
    ("en", "ru"): "Helsinki-NLP/opus-mt-en-ru",
    ("ru", "en"): "Helsinki-NLP/opus-mt-ru-en",
    ("en", "de"): "Helsinki-NLP/opus-mt-en-de",
    ("de", "en"): "Helsinki-NLP/opus-mt-de-en",
}

# ──────────────────────────────────────────────
# Globals
# ──────────────────────────────────────────────
opus_models = {}
classifier_pipe = None
gemini_client = None
device = None

STYLES = ["formal", "neutral", "casual"]
LANGUAGES = {
    "en": "English",
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
}

restyle_cache = {}
explain_cache = {}

TURKISH_FORMAL_COPULA_RE = re.compile(
    r"\b[\wçğıöşüÇĞİÖŞÜ]+(?:dır|dir|dur|dür|tır|tir|tur|tür)\b",
    re.IGNORECASE,
)
TURKISH_FORMAL_COPULA_STRIP_RE = re.compile(
    r"\b([\wçğıöşüÇĞİÖŞÜ]{3,}?)(?:dır|dir|dur|dür|tır|tir|tur|tür)\b",
    re.IGNORECASE,
)

GOOGLE_TTS_VOICE_STYLE = os.environ.get("GOOGLE_TTS_VOICE_STYLE", "Aoede").strip() or "Aoede"
GOOGLE_TTS_LANGUAGE_CODES = {
    "tr": "tr-TR",
    "en": "en-US",
    "de": "de-DE",
    "ru": "ru-RU",
}
TTS_BYTE_LIMIT = 3500
MARKED_TTS_BYTE_LIMIT = 4600
MARKED_TTS_SYNC_VERSION = 2
STORY_SENTENCE_SPLIT_RE = r"(?<=[.!?\u3002\uff01\uff1f])\s+"
STORY_MARK_TOKEN_RE = re.compile(r"[^\W_]+(?:['\u2019-][^\W_]+)*", re.UNICODE)


def has_turkish_formal_copula(text: str) -> bool:
    return bool(TURKISH_FORMAL_COPULA_RE.search(text or ""))


def strip_turkish_formal_copula(text: str) -> str:
    return TURKISH_FORMAL_COPULA_STRIP_RE.sub(r"\1", text or "")


def revise_turkish_casual_output(source_text: str, candidate: str) -> str:
    """One-pass cleanup for casual Turkish outputs that still sound written."""
    if not has_turkish_formal_copula(candidate):
        return candidate

    if gemini_client is None:
        return strip_turkish_formal_copula(candidate)

    prompt = f"""Rewrite this Turkish sentence so it sounds like natural casual spoken Turkish.

Hard rules:
- Do NOT use the formal/written copula suffixes -dır, -dir, -dur, -dür, -tır, -tir, -tur, or -tür.
- For nominal sentences like "X is Y", drop the copula suffix or use a conversational phrasing.
- Keep the same meaning. Do not add slang unless it is natural.
- Output ONLY the revised Turkish sentence.

Original source meaning:
{source_text}

Turkish sentence to fix:
{candidate}"""

    try:
        from google.genai import types

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=256,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        result = (response.text or "").strip()
        for q in ['"', "'", "\u201c", "\u201d"]:
            if result.startswith(q) and result.endswith(q):
                result = result[1:-1].strip()
        if result and not has_turkish_formal_copula(result):
            return result
    except Exception as e:
        print(f"  Turkish casual cleanup error: {e}")

    return strip_turkish_formal_copula(candidate)


def load_models(gemini_key: str):
    """Load all models."""
    global classifier_pipe, gemini_client, device

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    # ── opus-mt translation models ──
    print("\nLoading opus-mt translation models...")
    for (src, tgt), model_name in OPUS_MODELS.items():
        print(f"  Loading {src} -> {tgt}: {model_name}...")
        try:
            tok = MarianTokenizer.from_pretrained(model_name)
            mdl = MarianMTModel.from_pretrained(model_name).to(device)
            mdl.eval()
            opus_models[(src, tgt)] = (mdl, tok)
            print(f"    Loaded!")
        except Exception as e:
            print(f"    FAILED: {e}")

    print(f"  Translation models loaded: {len(opus_models)}/6")

    # ── Gemini for style restyling ──
    print(f"\nSetting up Gemini API...")
    if gemini_key:
        try:
            from google import genai
            gemini_client = genai.Client(api_key=gemini_key)
            from google.genai import types
            test = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Say OK",
                config=types.GenerateContentConfig(
                    max_output_tokens=5,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            print(f"  Gemini connected! Test: {(test.text or 'OK').strip()}")
        except Exception as e:
            print(f"  Gemini setup failed: {e}")
            gemini_client = None
    else:
        print("  No Gemini key. Run with: python app/app.py --gemini_key YOUR_KEY")

    # ── Style classifier ──
    print(f"\nLoading style classifier...")
    if CLASSIFIER_MODEL_PATH.exists():
        classifier_pipe = pipeline(
            "text-classification",
            model=str(CLASSIFIER_MODEL_PATH),
            device=0 if device == "cuda" else -1,
            top_k=3,
        )
        print("  Classifier loaded!")
    else:
        print(f"  Classifier not found at {CLASSIFIER_MODEL_PATH}")


# ──────────────────────────────────────────────
# Stage 1: Translation (opus-mt)
# ──────────────────────────────────────────────
def opus_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Accurate translation using opus-mt. Chains through English if no direct model."""
    if source_lang == target_lang:
        return text

    key = (source_lang, target_lang)

    # Direct model exists
    if key in opus_models:
        model, tokenizer = opus_models[key]
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_length=512, num_beams=5, early_stopping=True, length_penalty=1.0)
        return tokenizer.decode(outputs[0], skip_special_tokens=True)

    # No direct model — chain through English
    if source_lang != "en" and target_lang != "en":
        if (source_lang, "en") in opus_models and ("en", target_lang) in opus_models:
            english = opus_translate(text, source_lang, "en")
            return opus_translate(english, "en", target_lang)

    return f"[No model for {source_lang} to {target_lang}]"

# ──────────────────────────────────────────────
# Stage 2: Style restyling (Gemini)
# ──────────────────────────────────────────────
def gemini_restyle(text: str, language: str, style: str) -> str:
    """Restyle translated text using Gemini API."""
    if gemini_client is None or style == "neutral":
        return text

    cache_key = f"{text}|{language}|{style}"
    if cache_key in restyle_cache:
        return restyle_cache[cache_key]

    if len(text.split()) < 3:
        return text

    lang_name = LANGUAGES.get(language, language)

    style_instructions = {
        "formal": f"""Restyle this {lang_name} text to sound formal and polite. Follow these rules strictly:

    For Turkish:
    - ALWAYS conjugate verbs with "siz" form (-siniz, -iniz, -nız). Example: "gel" becomes "geliniz" or "lütfen gelin"
    - Use "siz" instead of "sen" in every case without exception
    - Add polite phrases where natural: "lütfen", "rica ederim"
    - Use longer, more complete sentence structures

    For Russian:
    - ALWAYS use "Вы" instead of "ты" — conjugate accordingly
    - Use polite constructions: "Не могли бы Вы...", "Будьте добры..."
    - Do NOT over-elaborate or add extra meaning. Keep the same length and meaning as the original
    - Do NOT add dramatic flourishes — just make it polite

    For German:
    - ALWAYS use "Sie" instead of "du" — conjugate accordingly
    - Use "könnten Sie", "würden Sie" for requests
    - Use "bitte" where natural

    For English:
    - Use complete sentences, no contractions
    - Use "would you", "could you", "please"

    CRITICAL: Keep the EXACT same meaning. Do not add information that was not in the original.
    Output ONLY the restyled {lang_name} text — nothing else.""",

        "casual": f"""Restyle this {lang_name} text to sound casual and friendly, like texting a close friend. Follow these rules strictly:

    For Turkish:
    - ALWAYS use "sen" form — conjugate accordingly (-sin, -n)
    - Do NOT use "ya" by default. Use it at most once, and only when the source clearly needs a soft emotional particle
    - Prefer natural everyday Turkish: simple wording, "sen" forms, "bi'" only when it sounds natural
    - Avoid filler particles such as "ya", "hadi ya", "lan", "abi" unless they are clearly required by context
    - Shorten words where natural: "bir" → "bi'", "şey" can be dropped
    - Keep it short and punchy

    For Russian:
    - ALWAYS use "ты" instead of "Вы"
    - Use casual expressions: "давай", "ну", "чё", "короче"
    - Can use slang and informal grammar
    - Keep sentences short

    For German:
    - ALWAYS use "du" instead of "Sie" — conjugate accordingly
    - Use particles: "mal", "halt", "echt", "voll"
    - Contractions welcome: "hab" instead of "habe"
    - Informal word order is fine

    For English:
    - Use contractions: "wanna", "gonna", "lemme"
    - Use slang and casual expressions
    - Keep it short

    CRITICAL: Keep the EXACT same meaning. Do not add information that was not in the original.
    Output ONLY the restyled {lang_name} text — nothing else.""",
    }

    prompt = f"""{style_instructions[style]}

Text to restyle: {text}"""

    try:
        from google.genai import types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        result = (response.text or "").strip()

        # Remove quotes if wrapped
        for q in ['"', "'", "\u201c", "\u201d"]:
            if result.startswith(q) and result.endswith(q):
                result = result[1:-1].strip()

        if len(result) < 2:
            result = text

        restyle_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"  Gemini restyle error: {e}")
        return text


# ──────────────────────────────────────────────
# Full pipeline
# ──────────────────────────────────────────────

def gemini_translate_styled(text: str, source_lang: str, target_lang: str, style: str) -> str:
    """Translate and style in one step using Gemini."""
    cache_key = f"{text}|{source_lang}|{target_lang}|{style}"
    if cache_key in restyle_cache:
        return restyle_cache[cache_key]

    src_name = LANGUAGES.get(source_lang, source_lang)
    tgt_name = LANGUAGES.get(target_lang, target_lang)

    style_rules = {
        "formal": {
            "Turkish": "Use 'siz' conjugation (-siniz, -iniz, -nız). 'gel' becomes 'gelin'. Do NOT add 'lütfen' unless 'please' was in the original. Remove any profanity or vulgar language entirely — replace with clean, polite equivalents. The tone should be respectful and measured.",
            "Russian": "Use 'Вы' conjugation, never 'ты'. Remove any profanity entirely — replace with clean equivalents. Do NOT over-elaborate. Keep the same length and meaning. Use 'счёт' not 'чек' for restaurant bills.",
            "German": "Use 'Sie' conjugation, never 'du'. Use 'könnten Sie', 'würden Sie' for requests. Use 'Beruhigen Sie sich' not 'Sie könnten sich entspannen' for commands. Remove any profanity entirely.",
            "English": "Use complete sentences, no contractions. Remove profanity — replace with clean equivalents.",
        },
        "casual": {
            "Turkish": (
                "Rewrite as spoken, everyday Turkish, like a friend talking. This must be clearly more casual than a neutral translation. "
                "You may restructure the sentence, split one polished sentence into short conversational fragments, use question form for requests, "
                "drop unnecessary subjects, and use natural contractions such as 'bi' for 'bir' when it fits. Always use 'sen' forms (-sin, -n) when addressing someone; never use 'siz'. "
                "Never use the formal written copula suffixes -dir/-dır/-dur/-dür/-tir/-tır/-tur/-tür; for sentences like 'X is Y', drop the suffix or use a conversational phrasing. "
                "For abstract judgments, avoid written phrases like 'kesinlikle kabul edilemez' when a spoken phrase works; prefer natural options like 'Bu gerçekten olmaz' or 'Bu hiç kabul edilecek şey değil'. "
                "Replace written/formal verbs with spoken equivalents: 'görüşmek' -> 'konuşmak', 'talep etmek/rica etmek' -> a simpler direct phrasing. "
                "Do NOT add 'ya' by default. Use sentence-final 'ya' at most once only when it genuinely sounds natural; never for simple greetings, never at the start, and never as 'hadi ya'. "
                "Avoid forced slang. 'lan' is only for very close male friends and should usually be avoided. The result should sound like natural chat, not textbook Turkish. "
                "Examples: 'Life is beautiful.' -> 'Hayat güzel.'; 'He is a student.' -> 'O öğrenci.'; 'That is absolutely unacceptable.' -> 'Bu gerçekten olmaz.'"
            ),
            "Russian": (
                "Rewrite as spoken Russian, clearly more casual than neutral. Use 'ты', never 'Вы'. You may restructure, shorten, and use fragments. "
                "Use casual particles such as 'ну', 'давай', or 'короче' sparingly, max once. Do not stack slang. Use 'счёт' not 'чек' for restaurant bills."
            ),
            "German": (
                "Rewrite as spoken German, clearly more casual than neutral. Use 'du', never 'Sie'. You may restructure and shorten. "
                "Use particles such as 'mal', 'halt', 'doch', or 'echt' naturally, not stacked. Contractions are allowed: 'hab' for 'habe', 'is' for 'ist'. "
                "Avoid 'echt jetzt' unless the source is clearly sarcastic."
            ),
            "English": (
                "Rewrite as spoken English, clearly more casual than neutral. You may restructure, shorten, use contractions, and use fragments. "
                "Use natural chat phrasing such as 'wanna', 'gonna', 'lemme', or 'I'd' only where it fits."
            ),
        },

    }

    rules = style_rules.get(style, {}).get(tgt_name, "")

    if style == "casual":
        meta_rules = f"""CRITICAL RULES:
    - Preserve the core meaning and intent, but make the register clearly casual
    - You MAY restructure freely: change sentence form, split long sentences, use fragments, and drop filler words
    - You MAY add one natural casual marker if it fits, but do not add new facts or new requests
    - Do not make the result rude unless the source is rude
    - Output ONLY the {tgt_name} translation — no quotes, no explanation"""
    else:
        meta_rules = f"""CRITICAL RULES:
    - Translate accurately — same meaning, nothing added, nothing removed
    - Do NOT add extra words, phrases, or politeness markers that are not in the original
    - Do NOT make the translation longer than necessary
    - Only change register: pronouns, verb conjugation, and word choice
    - Output ONLY the {tgt_name} translation — no quotes, no explanation"""

    prompt = f"""Translate this {src_name} text into {tgt_name} with a {style} tone.

    {rules}

    {meta_rules}

    Text: {text}"""

    try:
        from google.genai import types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        result = (response.text or "").strip()
        raw_result = result
        for q in ['"', "'", "\u201c", "\u201d"]:
            if result.startswith(q) and result.endswith(q):
                result = result[1:-1].strip()

        if target_lang == "tr" and style == "casual":
            result = revise_turkish_casual_output(text, result)

        if result != raw_result:
            print(f"  [Gemini] {style} {tgt_name}: '{text}' -> '{raw_result}' -> cleaned '{result}'")
        else:
            print(f"  [Gemini] {style} {tgt_name}: '{text}' -> '{result}'")

        if len(result) < 2:
            result = opus_translate(text, source_lang, target_lang)

        restyle_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"  Gemini translate error: {e}")
        return opus_translate(text, source_lang, target_lang)

def gemini_restyle_direct(text: str, language: str, style: str) -> str:
    """Restyle text within the same language."""
    if gemini_client is None or style == "neutral":
        return text

    cache_key = f"restyle|{text}|{language}|{style}"
    if cache_key in restyle_cache:
        return restyle_cache[cache_key]

    lang_name = LANGUAGES.get(language, language)
    extra_rules = ""
    if language == "tr" and style == "casual":
        extra_rules = (
            "- Turkish casual: make it sound spoken, not written. You may split polished sentences into short fragments, "
            "use 'sen' forms, and use 'bi' for 'bir' when natural. Do NOT add \"ya\" by default; use it at most once only when it truly fits.\n"
            "- Do not use formal written copula suffixes (-dir/-dır/-dur/-dür/-tir/-tır/-tur/-tür). For 'X is Y' sentences, drop the suffix or use a conversational phrasing.\n"
            "- For abstract judgments, avoid stiff phrases like 'kesinlikle kabul edilemez'; use spoken phrasing like 'Bu gerçekten olmaz' or 'Bu hiç kabul edilecek şey değil'.\n"
        )
    elif language == "tr" and style == "formal":
        extra_rules = "- Turkish formal: use respectful written Turkish. Use 'siz' forms when addressing someone; avoid slang and chatty particles.\n"

    prompt = f"""Restyle this {lang_name} text to sound {style}. Keep the SAME language ({lang_name}) — do NOT translate.

Rules for {style}:
- formal: use polite forms, complete sentences, sophisticated vocabulary, no slang
- casual: use spoken language, natural shortening, optional fragments, and a clearly friendlier register than neutral
{extra_rules}

Keep the exact same meaning. Change the tone/register, and for casual you may restructure lightly so it sounds genuinely spoken.
Output ONLY the restyled {lang_name} text.

Text: {text}"""

    try:
        from google.genai import types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3, max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        result = (response.text or "").strip()
        for q in ['"', "'", "\u201c", "\u201d"]:
            if result.startswith(q) and result.endswith(q):
                result = result[1:-1].strip()
        if language == "tr" and style == "casual":
            result = revise_turkish_casual_output(text, result)
        if len(result) < 2:
            result = text
        restyle_cache[cache_key] = result
        return result
    except Exception as e:
        print(f"  Restyle error: {e}")
        return text

def translate_with_style(text: str, source_lang: str, target_lang: str, style: str) -> dict:
    """
    Hybrid pipeline:
    - Same language: Gemini restyles directly (no translation needed)
    - Neutral: opus-mt only
    - Formal/Casual: opus-mt translate + Gemini style
    """
    # Same language = restyle mode
    if source_lang == target_lang:
        if style == "neutral" or gemini_client is None:
            return {"base_translation": text, "styled_translation": text}
        styled = gemini_restyle_direct(text, source_lang, style)
        return {"base_translation": text, "styled_translation": styled}

    # Different language
    base_translation = opus_translate(text, source_lang, target_lang)

    if style == "neutral" or gemini_client is None:
        return {"base_translation": base_translation, "styled_translation": base_translation}

    styled_translation = gemini_translate_styled(text, source_lang, target_lang, style)
    return {"base_translation": base_translation, "styled_translation": styled_translation}


def opus_translate_only(text: str, source_lang: str, target_lang: str) -> str:
    """Pure helper for evaluation scripts: opus-mt baseline only."""
    return opus_translate(text, source_lang, target_lang)


def translate_pipeline(text: str, source_lang: str, target_lang: str, style: str = "neutral") -> str:
    """Pure helper for evaluation scripts: full translation pipeline output."""
    return translate_with_style(text, source_lang, target_lang, style)["styled_translation"]

# ──────────────────────────────────────────────
# Style detection
# ──────────────────────────────────────────────
def detect_style(text: str) -> dict:
    """Classify style using our trained BERT classifier."""
    if classifier_pipe is None:
        return {"formal": 0.33, "casual": 0.33, "neutral": 0.34}

    results = classifier_pipe(text[:512])
    scores = {}
    for item in results[0]:
        scores[item["label"]] = round(item["score"], 3)

    for s in STYLES:
        if s not in scores:
            scores[s] = 0.0

    return scores


def extract_json_payload(raw_text: str) -> dict | None:
    """Extract the first JSON object from a Gemini response."""
    if not raw_text:
        return None

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


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
    if gemini_client is None:
        raise RuntimeError("Gemini is not configured")

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

    try:
        from google.genai import types
    except Exception as exc:
        raise RuntimeError(f"Gemini story generation failed: {exc}") from exc

    payload = None
    last_error = None
    for attempt in range(4):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    max_output_tokens=1200,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            payload = extract_json_payload(response.text or "")
            if payload:
                break
            last_error = RuntimeError("Gemini returned invalid JSON for story generation")
        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()
            transient = any(token in error_text for token in ["503", "unavailable", "overload", "quota", "timeout"])
            if not transient and attempt >= 1:
                break

        time.sleep(1.5 + (attempt * 1.5))

    if not payload:
        raise RuntimeError(f"Gemini could not generate a story after several tries: {last_error}")

    story_text = clean_story_punctuation((payload.get("story_text") or "").strip(), target_lang)
    if not story_text:
        raise RuntimeError("Gemini returned an empty story")

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


def _utf8_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


def _split_long_token_for_tts(token: str) -> list[str]:
    chunks = []
    current = ""
    for char in token:
        candidate = current + char
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = char
    if current:
        chunks.append(current)
    return chunks


def _split_words_for_tts(text: str) -> list[str]:
    chunks = []
    current = ""
    for word in text.split():
        if _utf8_len(word) > TTS_BYTE_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_token_for_tts(word))
            continue

        candidate = f"{current} {word}".strip() if current else word
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word

    if current:
        chunks.append(current)
    return chunks


def _split_oversized_tts_sentence(sentence: str) -> list[str]:
    chunks = []
    current = ""
    parts = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]

    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if _utf8_len(part) > TTS_BYTE_LIMIT:
            chunks.extend(_split_words_for_tts(part))
            current = ""
        else:
            current = part

    if current:
        chunks.append(current)
    return chunks


def _split_text_for_tts(text: str) -> list[str]:
    """Split text into chunks safely below the Google TTS byte limit."""
    text = (text or "").strip()
    if not text:
        return []

    sentences = [
        sentence.strip()
        for sentence in re.split(STORY_SENTENCE_SPLIT_RE, text)
        if sentence.strip()
    ]

    chunks = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if _utf8_len(sentence) > TTS_BYTE_LIMIT:
            chunks.extend(_split_oversized_tts_sentence(sentence))
            current = ""
        else:
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def synthesize_story_audio(provider: str, text: str, language: str) -> tuple[bytes, str]:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("No story text provided")

    provider = (provider or "").strip().lower()
    if provider != "google":
        raise RuntimeError("Unsupported TTS provider")

    try:
        from google.cloud import texttospeech
    except Exception as exc:
        raise RuntimeError("Google Cloud TTS is not installed. Run: pip install google-cloud-texttospeech") from exc

    language_code = GOOGLE_TTS_LANGUAGE_CODES.get(language, "en-US")
    voice_name = f"{language_code}-Chirp3-HD-{GOOGLE_TTS_VOICE_STYLE}"
    chunks = _split_text_for_tts(text)
    if not chunks:
        raise RuntimeError("No story text provided")

    try:
        client = texttospeech.TextToSpeechClient()
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )
        print(f"  [TTS] Total input: {_utf8_len(text)} bytes, {len(chunks)} chunk(s)")
        audio_parts = []
        for index, chunk in enumerate(chunks, start=1):
            print(f"  [TTS] Synthesizing chunk {index}/{len(chunks)} ({_utf8_len(chunk)} bytes)")
            synthesis_input = texttospeech.SynthesisInput(text=chunk)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
            audio_parts.append(response.audio_content)
        return b"".join(audio_parts), "audio/mpeg"
    except Exception as exc:
        raise RuntimeError(f"Google Cloud TTS failed: {exc}") from exc


def _ssml_escape(text: str) -> str:
    """Escape XML-significant characters before embedding token text in SSML."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _normalize_story_mark_token(value: str) -> str:
    return re.sub(r"^[\W_]+|[\W_]+$", "", str(value or ""), flags=re.UNICODE).casefold()


def _is_pure_story_punct(value: str) -> bool:
    return not bool(STORY_MARK_TOKEN_RE.search(str(value or "")))


def _word_item_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("word") or "")
    return str(item or "")


def _word_item_base(item) -> str:
    if isinstance(item, dict):
        return str(item.get("base_form") or "")
    return ""


def _next_story_word_index(word_items: list, start: int, display_token: str) -> int:
    first_usable = -1
    target = _normalize_story_mark_token(display_token)
    for index in range(max(0, start), len(word_items)):
        item = word_items[index]
        item_word = _word_item_text(item)
        if _is_pure_story_punct(item_word):
            continue
        if first_usable < 0:
            first_usable = index
        normalized_word = _normalize_story_mark_token(item_word)
        normalized_base = _normalize_story_mark_token(_word_item_base(item))
        if target and (normalized_word == target or normalized_base == target):
            return index
        if first_usable >= 0 and index - first_usable >= 4:
            break
    return first_usable


def _build_marked_story_ssml_from_text(story_text: str, word_items: list) -> tuple[str, int]:
    """
    Build SSML from the original story text, preserving punctuation and spacing.

    The matching mirrors the browser's renderWordsFromSource() logic so mark
    names line up with .word-span[data-index] instead of plain DOM position.
    """
    parts = ["<speak>"]
    last_offset = 0
    data_cursor = 0
    mark_count = 0

    for match in STORY_MARK_TOKEN_RE.finditer(story_text or ""):
        parts.append(_ssml_escape((story_text or "")[last_offset:match.start()]))
        token = match.group(0)
        data_index = _next_story_word_index(word_items, data_cursor, token)
        if data_index >= 0:
            parts.append(f'<mark name="w{data_index}"/>')
            parts.append(_ssml_escape(token))
            data_cursor = data_index + 1
            mark_count += 1
        else:
            parts.append(_ssml_escape(token))
        last_offset = match.end()

    parts.append(_ssml_escape((story_text or "")[last_offset:]))
    parts.append("</speak>")
    return "".join(parts), mark_count


def _build_marked_story_ssml_from_words(words: list[str]) -> tuple[str, int]:
    parts = ["<speak>"]
    mark_count = 0
    for index, word in enumerate(words):
        token = str(word or "").strip()
        parts.append(f'<mark name="w{index}"/>')
        mark_count += 1
        if token:
            parts.append(_ssml_escape(token))
            parts.append(" ")
    parts.append("</speak>")
    return "".join(parts), mark_count


def _ssml_mark_timepoint_value(texttospeech):
    """Return the SSML_MARK enum value across google-cloud-tts versions."""
    request_cls = texttospeech.SynthesizeSpeechRequest
    timepoint_type = getattr(request_cls, "TimepointType", None)
    if timepoint_type is not None and hasattr(timepoint_type, "SSML_MARK"):
        return timepoint_type.SSML_MARK
    if hasattr(request_cls, "SSML_MARK"):
        return request_cls.SSML_MARK
    module_type = getattr(texttospeech, "TimepointType", None)
    if module_type is not None and hasattr(module_type, "SSML_MARK"):
        return module_type.SSML_MARK
    return 1


def _timepoints_are_current(timepoints: list[dict]) -> bool:
    return bool(timepoints) and all(
        isinstance(item, dict) and item.get("sync_version") == MARKED_TTS_SYNC_VERSION
        for item in timepoints
    )


def synthesize_marked_story_audio(word_items: list, language: str, story_text: str = "") -> tuple[bytes, list[dict]]:
    """
    Synthesize narration with SSML mark timepoints.

    The words list must come from story word_data in display order, so returned
    timepoint indexes line up with .word-span[data-index] in the story reader.
    """
    word_strings = [_word_item_text(item) for item in (word_items or [])]
    if not word_strings:
        raise RuntimeError("No words supplied for word-synced narration")

    ssml = ""
    mark_count = 0
    if (story_text or "").strip():
        ssml, mark_count = _build_marked_story_ssml_from_text(story_text, word_items or [])
    if not mark_count:
        ssml, mark_count = _build_marked_story_ssml_from_words(word_strings)

    ssml_bytes = _utf8_len(ssml)
    if ssml_bytes > MARKED_TTS_BYTE_LIMIT:
        raise RuntimeError(
            "This story is too long for word-synced narration right now. "
            "Turn off Sync words to play regular narration."
        )

    try:
        from google.cloud import texttospeech_v1beta1 as texttospeech
    except Exception:
        try:
            from google.cloud import texttospeech
        except Exception as exc:
            raise RuntimeError("Google Cloud TTS is not installed. Run: pip install google-cloud-texttospeech") from exc

    language_code = GOOGLE_TTS_LANGUAGE_CODES.get(language, "en-US")

    try:
        client = texttospeech.TextToSpeechClient()
        # Chirp3 HD ignores unsupported SSML tags such as <mark>, so word sync
        # uses the API's default non-Chirp voice for the language.
        request_payload = {
            "input": texttospeech.SynthesisInput(ssml=ssml),
            "voice": texttospeech.VoiceSelectionParams(language_code=language_code),
            "audio_config": texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
            ),
            "enable_time_pointing": [_ssml_mark_timepoint_value(texttospeech)],
        }
        print(f"  [TTS sync] Synthesizing marked narration ({ssml_bytes} SSML bytes, {len(word_strings)} marks)")
        response = client.synthesize_speech(request=request_payload)
    except Exception as exc:
        error_text = str(exc)
        if "enable_time_pointing" in error_text:
            raise RuntimeError(
                "Google Cloud TTS word sync is not supported by the installed client. "
                "Upgrade google-cloud-texttospeech or turn off Sync words for regular narration."
            ) from exc
        raise RuntimeError(f"Google Cloud TTS (word sync) failed: {exc}") from exc

    timepoints = []
    for timepoint in getattr(response, "timepoints", []) or []:
        mark_name = getattr(timepoint, "mark_name", "") or ""
        if not mark_name.startswith("w"):
            continue
        try:
            index = int(mark_name[1:])
        except ValueError:
            continue
        if index < 0 or index >= len(word_strings):
            continue
        timepoints.append({
            "index": index,
            "time": float(timepoint.time_seconds),
            "sync_version": MARKED_TTS_SYNC_VERSION,
        })
    timepoints.sort(key=lambda item: item["time"])
    if not timepoints:
        raise RuntimeError("Google Cloud TTS did not return word-sync timing data")
    return response.audio_content, timepoints


def audio_mpeg_response(audio: bytes) -> Response:
    """Return MP3 bytes with basic byte-range support for browser seeking."""
    total = len(audio)
    range_header = request.headers.get("Range", "")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/mpeg",
    }

    if range_header.startswith("bytes="):
        range_value = range_header.split("=", 1)[1].split(",", 1)[0].strip()
        start_text, _, end_text = range_value.partition("-")
        try:
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else total - 1
            else:
                suffix_length = int(end_text)
                start = max(total - suffix_length, 0)
                end = total - 1
            if start < 0 or end < start or start >= total:
                return Response(status=416, headers={**headers, "Content-Range": f"bytes */{total}"})
            end = min(end, total - 1)
            chunk = audio[start:end + 1]
            headers.update({
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(len(chunk)),
            })
            return Response(chunk, status=206, headers=headers)
        except (TypeError, ValueError):
            pass

    headers["Content-Length"] = str(total)
    return Response(audio, headers=headers)


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/sets")
def sets_page():
    return render_template("sets.html")

@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.json
    text = data.get("text", "").strip()
    source_lang = data.get("source_lang", "en")
    target_lang = data.get("target_lang", "tr")
    style = data.get("style", "neutral")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    result = translate_with_style(text, source_lang, target_lang, style)
    style_scores = detect_style(result["styled_translation"])

    # Analyze words in the translation
    word_data = []
    if target_lang != source_lang:
        word_data = analyze_words(result["styled_translation"], target_lang, gemini_client, LANGUAGES)

    return jsonify({
        "translation": result["styled_translation"],
        "base_translation": result["base_translation"],
        "style_scores": style_scores,
        "word_data": word_data,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "style": style,
    })


@app.route("/api/explain_sentence", methods=["POST"])
def api_explain_sentence():
    """Return a sentence-level grammar explanation for the translated output."""
    data = request.json or {}
    sentence = (data.get("sentence") or "").strip()
    target_lang = data.get("target_lang", "tr")
    support_lang = data.get("support_lang", "en")

    if not sentence:
        return jsonify({"error": "No sentence provided"}), 400
    if len(sentence.encode("utf-8")) > 6000:
        return jsonify({"error": "That sentence is too long to explain at once."}), 413
    if target_lang not in LANGUAGES or support_lang not in LANGUAGES:
        return jsonify({"error": "Unsupported language selection"}), 400
    if gemini_client is None:
        return jsonify({"error": "Explanation service is not configured."}), 503

    cache_key = f"{sentence}|{target_lang}|{support_lang}"
    if cache_key in explain_cache:
        return jsonify({"explanation": explain_cache[cache_key]})

    target_name = LANGUAGES[target_lang]
    support_name = LANGUAGES[support_lang]
    prompt = f"""You are a patient language tutor. Explain this {target_name} sentence to a {support_name}-speaking learner.

Sentence: "{sentence}"

Write your explanation in {support_name}.

Stay at the sentence level. Focus on:
- Why specific grammatical cases, tenses, or moods were chosen
- Word order rationale, especially where it differs from {support_name}
- Idiomatic phrases or constructions that are not transparent word-by-word
- Subtle register, formality, or politeness cues

Do NOT redefine individual word meanings. The learner already has word-level tooltips.
Do NOT translate the sentence again. They already have the translation.
Do NOT list every word. Pick the 3-5 most interesting structural features.

Format your response as 4-6 short bullet points, each starting with "- ".
Use **bold** for the {target_name} words or phrases you reference.
No preamble, no closing remarks, no markdown headers. Just the bullet points."""

    try:
        from google.genai import types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=600,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        explanation = (response.text or "").strip()
        if not explanation:
            return jsonify({"error": "Ivy returned an empty explanation. Try again."}), 503
        explain_cache[cache_key] = explanation
        return jsonify({"explanation": explanation})
    except Exception as exc:
        print(f"[explain_sentence] Gemini failed: {exc}")
        return jsonify({"error": f"Could not generate explanation: {exc}"}), 503


@app.route("/api/compare", methods=["POST"])
def api_compare():
    data = request.json
    text = data.get("text", "").strip()
    source_lang = data.get("source_lang", "en")
    target_lang = data.get("target_lang", "tr")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    results = {}
    for style in STYLES:
        result = translate_with_style(text, source_lang, target_lang, style)
        scores = detect_style(result["styled_translation"])
        word_data = analyze_words(result["styled_translation"], target_lang, gemini_client, LANGUAGES) if target_lang != source_lang else []
        results[style] = {
            "translation": result["styled_translation"],
            "base_translation": result["base_translation"],
            "style_scores": scores,
            "word_data": word_data,
        }

    input_style = detect_style(text)

    return jsonify({
        "results": results,
        "input_style": input_style,
        "source_lang": source_lang,
        "target_lang": target_lang,
    })


@app.route("/api/detect-style", methods=["POST"])
def api_detect_style():
    data = request.json
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "No text provided"}), 400

    scores = detect_style(text)
    dominant = max(scores, key=scores.get)

    return jsonify({
        "scores": scores,
        "dominant_style": dominant,
    })


@app.route("/api/stories/generate", methods=["POST"])
def api_generate_story():
    data = request.json or {}
    target_lang = data.get("target_lang", "tr")
    support_lang = data.get("support_lang", "en")
    cefr_level = data.get("cefr_level", "A2")
    theme = data.get("theme", "daily life")
    length_label = data.get("length_label", "short")
    style = data.get("style", "neutral")
    variation_id = data.get("variation_id", "")
    personalize = bool(data.get("personalize", False))

    if target_lang not in LANGUAGES or support_lang not in LANGUAGES:
        return jsonify({"error": "Unsupported language selection"}), 400

    learner_profile = None
    if personalize:
        user = get_current_user()
        if user:
            from database import get_user_known_words, get_user_struggling_words
            known = get_user_known_words(user["id"], target_lang, limit=25)
            struggling = get_user_struggling_words(user["id"], target_lang, limit=3)
            if known or struggling:
                learner_profile = {
                    "known_words": known,
                    "struggling_words": struggling,
                }

    try:
        story = generate_short_story(
            target_lang=target_lang,
            support_lang=support_lang,
            cefr_level=cefr_level,
            theme=theme,
            length_label=length_label,
            style=style,
            variation_id=variation_id,
            learner_profile=learner_profile,
        )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Story generation failed: {exc}"}), 500

    return jsonify(story)


@app.route("/api/stories/analyze", methods=["POST"])
def api_analyze_story():
    data = request.json or {}
    text = data.get("text", "").strip()
    target_lang = data.get("target_lang", "tr")

    if not text:
        return jsonify({"word_data": []})
    if target_lang not in LANGUAGES:
        return jsonify({"error": "Unsupported language selection"}), 400

    sentences = [
        chunk.strip()
        for chunk in re.split(STORY_SENTENCE_SPLIT_RE, text)
        if chunk.strip()
    ]

    word_data = []
    for sentence in sentences:
        try:
            word_data.extend(analyze_words(sentence, target_lang, gemini_client, LANGUAGES))
        except Exception as exc:
            print(f"[stories_analyze] sentence failed, continuing: {exc}")
            word_data.extend(
                {
                    "word": token,
                    "meaning": "",
                    "pos": "other",
                    "case": None,
                    "gender": None,
                    "base_form": token,
                    "difficulty": "",
                    "vulgar": False,
                }
                for token in sentence.split()
            )

    return jsonify({"word_data": word_data})


@app.route("/api/stories/tts", methods=["POST"])
def api_story_tts():
    data = request.json or {}
    provider = data.get("provider", "")
    text = data.get("text", "")
    language = data.get("language", "tr")
    story_id = data.get("story_id")

    if language not in LANGUAGES:
        return jsonify({"error": "Unsupported language selection"}), 400

    user = None
    saved_story = None
    parsed_story_id = None
    if story_id is not None:
        try:
            parsed_story_id = int(story_id)
        except (TypeError, ValueError):
            parsed_story_id = None
        if parsed_story_id:
            user = get_current_user()
            if user:
                saved_story = get_saved_story(user["id"], parsed_story_id)
                if saved_story:
                    cached = get_story_audio(user["id"], parsed_story_id)
                    if cached:
                        return audio_mpeg_response(cached)

    try:
        audio, content_type = synthesize_story_audio(provider, text, language)
    except RuntimeError as exc:
        status = 503 if "failed" in str(exc).lower() else 400
        return jsonify({"error": str(exc)}), status

    if user and saved_story and parsed_story_id:
        saved_text = (saved_story.get("story_text") or "").strip()
        if saved_text == (text or "").strip():
            try:
                set_story_audio(user["id"], parsed_story_id, audio)
            except Exception as exc:
                print(f"[tts] persistence failed (non-fatal): {exc}")

    return Response(audio, mimetype=content_type)


@app.route("/api/stories/tts-marked", methods=["POST"])
def api_story_tts_marked():
    """Return one MP3 plus per-word timing data for karaoke-style story playback."""
    import base64

    data = request.json or {}
    language = data.get("language", "tr")
    story_id = data.get("story_id")
    story_text = data.get("story_text") or data.get("text") or ""
    word_data = data.get("word_data") if isinstance(data.get("word_data"), list) else []
    words = data.get("words")
    if not words and word_data:
        words = [item.get("word", "") if isinstance(item, dict) else "" for item in word_data]
    word_items = word_data if word_data else [str(word or "") for word in (words or [])]

    if language not in LANGUAGES:
        return jsonify({"error": "Unsupported language selection"}), 400
    if not isinstance(word_items, list) or not word_items:
        return jsonify({"error": "Words are required for word-synced narration"}), 400

    user = None
    saved_story = None
    parsed_story_id = None
    if story_id is not None:
        try:
            parsed_story_id = int(story_id)
        except (TypeError, ValueError):
            parsed_story_id = None
        if parsed_story_id:
            user = get_current_user()
            if user:
                saved_story = get_saved_story(user["id"], parsed_story_id)
                if saved_story:
                    cached = get_story_narration(user["id"], parsed_story_id)
                    if cached and _timepoints_are_current(cached["timepoints"]):
                        return jsonify({
                            "audio_b64": base64.b64encode(cached["audio_bytes"]).decode("ascii"),
                            "timepoints": cached["timepoints"],
                            "cached": True,
                        })
                    if not story_text:
                        story_text = saved_story.get("story_text") or ""

    try:
        audio, timepoints = synthesize_marked_story_audio(word_items, language, story_text)
    except RuntimeError as exc:
        status = 503 if "failed" in str(exc).lower() else 400
        return jsonify({"error": str(exc)}), status

    if user and saved_story and parsed_story_id:
        try:
            set_story_narration(user["id"], parsed_story_id, audio, timepoints)
        except Exception as exc:
            print(f"[tts-marked] persistence failed (non-fatal): {exc}")

    return jsonify({
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "timepoints": timepoints,
        "cached": False,
    })


@app.route("/api/stories/<int:story_id>/audio", methods=["GET"])
def api_get_story_audio(story_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    audio = get_story_audio(user["id"], story_id)
    if not audio:
        return jsonify({"error": "No audio for this story"}), 404

    return audio_mpeg_response(audio)


@app.route("/api/stories/<int:story_id>/audio", methods=["PUT"])
def api_put_story_audio(story_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    audio_bytes = request.get_data()
    if not audio_bytes:
        return jsonify({"error": "No audio data"}), 400
    if len(audio_bytes) > 50 * 1024 * 1024:
        return jsonify({"error": "Audio too large"}), 413

    ok = set_story_audio(user["id"], story_id, audio_bytes)
    if not ok:
        return jsonify({"error": "Story not found"}), 404

    return jsonify({"ok": True})


@app.route("/api/stories/<int:story_id>/narration", methods=["GET"])
def api_get_story_narration(story_id):
    """Return cached synced narration as JSON for saved stories."""
    import base64

    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    cached = get_story_narration(user["id"], story_id)
    if not cached or not _timepoints_are_current(cached["timepoints"]):
        return jsonify({"error": "No synced narration for this story"}), 404

    return jsonify({
        "audio_b64": base64.b64encode(cached["audio_bytes"]).decode("ascii"),
        "timepoints": cached["timepoints"],
        "cached": True,
    })


@app.route("/api/stories/<int:story_id>/narration", methods=["PUT"])
def api_put_story_narration(story_id):
    """Persist synced narration generated before the story was saved."""
    import base64
    import binascii

    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.json or {}
    audio_b64 = data.get("audio_b64", "")
    timepoints = data.get("timepoints")
    if not audio_b64 or not isinstance(timepoints, list) or not timepoints:
        return jsonify({"error": "Audio and timepoints are required"}), 400
    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "Invalid audio data"}), 400
    if len(audio_bytes) > 50 * 1024 * 1024:
        return jsonify({"error": "Audio too large"}), 413

    ok = set_story_narration(user["id"], story_id, audio_bytes, timepoints)
    if not ok:
        return jsonify({"error": "Story not found"}), 404

    return jsonify({"ok": True})


# ──────────────────────────────────────────────
# Start
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini_key", type=str,
                        default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key for style restyling")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    init_db()
    load_models(args.gemini_key)

    print(f"\n{'='*50}")
    print(f"  Style Translator v3 (Hybrid Pipeline)")
    print(f"  opus-mt: {len(opus_models)} translation pairs")
    print(f"  Gemini:  {'connected' if gemini_client else 'NOT connected'}")
    print(f"  Classifier: {'loaded' if classifier_pipe else 'NOT loaded'}")
    print(f"  http://localhost:{args.port}")
    print(f"{'='*50}\n")

    app.run(debug=False, host="0.0.0.0", port=args.port)
