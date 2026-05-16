"""Latency benchmarks for pipeline stages."""

from __future__ import annotations

import time
from typing import Callable

from eval.runners.common import percentile, sleep_between_calls


DEFAULT_TRANSLATION_SAMPLES = [
    ("I need to buy a train ticket for tomorrow.", "en", "tr"),
    ("Could you please send the report before Friday?", "en", "de"),
    ("The weather changed suddenly during the trip.", "en", "ru"),
    ("Ayşe sabah erkenden okula gitti.", "tr", "en"),
]

DEFAULT_ANALYSIS_SAMPLES = [
    ("Ayşe sabah erkenden okula gitti.", "tr"),
    ("Deniz çantasına su ve elma koydu.", "tr"),
]


def benchmark_pipeline(
    opus_fn: Callable[[str, str, str], str],
    pipeline_fn: Callable[[str, str, str, str], str],
    analyze_fn: Callable[[str, str], list[dict]],
    story_fn: Callable[[], dict] | None = None,
    tts_fn: Callable[[], bytes] | None = None,
    n: int = 50,
    warmup: int = 5,
    sleep_seconds: float = 0.0,
) -> dict:
    results = {}
    results["opus_mt_translate"] = _benchmark(
        lambda i: opus_fn(*DEFAULT_TRANSLATION_SAMPLES[i % len(DEFAULT_TRANSLATION_SAMPLES)]),
        n,
        warmup,
        sleep_seconds,
    )
    results["full_pipeline_neutral"] = _benchmark(
        lambda i: pipeline_fn(*DEFAULT_TRANSLATION_SAMPLES[i % len(DEFAULT_TRANSLATION_SAMPLES)], "neutral"),
        n,
        warmup,
        sleep_seconds,
    )
    results["full_pipeline_formal"] = _benchmark(
        lambda i: pipeline_fn(*DEFAULT_TRANSLATION_SAMPLES[i % len(DEFAULT_TRANSLATION_SAMPLES)], "formal"),
        n,
        warmup,
        sleep_seconds,
    )
    results["analyze_words_per_sentence"] = _benchmark(
        lambda i: analyze_fn(*DEFAULT_ANALYSIS_SAMPLES[i % len(DEFAULT_ANALYSIS_SAMPLES)]),
        n,
        warmup,
        sleep_seconds,
    )
    results["translate_then_analyze"] = _benchmark(
        lambda i: _translate_then_analyze(i, pipeline_fn, analyze_fn),
        n,
        warmup,
        sleep_seconds,
    )
    results["story_generation"] = _benchmark_optional(story_fn, n=min(n, 10), warmup=min(warmup, 2), sleep_seconds=sleep_seconds)
    results["tts_per_chunk"] = _benchmark_optional(tts_fn, n=min(n, 10), warmup=min(warmup, 2), sleep_seconds=sleep_seconds)
    return results


def _translate_then_analyze(index, pipeline_fn, analyze_fn):
    src, src_lang, tgt_lang = DEFAULT_TRANSLATION_SAMPLES[index % len(DEFAULT_TRANSLATION_SAMPLES)]
    translated = pipeline_fn(src, src_lang, tgt_lang, "neutral")
    return analyze_fn(translated, tgt_lang)


def _benchmark(fn: Callable[[int], object], n: int, warmup: int, sleep_seconds: float) -> dict:
    for i in range(warmup):
        fn(i)
        sleep_between_calls(sleep_seconds)

    times = []
    for i in range(n):
        start = time.perf_counter()
        fn(i)
        times.append((time.perf_counter() - start) * 1000)
        sleep_between_calls(sleep_seconds)

    return {
        "n": n,
        "p50": round(percentile(times, 50), 2),
        "p95": round(percentile(times, 95), 2),
        "min": round(min(times), 2) if times else 0.0,
        "max": round(max(times), 2) if times else 0.0,
    }


def _benchmark_optional(fn: Callable[[], object] | None, n: int, warmup: int, sleep_seconds: float) -> dict:
    if fn is None:
        return {"n": 0, "skipped": True}
    return _benchmark(lambda _i: fn(), n, warmup, sleep_seconds)
