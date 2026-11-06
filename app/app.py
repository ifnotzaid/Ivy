"""
Ivy - Flask backend.

The work lives in small modules next to this file:
  gemini.py       shared Gemini client and helpers
  translation.py  opus-mt + Gemini translation, and the tone classifier
  stories.py      CEFR story generation
  tts.py          story narration (Google Cloud Text-to-Speech)
  word_analysis.py, auth_routes.py, database.py

This file loads the models, defines the translate / story routes and starts the server.

Usage:
    python app/app.py            (reads GEMINI_API_KEY from .env)
    python app/app.py --port 5001
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

import gemini
import translation
from auth_routes import auth_bp, get_current_user
from database import (
    get_saved_story,
    get_story_audio,
    get_story_narration,
    get_user_known_words,
    get_user_struggling_words,
    init_db,
    set_story_audio,
    set_story_narration,
)
from stories import StoryError, generate_short_story
from translation import (
    LANGUAGES,
    STYLES,
    detect_style,
    opus_translate_only,  # noqa: F401  (used by eval/run_all.py)
    translate_pipeline,  # noqa: F401  (used by eval/run_all.py)
    translate_with_style,
)
from tts import (
    STORY_SENTENCE_SPLIT_RE,
    audio_mpeg_response,
    synthesize_marked_story_audio,
    synthesize_story_audio,
    timepoints_are_current,
)
from word_analysis import analyze_words

ROOT_DIR = Path(__file__).parent.parent
CLASSIFIER_MODEL_PATH = ROOT_DIR / "models" / "style-classifier-final"


def load_local_env() -> None:
    """Load simple KEY=VALUE pairs from the .env file in the repo root, if there is one."""
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

# Logs contain Turkish and Russian text. When output goes to a file, Windows
# defaults to cp1252 and a single "ı" would crash the request that printed it.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret-change-me")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.register_blueprint(auth_bp)


def load_models(gemini_key: str) -> None:
    """Load opus-mt, connect Gemini and load the tone classifier."""
    translation.load_translation_models()
    print("\nSetting up Gemini API...")
    gemini.connect(gemini_key)
    translation.load_classifier(CLASSIFIER_MODEL_PATH)


def __getattr__(name: str):
    # eval/run_all.py reads ivy_app.gemini_client after load_models().
    if name == "gemini_client":
        return gemini.get_client()
    raise AttributeError(name)


def read_json() -> dict:
    """The request body as a dict, or {} when it is missing or not JSON."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def check_languages(*codes: str):
    """Return an error response if any language code is not supported, else None."""
    if any(code not in LANGUAGES for code in codes):
        return jsonify({"error": "Unsupported language selection"}), 400
    return None


explain_cache: dict[str, str] = {}


# ──────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sets")
def sets_page():
    return render_template("sets.html")


# ──────────────────────────────────────────────
# Translation
# ──────────────────────────────────────────────
def word_details(text: str, language: str) -> list[dict]:
    return analyze_words(text, language, gemini.get_client() if gemini.is_ready() else None, LANGUAGES)


def translate_one_style(text: str, source_lang: str, target_lang: str, style: str) -> dict:
    """Translation, tone scores and word details for one register."""
    result = translate_with_style(text, source_lang, target_lang, style)
    output = result["styled_translation"]
    return {
        "translation": output,
        "base_translation": result["base_translation"],
        "style_scores": detect_style(output),
        "word_data": word_details(output, target_lang) if target_lang != source_lang else [],
    }


def read_translate_request():
    """Validate a translate/compare body. Returns (fields, None) or (None, error response)."""
    data = read_json()
    text = str(data.get("text") or "").strip()
    source_lang = data.get("source_lang", "en")
    target_lang = data.get("target_lang", "tr")
    style = data.get("style", "neutral")

    if not text:
        return None, (jsonify({"error": "No text provided"}), 400)
    if len(text) > 5000:
        return None, (jsonify({"error": "That text is too long. Try 5,000 characters or fewer."}), 413)
    error = check_languages(source_lang, target_lang)
    if error:
        return None, error
    if style not in STYLES:
        style = "neutral"
    return {"text": text, "source_lang": source_lang, "target_lang": target_lang, "style": style}, None


TRANSLATE_FAILED = "Ivy couldn't translate that right now. Please try again."


def ai_notice() -> dict:
    """Tell the page when results came from the basic translator because Gemini is out of quota."""
    return {"notice": gemini.TRANSLATE_LIMIT_NOTICE} if gemini.recently_rate_limited() else {}


@app.route("/api/translate", methods=["POST"])
def api_translate():
    fields, error = read_translate_request()
    if error:
        return error

    try:
        result = translate_one_style(fields["text"], fields["source_lang"], fields["target_lang"], fields["style"])
    except Exception as exc:
        print(f"[translate] failed: {exc}")
        return jsonify({"error": TRANSLATE_FAILED}), 503

    return jsonify({
        **result,
        **ai_notice(),
        "source_lang": fields["source_lang"],
        "target_lang": fields["target_lang"],
        "style": fields["style"],
    })


@app.route("/api/compare", methods=["POST"])
def api_compare():
    fields, error = read_translate_request()
    if error:
        return error
    text, source_lang, target_lang = fields["text"], fields["source_lang"], fields["target_lang"]

    # The three registers are independent, so ask for them at the same time.
    try:
        with ThreadPoolExecutor(max_workers=len(STYLES)) as pool:
            futures = {
                style: pool.submit(translate_one_style, text, source_lang, target_lang, style)
                for style in STYLES
            }
            results = {style: future.result() for style, future in futures.items()}
    except Exception as exc:
        print(f"[compare] failed: {exc}")
        return jsonify({"error": TRANSLATE_FAILED}), 503

    return jsonify({
        "results": results,
        **ai_notice(),
        "input_style": detect_style(text),
        "source_lang": source_lang,
        "target_lang": target_lang,
    })


@app.route("/api/detect-style", methods=["POST"])
def api_detect_style():
    text = str(read_json().get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    scores = detect_style(text)
    return jsonify({"scores": scores, "dominant_style": max(scores, key=scores.get)})


@app.route("/api/explain_sentence", methods=["POST"])
def api_explain_sentence():
    """A short grammar explanation of the translated sentence."""
    data = read_json()
    sentence = str(data.get("sentence") or "").strip()
    target_lang = data.get("target_lang", "tr")
    support_lang = data.get("support_lang", "en")

    if not sentence:
        return jsonify({"error": "No sentence provided"}), 400
    if len(sentence.encode("utf-8")) > 6000:
        return jsonify({"error": "That sentence is too long to explain at once."}), 413
    error = check_languages(target_lang, support_lang)
    if error:
        return error
    if not gemini.is_ready():
        return jsonify({"error": "Explanations need the Gemini API key. Add GEMINI_API_KEY to .env and restart Ivy."}), 503

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
        explanation = gemini.generate(prompt, temperature=0.4, max_tokens=600)
    except Exception as exc:
        print(f"[explain_sentence] Gemini failed: {exc}")
        return jsonify({"error": gemini.friendly_error(exc, "explain this sentence")}), 503

    if not explanation:
        return jsonify({"error": "Ivy returned an empty explanation. Please try again."}), 503
    explain_cache[cache_key] = explanation
    return jsonify({"explanation": explanation})


# ──────────────────────────────────────────────
# Stories
# ──────────────────────────────────────────────
@app.route("/api/stories/generate", methods=["POST"])
def api_generate_story():
    data = read_json()
    target_lang = data.get("target_lang", "tr")
    support_lang = data.get("support_lang", "en")
    error = check_languages(target_lang, support_lang)
    if error:
        return error

    learner_profile = None
    if data.get("personalize"):
        user = get_current_user()
        if user:
            known = get_user_known_words(user["id"], target_lang, limit=25)
            struggling = get_user_struggling_words(user["id"], target_lang, limit=3)
            if known or struggling:
                learner_profile = {"known_words": known, "struggling_words": struggling}

    try:
        story = generate_short_story(
            target_lang=target_lang,
            support_lang=support_lang,
            cefr_level=str(data.get("cefr_level") or "A2"),
            theme=str(data.get("theme") or "daily life"),
            length_label=str(data.get("length_label") or "short"),
            style=data.get("style", "neutral"),
            variation_id=str(data.get("variation_id") or ""),
            learner_profile=learner_profile,
        )
    except StoryError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        print(f"[stories] generation crashed: {exc}")
        return jsonify({"error": "Ivy couldn't write a story. Please try again."}), 500

    return jsonify(story)


@app.route("/api/stories/analyze", methods=["POST"])
def api_analyze_story():
    data = read_json()
    text = str(data.get("text") or "").strip()
    target_lang = data.get("target_lang", "tr")

    if not text:
        return jsonify({"word_data": []})
    error = check_languages(target_lang)
    if error:
        return error

    sentences = [chunk.strip() for chunk in re.split(STORY_SENTENCE_SPLIT_RE, text) if chunk.strip()]

    # Sentences are analysed independently; run a few at once but keep their order.
    with ThreadPoolExecutor(max_workers=4) as pool:
        per_sentence = list(pool.map(lambda s: word_details(s, target_lang), sentences))

    return jsonify({"word_data": [item for words in per_sentence for item in words]})


def saved_story_for(story_id):
    """(user, story) when story_id belongs to the logged-in user, else (None, None)."""
    try:
        story_id = int(story_id)
    except (TypeError, ValueError):
        return None, None
    user = get_current_user()
    if not user or story_id <= 0:
        return None, None
    story = get_saved_story(user["id"], story_id)
    return (user, story) if story else (None, None)


def tts_error(exc: RuntimeError):
    status = 503 if "failed" in str(exc).lower() else 400
    return jsonify({"error": str(exc)}), status


def narration_json(audio: bytes, timepoints: list, cached: bool):
    return jsonify({
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "timepoints": timepoints,
        "cached": cached,
    })


@app.route("/api/stories/tts", methods=["POST"])
def api_story_tts():
    data = read_json()
    text = str(data.get("text") or "")
    language = data.get("language", "tr")
    error = check_languages(language)
    if error:
        return error

    user, story = saved_story_for(data.get("story_id"))
    if story:
        cached = get_story_audio(user["id"], story["id"])
        if cached:
            return audio_mpeg_response(cached)

    try:
        audio, content_type = synthesize_story_audio(data.get("provider", ""), text, language)
    except RuntimeError as exc:
        return tts_error(exc)

    if story and (story.get("story_text") or "").strip() == text.strip():
        try:
            set_story_audio(user["id"], story["id"], audio)
        except Exception as exc:
            print(f"[tts] saving audio failed (non-fatal): {exc}")

    return Response(audio, mimetype=content_type)


@app.route("/api/stories/tts-marked", methods=["POST"])
def api_story_tts_marked():
    """One MP3 plus per-word timings for karaoke-style story playback."""
    data = read_json()
    language = data.get("language", "tr")
    story_text = str(data.get("story_text") or data.get("text") or "")
    word_data = data.get("word_data") if isinstance(data.get("word_data"), list) else []
    words = data.get("words") if isinstance(data.get("words"), list) else []
    word_items = word_data or [str(word or "") for word in words]

    error = check_languages(language)
    if error:
        return error
    if not word_items:
        return jsonify({"error": "Words are required for word-synced narration"}), 400

    user, story = saved_story_for(data.get("story_id"))
    if story:
        cached = get_story_narration(user["id"], story["id"])
        if cached and timepoints_are_current(cached["timepoints"]):
            return narration_json(cached["audio_bytes"], cached["timepoints"], cached=True)
        story_text = story_text or story.get("story_text") or ""

    try:
        audio, timepoints = synthesize_marked_story_audio(word_items, language, story_text)
    except RuntimeError as exc:
        return tts_error(exc)

    if story:
        try:
            set_story_narration(user["id"], story["id"], audio, timepoints)
        except Exception as exc:
            print(f"[tts-marked] saving narration failed (non-fatal): {exc}")

    return narration_json(audio, timepoints, cached=False)


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
    """Cached word-synced narration for a saved story."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    cached = get_story_narration(user["id"], story_id)
    if not cached or not timepoints_are_current(cached["timepoints"]):
        return jsonify({"error": "No synced narration for this story"}), 404

    return narration_json(cached["audio_bytes"], cached["timepoints"], cached=True)


@app.route("/api/stories/<int:story_id>/narration", methods=["PUT"])
def api_put_story_narration(story_id):
    """Save word-synced narration that was made before the story was saved."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = read_json()
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
                        help="Gemini API key (defaults to GEMINI_API_KEY from .env)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    init_db()
    load_models(args.gemini_key)

    print(f"\n{'=' * 50}")
    print("  Ivy - style-aware translator")
    print(f"  opus-mt: {len(translation.opus_models)} translation pairs")
    print(f"  Gemini:  {'connected' if gemini.is_ready() else 'NOT connected'}")
    print(f"  Classifier: {'loaded' if translation.classifier_pipe else 'NOT loaded'}")
    print(f"  http://localhost:{args.port}")
    print(f"{'=' * 50}\n")

    app.run(debug=False, host="0.0.0.0", port=args.port)
