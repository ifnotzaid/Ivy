"""BLEU and chrF++ for opus-mt baseline vs full translation pipeline."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from eval.runners.common import load_jsonl, require_dependency, sleep_between_calls


def load_test_set(path):
    return load_jsonl(path)


def evaluate_translation(
    test_set: list[dict],
    baseline_fn: Callable[[str, str, str], str],
    pipeline_fn: Callable[[str, str, str, str], str],
    sleep_seconds: float = 0.0,
) -> dict:
    sacrebleu = require_dependency("sacrebleu")
    corpus_bleu = sacrebleu.corpus_bleu
    corpus_chrf = sacrebleu.corpus_chrf

    by_pair: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"refs": [], "base": [], "styled": [], "src": []})
    for item in test_set:
        key = f"{item['src_lang']}->{item['tgt_lang']}"
        style = item.get("style", "neutral")
        src = item["src"]
        src_lang = item["src_lang"]
        tgt_lang = item["tgt_lang"]

        base = baseline_fn(src, src_lang, tgt_lang)
        sleep_between_calls(sleep_seconds)
        styled = pipeline_fn(src, src_lang, tgt_lang, style)
        sleep_between_calls(sleep_seconds)

        by_pair[key]["refs"].append(item["ref"])
        by_pair[key]["src"].append(src)
        by_pair[key]["base"].append(base)
        by_pair[key]["styled"].append(styled)

    results = {}
    for pair, data in by_pair.items():
        baseline_bleu = corpus_bleu(data["base"], [data["refs"]]).score
        styled_bleu = corpus_bleu(data["styled"], [data["refs"]]).score
        baseline_chrf = corpus_chrf(data["base"], [data["refs"]], word_order=2).score
        styled_chrf = corpus_chrf(data["styled"], [data["refs"]], word_order=2).score
        results[pair] = {
            "n": len(data["refs"]),
            "baseline_bleu": round(baseline_bleu, 2),
            "baseline_chrf": round(baseline_chrf, 2),
            "pipeline_bleu": round(styled_bleu, 2),
            "pipeline_chrf": round(styled_chrf, 2),
            "delta_bleu": round(styled_bleu - baseline_bleu, 2),
            "delta_chrf": round(styled_chrf - baseline_chrf, 2),
        }
    return results
