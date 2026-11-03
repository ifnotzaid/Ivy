"""
translation.py - The translation pipeline and the tone classifier.

  1. opus-mt (local) gives an accurate base translation.
  2. Gemini rewrites it into the chosen register (formal / casual), or
     translates directly when opus-mt can't (single words it copies through).
  3. The fine-tuned BERT classifier scores how formal / neutral / casual a text sounds.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from pathlib import Path

import torch

import gemini

LANGUAGES = {
    "en": "English",
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
}
STYLES = ["formal", "neutral", "casual"]

OPUS_MODELS = {
    ("en", "tr"): "Helsinki-NLP/opus-mt-tc-big-en-tr",
    ("tr", "en"): "Helsinki-NLP/opus-mt-tc-big-tr-en",
    ("en", "ru"): "Helsinki-NLP/opus-mt-en-ru",
    ("ru", "en"): "Helsinki-NLP/opus-mt-ru-en",
    ("en", "de"): "Helsinki-NLP/opus-mt-en-de",
    ("de", "en"): "Helsinki-NLP/opus-mt-de-en",
}

# Inputs this short go straight to Gemini: opus-mt often copies single words
# through unchanged ("cool" -> "cool") or picks a rare sense.
SHORT_INPUT_WORDS = 3

opus_models: dict[tuple[str, str], tuple] = {}
classifier_pipe = None
device = "cpu"

# opus-mt runs on one GPU; Compare translates three styles at once, so take turns.
_opus_lock = threading.Lock()
_classifier_lock = threading.Lock()
_style_cache: dict[str, str] = {}


# ──────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────
def load_translation_models() -> None:
    global device
    from transformers import MarianMTModel, MarianTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    print("\nLoading opus-mt translation models...")
    for (src, tgt), model_name in OPUS_MODELS.items():
        print(f"  Loading {src} -> {tgt}: {model_name}...")
        try:
            tokenizer = MarianTokenizer.from_pretrained(model_name)
            model = MarianMTModel.from_pretrained(model_name).to(device)
            model.eval()
            opus_models[(src, tgt)] = (model, tokenizer)
            print("    Loaded!")
        except Exception as exc:
            print(f"    FAILED: {exc}")
    print(f"  Translation models loaded: {len(opus_models)}/{len(OPUS_MODELS)}")


def load_classifier(model_path: Path) -> None:
    global classifier_pipe
    from transformers import pipeline

    print("\nLoading style classifier...")
    if not model_path.exists():
        print(f"  Classifier not found at {model_path}")
        return
    classifier_pipe = pipeline(
        "text-classification",
        model=str(model_path),
        device=0 if device == "cuda" else -1,
        top_k=3,
    )
    print("  Classifier loaded!")


# ──────────────────────────────────────────────
# Stage 1: opus-mt
# ──────────────────────────────────────────────
@lru_cache(maxsize=1024)
def opus_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Translate with opus-mt, going through English when there is no direct model."""
    if source_lang == target_lang:
        return text

    key = (source_lang, target_lang)
    if key in opus_models:
        model, tokenizer = opus_models[key]
        with _opus_lock, torch.no_grad():
            inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
            outputs = model.generate(**inputs, max_length=512, num_beams=5, early_stopping=True)
        return tokenizer.decode(outputs[0], skip_special_tokens=True)

    if (source_lang, "en") in opus_models and ("en", target_lang) in opus_models:
        english = opus_translate(text, source_lang, "en")
        return opus_translate(english, "en", target_lang)

    raise ValueError(f"No translation model for {source_lang} -> {target_lang}")


def _normalize(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text or "", flags=re.UNICODE).strip().casefold()


def looks_untranslated(source: str, output: str) -> bool:
    """True when opus-mt handed back the input unchanged."""
    return bool(_normalize(source)) and _normalize(source) == _normalize(output)


# ──────────────────────────────────────────────
# Stage 2: Gemini register rules
# ──────────────────────────────────────────────
TURKISH_FORMAL_COPULA_RE = re.compile(
    r"\b[\wçğıöşüÇĞİÖŞÜ]+(?:dır|dir|dur|dür|tır|tir|tur|tür)\b",
    re.IGNORECASE,
)
TURKISH_FORMAL_COPULA_STRIP_RE = re.compile(
    r"\b([\wçğıöşüÇĞİÖŞÜ]{3,}?)(?:dır|dir|dur|dür|tır|tir|tur|tür)\b",
    re.IGNORECASE,
)

NEUTRAL_RULE = (
    "Use plain, everyday wording: neither formal nor slangy. "
    "If the text is a single word or short phrase, give its most common everyday translation "
    "in the sense a learner most likely means, as a single word or short phrase. No alternatives, no explanation."
)

STYLE_RULES = {
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

CASUAL_META_RULES = """CRITICAL RULES:
- Preserve the core meaning and intent, but make the register clearly casual
- You MAY restructure freely: change sentence form, split long sentences, use fragments, and drop filler words
- You MAY add one natural casual marker if it fits, but do not add new facts or new requests
- Do not make the result rude unless the source is rude
- Output ONLY the {lang} translation — no quotes, no explanation"""

STRICT_META_RULES = """CRITICAL RULES:
- Translate accurately — same meaning, nothing added, nothing removed
- Do NOT add extra words, phrases, or politeness markers that are not in the original
- Do NOT make the translation longer than necessary
- Only change register: pronouns, verb conjugation, and word choice
- Output ONLY the {lang} translation — no quotes, no explanation"""


def has_turkish_formal_copula(text: str) -> bool:
    return bool(TURKISH_FORMAL_COPULA_RE.search(text or ""))


def strip_turkish_formal_copula(text: str) -> str:
    return TURKISH_FORMAL_COPULA_STRIP_RE.sub(r"\1", text or "")


def revise_turkish_casual_output(source_text: str, candidate: str) -> str:
    """One extra pass for casual Turkish that still sounds written (-dır/-dir endings)."""
    if not has_turkish_formal_copula(candidate):
        return candidate
    if not gemini.is_ready():
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
        result = gemini.strip_wrapping_quotes(gemini.generate(prompt, temperature=0.2, max_tokens=256))
        if result and not has_turkish_formal_copula(result):
            return result
    except Exception as exc:
        print(f"  Turkish casual cleanup error: {str(exc)[:200]}")
    return strip_turkish_formal_copula(candidate)


def gemini_translate_styled(text: str, source_lang: str, target_lang: str, style: str) -> str:
    """Translate and apply the register in one Gemini call. Falls back to opus-mt on failure."""
    cache_key = f"translate|{text}|{source_lang}|{target_lang}|{style}"
    if cache_key in _style_cache:
        return _style_cache[cache_key]

    src_name = LANGUAGES[source_lang]
    tgt_name = LANGUAGES[target_lang]
    rules = NEUTRAL_RULE if style == "neutral" else STYLE_RULES.get(style, {}).get(tgt_name, "")
    meta = CASUAL_META_RULES if style == "casual" else STRICT_META_RULES

    prompt = f"""Translate this {src_name} text into {tgt_name} with a {style} tone.

{rules}

{meta.format(lang=tgt_name)}

Text: {text}"""

    try:
        raw = gemini.generate(prompt, temperature=0.2, max_tokens=512)
        result = gemini.strip_wrapping_quotes(raw)
        if target_lang == "tr" and style == "casual":
            result = revise_turkish_casual_output(text, result)
    except Exception as exc:
        print(f"  Gemini translate error: {str(exc)[:200]}")
        return opus_translate(text, source_lang, target_lang)

    note = f" -> cleaned '{result}'" if result != raw else ""
    print(f"  [Gemini] {style} {tgt_name}: '{text}' -> '{raw}'{note}")

    if len(result) < 2 and len(text) >= 2:
        return opus_translate(text, source_lang, target_lang)

    _style_cache[cache_key] = result
    return result


def gemini_restyle_same_language(text: str, language: str, style: str) -> str:
    """Change the register of a text without translating it."""
    if not gemini.is_ready() or style == "neutral":
        return text

    cache_key = f"restyle|{text}|{language}|{style}"
    if cache_key in _style_cache:
        return _style_cache[cache_key]

    lang_name = LANGUAGES[language]
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
        result = gemini.strip_wrapping_quotes(gemini.generate(prompt, temperature=0.3, max_tokens=512))
        if language == "tr" and style == "casual":
            result = revise_turkish_casual_output(text, result)
    except Exception as exc:
        print(f"  Restyle error: {str(exc)[:200]}")
        return text

    if len(result) < 2:
        return text
    _style_cache[cache_key] = result
    return result


# ──────────────────────────────────────────────
# Full pipeline
# ──────────────────────────────────────────────
def translate_with_style(text: str, source_lang: str, target_lang: str, style: str) -> dict:
    """
    - Same language: Gemini changes the register only.
    - Neutral: opus-mt, unless the input is very short or opus-mt copied it through.
    - Formal / casual: Gemini translates with the register rules.
    """
    if source_lang == target_lang:
        styled = gemini_restyle_same_language(text, source_lang, style)
        return {"base_translation": text, "styled_translation": styled}

    base = opus_translate(text, source_lang, target_lang)
    if not gemini.is_ready():
        return {"base_translation": base, "styled_translation": base}

    if style == "neutral":
        short = len(text.split()) <= SHORT_INPUT_WORDS
        if short or looks_untranslated(text, base):
            return {"base_translation": base, "styled_translation": gemini_translate_styled(text, source_lang, target_lang, "neutral")}
        return {"base_translation": base, "styled_translation": base}

    return {"base_translation": base, "styled_translation": gemini_translate_styled(text, source_lang, target_lang, style)}


def opus_translate_only(text: str, source_lang: str, target_lang: str) -> str:
    """For eval scripts: the opus-mt baseline on its own."""
    return opus_translate(text, source_lang, target_lang)


def translate_pipeline(text: str, source_lang: str, target_lang: str, style: str = "neutral") -> str:
    """For eval scripts: the full pipeline output."""
    return translate_with_style(text, source_lang, target_lang, style)["styled_translation"]


# ──────────────────────────────────────────────
# Tone classifier
# ──────────────────────────────────────────────
def detect_style(text: str) -> dict:
    """Score formal / neutral / casual with the fine-tuned BERT classifier."""
    if classifier_pipe is None:
        return {"formal": 0.33, "casual": 0.33, "neutral": 0.34}

    with _classifier_lock:
        results = classifier_pipe(text[:512])
    scores = {item["label"]: round(item["score"], 3) for item in results[0]}
    for style in STYLES:
        scores.setdefault(style, 0.0)
    return scores
