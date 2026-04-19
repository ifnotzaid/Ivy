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

import os
import sys
import json
import torch
import argparse
import time
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    pipeline,
    MarianMTModel,
    MarianTokenizer,
)

app = Flask(__name__)

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
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

STYLES = ["formal", "casual", "neutral"]
LANGUAGES = {
    "en": "English",
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
}

restyle_cache = {}


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
    """Accurate translation using opus-mt."""
    if source_lang == target_lang:
        return text

    key = (source_lang, target_lang)
    if key not in opus_models:
        return f"[No model for {source_lang} to {target_lang}]"

    model, tokenizer = opus_models[key]
    inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_length=512,
            num_beams=5,
            early_stopping=True,
            length_penalty=1.0,
        )

    return tokenizer.decode(outputs[0], skip_special_tokens=True)


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
    - Use casual expressions: "ya", "hadi", "lan" (if appropriate), "bi'"
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
            "Turkish": "Use 'sen' conjugation (-sin, -n). Keep sentences SHORT and natural. Use 'ya' only at the END of sentences as a softener, NEVER at the start. Do NOT use 'hadi ya' — it sounds angry. Good casual markers: 'bi'', sentence-final 'ya', 'lan' only between very close male friends. Bad markers to AVOID: 'hadi ya', 'ya,' at start of sentence, excessive particles. Sound like a relaxed friend, not an annoyed person.",
            "Russian": "Use 'ты', never 'Вы'. Use casual words: 'давай', 'ну'. Keep it short and natural. Use 'счёт' not 'чек' for restaurant bills.",
            "German": "Use 'du', never 'Sie'. Use particles: 'mal', 'halt', 'echt'. Contractions OK: 'hab' for 'habe'. Do NOT overuse 'echt jetzt' — it sounds sarcastic.",
            "English": "Use contractions: wanna, gonna. Slang OK. Keep it short.",
        },

    }

    rules = style_rules.get(style, {}).get(tgt_name, "")

    prompt = f"""Translate this {src_name} text into {tgt_name} with a {style} tone.

    {rules}

    CRITICAL RULES:
    - Translate accurately — same meaning, nothing added, nothing removed
    - Do NOT add extra words, phrases, or politeness markers that are not in the original
    - Do NOT make the translation longer than necessary
    - Only change register: pronouns, verb conjugation, and word choice
    - Output ONLY the {tgt_name} translation — no quotes, no explanation

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
        print(f"  [Gemini] {style} {tgt_name}: '{text}' -> '{result}'")
        for q in ['"', "'", "\u201c", "\u201d"]:
            if result.startswith(q) and result.endswith(q):
                result = result[1:-1].strip()

        if len(result) < 2:
            result = opus_translate(text, source_lang, target_lang)

        restyle_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"  Gemini translate error: {e}")
        return opus_translate(text, source_lang, target_lang)

def translate_with_style(text: str, source_lang: str, target_lang: str, style: str) -> dict:
    """
    Hybrid pipeline:
    - Neutral: opus-mt (fast, local)
    - Formal/Casual: Gemini translates + styles in one step
    """
    # Always get a neutral base translation from opus-mt
    base_translation = opus_translate(text, source_lang, target_lang)

    if style == "neutral" or source_lang == target_lang or gemini_client is None:
        return {
            "base_translation": base_translation,
            "styled_translation": base_translation,
        }

    # For formal/casual: Gemini does translation + styling together
    styled_translation = gemini_translate_styled(text, source_lang, target_lang, style)

    return {
        "base_translation": base_translation,
        "styled_translation": styled_translation,
    }

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


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


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

    return jsonify({
        "translation": result["styled_translation"],
        "base_translation": result["base_translation"],
        "style_scores": style_scores,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "style": style,
    })


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
        results[style] = {
            "translation": result["styled_translation"],
            "base_translation": result["base_translation"],
            "style_scores": scores,
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

    load_models(args.gemini_key)

    print(f"\n{'='*50}")
    print(f"  Style Translator v3 (Hybrid Pipeline)")
    print(f"  opus-mt: {len(opus_models)} translation pairs")
    print(f"  Gemini:  {'connected' if gemini_client else 'NOT connected'}")
    print(f"  Classifier: {'loaded' if classifier_pipe else 'NOT loaded'}")
    print(f"  http://localhost:{args.port}")
    print(f"{'='*50}\n")

    app.run(debug=False, host="0.0.0.0", port=args.port)
