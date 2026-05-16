"""Style classifier held-out evaluation."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from eval.runners.common import load_jsonl, normalize_label, require_dependency

LABELS = ["formal", "neutral", "casual"]


def evaluate_style_classifier(test_set: list[dict], predict_fn: Callable[[str], str]) -> dict:
    metrics = require_dependency("sklearn.metrics", "scikit-learn")
    classification_report = metrics.classification_report
    confusion_matrix = metrics.confusion_matrix

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in test_set:
        grouped[item.get("language", "all")].append(item)

    results = {}
    all_true = []
    all_pred = []
    for language, rows in grouped.items():
        y_true = [normalize_label(row["style"]) for row in rows]
        y_pred = [normalize_label(predict_fn(row["text"])) for row in rows]
        all_true.extend(y_true)
        all_pred.extend(y_pred)
        results[language] = _metrics_for(y_true, y_pred, classification_report, confusion_matrix)

    results["overall"] = _metrics_for(all_true, all_pred, classification_report, confusion_matrix)
    return results


def _metrics_for(y_true, y_pred, classification_report, confusion_matrix) -> dict:
    report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS).tolist()
    return {
        "n": len(y_true),
        "accuracy": round(report["accuracy"], 4) if y_true else 0.0,
        "macro_f1": round(report["macro avg"]["f1-score"], 4) if y_true else 0.0,
        "per_class": {
            label: {
                "precision": round(report[label]["precision"], 4),
                "recall": round(report[label]["recall"], 4),
                "f1": round(report[label]["f1-score"], 4),
                "support": int(report[label]["support"]),
            }
            for label in LABELS
        },
        "labels": LABELS,
        "confusion_matrix": matrix,
    }
