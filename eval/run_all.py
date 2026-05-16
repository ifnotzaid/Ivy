"""Run all evaluations and emit reports/evaluation_report.md and .json."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))

from eval.report import render_markdown_report
from eval.runners.common import load_jsonl
from eval.runners.latency import benchmark_pipeline
from eval.runners.style import evaluate_style_classifier
from eval.runners.translation import evaluate_translation
from eval.runners.word_analysis import evaluate_word_analysis


def load_dotenv() -> None:
    """Load simple KEY=VALUE lines from .env for local evaluation runs."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_ivy_app_module():
    """Load app/app.py with the same script-style imports used by Flask."""
    spec = importlib.util.spec_from_file_location("ivy_flask_app", APP_DIR / "app.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load app/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run ivy evaluation harness.")
    parser.add_argument("--translation-data", default="eval/data/translation_test.jsonl")
    parser.add_argument("--style-data", default="eval/data/style_test.jsonl")
    parser.add_argument("--word-data", default="eval/data/word_analysis_test.jsonl")
    parser.add_argument("--latency-n", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds to sleep between API-heavy calls.")
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--skip-style", action="store_true")
    parser.add_argument("--skip-word-analysis", action="store_true")
    parser.add_argument("--skip-latency", action="store_true")
    parser.add_argument("--include-story-latency", action="store_true")
    parser.add_argument("--include-tts-latency", action="store_true")
    args = parser.parse_args()

    translation_set = load_jsonl(args.translation_data)
    style_set = load_jsonl(args.style_data)
    word_set = load_jsonl(args.word_data)

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset_sizes": {
            "translation": len(translation_set),
            "style": len(style_set),
            "word_analysis": len(word_set),
        },
        "translation": {},
        "style": {},
        "word_analysis": {},
        "latency_ms": {},
    }

    all_sections_skipped = (
        args.skip_translation
        and args.skip_style
        and args.skip_word_analysis
        and args.skip_latency
    )
    ivy_app = None
    analyze = None
    predict_style = None
    if not all_sections_skipped:
        ivy_app = load_ivy_app_module()
        from word_analysis import analyze_words

        print("Loading models...")
        ivy_app.load_models(os.environ.get("GEMINI_API_KEY", ""))

        def predict_style(text: str) -> str:
            scores = ivy_app.detect_style(text)
            return max(scores, key=scores.get)

        def analyze(sentence: str, language: str) -> list[dict]:
            return analyze_words(sentence, language, ivy_app.gemini_client, ivy_app.LANGUAGES)

    if not args.skip_translation:
        print("Running translation evaluation...")
        report["translation"] = evaluate_translation(
            translation_set,
            baseline_fn=ivy_app.opus_translate_only,  # type: ignore[union-attr]
            pipeline_fn=ivy_app.translate_pipeline,  # type: ignore[union-attr]
            sleep_seconds=args.sleep,
        )

    if not args.skip_style:
        print("Running style classifier evaluation...")
        report["style"] = evaluate_style_classifier(style_set, predict_style)  # type: ignore[arg-type]

    if not args.skip_word_analysis:
        print("Running word-analysis evaluation...")
        report["word_analysis"] = evaluate_word_analysis(word_set, analyze)  # type: ignore[arg-type]

    if not args.skip_latency:
        print("Running latency benchmarks...")
        story_fn = None
        tts_fn = None
        if args.include_story_latency:
            story_fn = lambda: ivy_app.generate_short_story("tr", "en", "A2", "daily life", "short", "neutral")  # type: ignore[union-attr]
        if args.include_tts_latency:
            tts_fn = lambda: ivy_app.synthesize_story_audio("google", "Ayşe sabah erkenden okula gitti.", "tr")[0]  # type: ignore[union-attr]
        report["latency_ms"] = benchmark_pipeline(
            opus_fn=ivy_app.opus_translate_only,  # type: ignore[union-attr]
            pipeline_fn=ivy_app.translate_pipeline,  # type: ignore[union-attr]
            analyze_fn=analyze,  # type: ignore[arg-type]
            story_fn=story_fn,
            tts_fn=tts_fn,
            n=args.latency_n,
            warmup=args.warmup,
            sleep_seconds=args.sleep,
        )

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "evaluation_report.md").write_text(render_markdown_report(report), encoding="utf-8")
    (reports_dir / "evaluation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote reports/evaluation_report.md and reports/evaluation_report.json")


if __name__ == "__main__":
    main()
