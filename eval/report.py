"""Render evaluation results into markdown."""

from __future__ import annotations

from statistics import mean


def render_markdown_report(report: dict) -> str:
    lines = [
        "# ivy Evaluation Report",
        f"Generated: {report.get('timestamp', '')}",
        "",
        "## Summary",
    ]
    lines.extend(_summary_lines(report))
    lines.extend(["", "## Translation Quality", ""])
    lines.extend(_translation_table(report.get("translation", {})))
    lines.extend(["", "## Style Classifier", ""])
    lines.extend(_style_sections(report.get("style", {})))
    lines.extend(["", "## Word Analysis", ""])
    lines.extend(_word_analysis_section(report.get("word_analysis", {})))
    lines.extend(["", "## Latency (ms)", ""])
    lines.extend(_latency_table(report.get("latency_ms", {})))
    lines.extend(["", "## Dataset Sizes", ""])
    lines.extend(_dataset_size_notes(report))
    return "\n".join(lines).rstrip() + "\n"


def _summary_lines(report: dict) -> list[str]:
    translation = report.get("translation", {})
    style = report.get("style", {}).get("overall", {})
    word = report.get("word_analysis", {})
    latency = report.get("latency_ms", {})
    pipeline_bleu = _avg([row.get("pipeline_bleu", 0) for row in translation.values()])
    baseline_bleu = _avg([row.get("baseline_bleu", 0) for row in translation.values()])
    p95 = latency.get("translate_then_analyze", {}).get("p95")

    lines = [
        f"- Translation: average pipeline BLEU {pipeline_bleu:.2f} (baseline {baseline_bleu:.2f}, delta {pipeline_bleu - baseline_bleu:+.2f}).",
        f"- Style classifier: macro-F1 {style.get('macro_f1', 0):.4f} across {style.get('n', 0)} examples.",
        f"- Word analysis: POS accuracy {word.get('pos_accuracy', 0):.2%}, base-form accuracy {word.get('base_form_accuracy', 0):.2%} (found {word.get('found', 0)}/{word.get('n', 0)}).",
    ]
    if p95 is not None:
        lines.append(f"- End-to-end translation + analysis p95 latency: {p95} ms.")
    return lines


def _translation_table(results: dict) -> list[str]:
    if not results:
        return ["No translation results."]
    lines = [
        "| Pair | n | Baseline BLEU | Pipeline BLEU | Delta | Baseline chrF++ | Pipeline chrF++ |",
        "|------|---|---------------|---------------|-------|---------------|---------------|",
    ]
    for pair, row in sorted(results.items()):
        lines.append(
            f"| {pair} | {row['n']} | {row['baseline_bleu']:.2f} | {row['pipeline_bleu']:.2f} | "
            f"{row['delta_bleu']:+.2f} | {row['baseline_chrf']:.2f} | {row['pipeline_chrf']:.2f} |"
        )
    return lines


def _style_sections(results: dict) -> list[str]:
    if not results:
        return ["No style classifier results."]
    lines = []
    for language, row in sorted(results.items()):
        if language == "overall":
            continue
        lines.extend(_one_style_section(language, row))
    if "overall" in results:
        lines.extend(_one_style_section("overall", results["overall"]))
    return lines


def _one_style_section(name: str, row: dict) -> list[str]:
    labels = row.get("labels", ["formal", "neutral", "casual"])
    matrix = row.get("confusion_matrix", [])
    lines = [
        f"### {name}",
        f"n={row.get('n', 0)}, accuracy={row.get('accuracy', 0):.4f}, macro-F1={row.get('macro_f1', 0):.4f}",
        "",
        "| Class | Precision | Recall | F1 | Support |",
        "|-------|-----------|--------|----|---------|",
    ]
    for label, stats in row.get("per_class", {}).items():
        lines.append(
            f"| {label} | {stats['precision']:.4f} | {stats['recall']:.4f} | {stats['f1']:.4f} | {stats['support']} |"
        )
    lines.extend(["", "Confusion matrix:", "", "| actual \\ predicted | " + " | ".join(labels) + " |"])
    lines.append("|---|" + "|".join(["---"] * len(labels)) + "|")
    for label, values in zip(labels, matrix):
        lines.append("| " + label + " | " + " | ".join(str(v) for v in values) + " |")
    lines.append("")
    return lines


def _word_analysis_section(results: dict) -> list[str]:
    if not results:
        return ["No word-analysis results."]
    lines = [
        f"- n: {results.get('n', 0)}",
        f"- found: {results.get('found', 0)}",
        f"- coverage: {results.get('coverage', 0):.2%}",
        f"- POS accuracy: {results.get('pos_accuracy', 0):.2%}",
        f"- base-form accuracy: {results.get('base_form_accuracy', 0):.2%}",
        f"- mismatches: {results.get('error_count', 0)}",
    ]
    errors = results.get("errors", [])
    if errors:
        lines.extend(["", "Sample mismatches:", "", "| Word | Expected POS | Predicted POS | Expected Base | Predicted Base |", "|------|--------------|---------------|---------------|----------------|"])
        for err in errors[:10]:
            lines.append(
                f"| {err.get('word', '')} | {err.get('expected_pos', '')} | {err.get('predicted_pos', err.get('error', ''))} | "
                f"{err.get('expected_base_form', '')} | {err.get('predicted_base_form', '')} |"
            )
    return lines


def _latency_table(results: dict) -> list[str]:
    if not results:
        return ["No latency results."]
    lines = ["| Stage | p50 | p95 | min | max | n |", "|-------|-----|-----|-----|-----|---|"]
    for stage, row in results.items():
        if row.get("skipped"):
            lines.append(f"| {stage} | skipped | skipped | skipped | skipped | 0 |")
        else:
            lines.append(f"| {stage} | {row['p50']} | {row['p95']} | {row['min']} | {row['max']} | {row['n']} |")
    return lines


def _dataset_size_notes(report: dict) -> list[str]:
    data = report.get("dataset_sizes", {})
    lines = [
        f"- translation examples: {data.get('translation', 0)} (target for final defense: 300)",
        f"- style examples: {data.get('style', 0)} (target for final defense: ~400)",
        f"- word-analysis examples: {data.get('word_analysis', 0)} (target for final defense: 100)",
    ]
    if any(data.get(key, 0) < target for key, target in [("translation", 300), ("style", 300), ("word_analysis", 100)]):
        lines.append("- Note: current seed data validates the harness; expand JSONL files before quoting final capstone metrics.")
    return lines


def _avg(values: list[float]) -> float:
    return mean(values) if values else 0.0
