"""Word-analysis agreement against hand annotations."""

from __future__ import annotations

import re
from typing import Callable

from eval.runners.common import normalize_label


def evaluate_word_analysis(test_set: list[dict], analyze_fn: Callable[[str, str], list[dict]]) -> dict:
    pos_correct = 0
    base_correct = 0
    found = 0
    errors = []

    for item in test_set:
        sentence = item["sentence"]
        language = item.get("language", "tr")
        target = _clean_token(item["word"])
        expected_pos = normalize_label(item["expected_pos"])
        expected_base = _normalize_base(item["expected_base_form"])
        analysis = analyze_fn(sentence, language)
        match = _find_word(analysis, target)

        if not match:
            errors.append({**item, "error": "word_not_found", "predicted": None})
            continue

        found += 1
        predicted_pos = normalize_label(match.get("pos", ""))
        predicted_base = _normalize_base(match.get("base_form", ""))
        pos_ok = predicted_pos == expected_pos
        base_ok = predicted_base == expected_base
        pos_correct += int(pos_ok)
        base_correct += int(base_ok)
        if not (pos_ok and base_ok):
            errors.append({
                **item,
                "predicted_pos": predicted_pos,
                "predicted_base_form": predicted_base,
                "pos_ok": pos_ok,
                "base_form_ok": base_ok,
            })

    n = len(test_set)
    return {
        "n": n,
        "found": found,
        "pos_accuracy": round(pos_correct / found, 4) if found else 0.0,
        "base_form_accuracy": round(base_correct / found, 4) if found else 0.0,
        "coverage": round(found / n, 4) if n else 0.0,
        "errors": errors[:25],
        "error_count": len(errors),
    }


def _find_word(analysis: list[dict], target: str) -> dict | None:
    for item in analysis:
        if _clean_token(item.get("word", "")) == target:
            return item
    return None


def _clean_token(value: str) -> str:
    return re.sub(r"^[^\wçğıöşüÇĞİÖŞÜ]+|[^\wçğıöşüÇĞİÖŞÜ]+$", "", str(value or "")).casefold()


def _normalize_base(value: str) -> str:
    return _clean_token(value)
