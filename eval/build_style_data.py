"""Build style_test.jsonl entries using Gemini with a different prompt structure
than the one used for training data generation.

Why "different prompt structure" matters: your style classifier was trained on
sentences Gemini produced from one prompt template. Evaluating on sentences from
the *same* prompt template would test memorization, not generalization. This
script uses scenario-driven prompts at higher temperature, with different framing,
to produce sentences that exercise a different part of Gemini's output space.

Run from project root:
    py eval/build_style_data.py

The script reads GEMINI_API_KEY from .env (or from environment variable directly).
It APPENDS to eval/data/style_test.jsonl rather than replacing — so your existing
seed entries are preserved.

Cost: roughly $0.50-1 USD in Gemini API calls (~400 short generations).
Runtime: 5-15 minutes depending on rate limits.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

# Load .env so users don't have to set environment variables manually.
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: google-genai not installed. Run: pip install google-genai")
    sys.exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: GEMINI_API_KEY not found. Set it in .env or environment.")
    sys.exit(1)

OUT_PATH = ROOT / "eval" / "data" / "style_test.jsonl"
RANDOM_SEED = 137

# Target counts per (language, style). 4 langs × 3 styles × 33 = 396 sentences.
PER_BUCKET = 33

LANGUAGES = ["en", "tr", "de", "ru"]
STYLES = ["formal", "neutral", "casual"]
LANG_NAMES = {"en": "English", "tr": "Turkish", "de": "German", "ru": "Russian"}

# Scenario prompts: distinct from training data, which used "rewrite this in X style".
# Here we ask Gemini to *generate* fresh sentences in specific scenarios at specific
# registers, which exercises generation rather than restyling.
SCENARIOS = {
    "formal": [
        "writing an email to a professor or supervisor",
        "drafting a sentence in a business proposal",
        "delivering an academic lecture",
        "writing a complaint letter to a company",
        "speaking at a formal event or ceremony",
        "writing a job application cover letter",
        "addressing a government office in writing",
        "writing the introduction to a research paper",
    ],
    "neutral": [
        "describing a news event matter-of-factly",
        "writing an entry in a personal journal",
        "explaining a procedure step by step",
        "describing what someone is doing at the moment",
        "talking to a doctor about a symptom",
        "writing a product description",
        "narrating a short event from yesterday",
        "describing the weather or surroundings",
    ],
    "casual": [
        "texting a close friend about weekend plans",
        "venting to a friend about a bad day",
        "joking around in a group chat",
        "telling a friend you're excited about something",
        "complaining to a roommate about chores",
        "sharing a funny story at a cafe with friends",
        "reacting to surprising gossip from a friend",
        "making weekend plans on a casual call",
    ],
}


def build_prompt(language: str, style: str, scenario: str, batch_size: int) -> str:
    """Build a generation prompt that's structured deliberately different from
    the training-data prompt:
    - Scenario-driven (not restyle-driven)
    - Asks for a batch in JSON (not single sentences)
    - Specifies register markers explicitly per language
    """
    lang_name = LANG_NAMES[language]

    # Per-language register hints. These are explicit enough that Gemini knows
    # what to produce but loose enough to allow natural variation.
    register_hints = {
        "tr": {
            "formal": "Use 'siz' forms, complete sentence structure, formal vocabulary (yönetici, görüşmek, lütfen, rica ederim).",
            "neutral": "Use everyday Turkish with natural sentence flow. No specific register markers.",
            "casual": "Use 'sen' forms, drop -dır/-dir copula in nominal sentences, allow fragments and sentence-final 'ya' SPARINGLY.",
        },
        "de": {
            "formal": "Use 'Sie' forms, complete sentences, formal vocabulary, no contractions.",
            "neutral": "Use everyday German with natural flow.",
            "casual": "Use 'du' forms, contractions ('hab' for 'habe'), particles like 'mal', 'halt', 'echt'.",
        },
        "ru": {
            "formal": "Use 'Вы' forms, polite constructions ('не могли бы Вы...'), formal vocabulary.",
            "neutral": "Use everyday Russian. No specific register markers.",
            "casual": "Use 'ты' forms, casual particles ('ну', 'давай'), shorter sentences.",
        },
        "en": {
            "formal": "Use complete sentences, no contractions, formal vocabulary.",
            "neutral": "Use everyday English with natural flow.",
            "casual": "Use contractions ('I'm', 'gonna', 'wanna'), informal vocabulary, fragments allowed.",
        },
    }

    hint = register_hints[language][style]

    return f"""Generate {batch_size} distinct {lang_name} sentences for the following scenario:

Scenario: {scenario}
Required register: {style}
Register guidance: {hint}

Rules:
- Each sentence MUST be at most one sentence long (no compound multi-sentence outputs).
- Each sentence MUST sound natural in {lang_name} — no awkward translations from English.
- Sentences should vary in length and structure within the batch.
- Output ONLY a JSON array of strings, like ["sentence one", "sentence two", ...].
- Do not include explanations, numbering, or text outside the JSON array.

Output:"""


def call_gemini(client, prompt: str) -> str:
    """One Gemini call with retry on 503/transient errors."""
    last_err = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.85,  # higher than training's 0.2 → more variety
                    max_output_tokens=2048,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            return (response.text or "").strip()
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            print(f"    retry in {wait}s ({e})")
            time.sleep(wait)
    raise RuntimeError(f"Gemini failed 3x: {last_err}")


def parse_json_array(raw: str) -> list[str]:
    """Pull the JSON array out of Gemini's response. Sometimes it wraps in
    markdown fences or adds preamble despite our instruction."""
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        # Find first newline, drop it and the opening fence
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    # Find the JSON array bounds
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        arr = json.loads(raw[start : end + 1])
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if isinstance(x, (str, int))]
    except json.JSONDecodeError:
        pass
    return []


def generate_bucket(client, language: str, style: str, target: int, rng: random.Random) -> list[str]:
    """Generate `target` sentences for one (language, style) bucket.

    Loops over scenarios, asks Gemini for batches of 5, deduplicates, until
    we reach the target. Caps total attempts to avoid runaway loops if
    Gemini repeats itself heavily.
    """
    collected: list[str] = []
    seen: set[str] = set()
    scenarios = SCENARIOS[style][:]
    rng.shuffle(scenarios)

    scenario_idx = 0
    attempts = 0
    MAX_ATTEMPTS = 20

    while len(collected) < target and attempts < MAX_ATTEMPTS:
        scenario = scenarios[scenario_idx % len(scenarios)]
        scenario_idx += 1
        attempts += 1

        prompt = build_prompt(language, style, scenario, batch_size=6)
        raw = call_gemini(client, prompt)
        items = parse_json_array(raw)

        for s in items:
            s = s.strip().strip('"').strip("'").strip()
            # Basic sanity: skip empty, very short, or duplicate sentences.
            if len(s) < 5:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append(s)
            if len(collected) >= target:
                break

        # Polite to the API
        time.sleep(0.2)

    return collected[:target]


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    client = genai.Client(api_key=API_KEY)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Append mode: keep the existing seed entries intact.
    fout = open(OUT_PATH, "a", encoding="utf-8")
    total = 0

    try:
        for language in LANGUAGES:
            for style in STYLES:
                print(f"\n[{language} / {style}] generating {PER_BUCKET}...")
                sentences = generate_bucket(client, language, style, PER_BUCKET, rng)
                print(f"  got {len(sentences)} sentences")
                for s in sentences:
                    record = {"text": s, "language": language, "style": style}
                    fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total += 1
                fout.flush()
    finally:
        fout.close()

    print(f"\nAppended {total} entries to {OUT_PATH}")
    print("Note: existing seed entries were preserved (appended, not overwritten).")


if __name__ == "__main__":
    main()
