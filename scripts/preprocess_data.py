"""
preprocess_data.py — Convert raw Gemini output into mT5 training format.

Takes the JSONL files from generate_data.py and produces clean CSV files
ready for fine-tuning, with the format:
    input:  "[formal] translate English to Turkish: How are you doing?"
    target: "Nasılsınız, iyi misiniz?"

Also downloads OPUS parallel data and merges everything.

Usage:
    python scripts/preprocess_data.py --lang turkish
    python scripts/preprocess_data.py --lang all
"""

import argparse
import json
import csv
import random
from pathlib import Path
from collections import Counter

import pandas as pd
from tqdm import tqdm


LANG_CODES = {
    "turkish": "tr",
    "russian": "ru",
    "german": "de",
}

STYLES = ["formal", "casual", "neutral"]


def load_gemini_data(lang: str) -> list[dict]:
    """Load and parse the raw JSONL from Gemini generation."""
    raw_file = Path(f"data/raw/style_pairs_{lang}.jsonl")
    if not raw_file.exists():
        print(f"  [!] File not found: {raw_file}")
        print(f"      Run generate_data.py --lang {lang} first!")
        return []

    records = []
    bad_lines = 0
    with open(raw_file, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(obj)
            except json.JSONDecodeError:
                bad_lines += 1

    print(f"  Loaded {len(records)} records from {raw_file} ({bad_lines} bad lines skipped)")
    return records


def gemini_to_training_pairs(records: list[dict], lang: str) -> list[dict]:
    """
    Convert Gemini records into training pairs.
    
    Each Gemini record has:
        en_formal, en_casual, en_neutral,
        {lang}_formal, {lang}_casual, {lang}_neutral
    
    We create training pairs for BOTH directions:
        EN → target_lang  AND  target_lang → EN
    
    For each style, we create:
        input:  "[formal] translate English to Turkish: Hello, how are you?"
        target: "Merhaba, nasılsınız?"
    """
    lang_code = LANG_CODES[lang]
    lang_name = lang.capitalize()
    pairs = []

    for record in records:
        for style in STYLES:
            en_key = f"en_{style}"
            tgt_key = f"{lang}_{style}"

            en_text = record.get(en_key, "").strip()
            tgt_text = record.get(tgt_key, "").strip()

            if not en_text or not tgt_text:
                continue

            # Skip if too short or too long
            if len(en_text) < 5 or len(tgt_text) < 5:
                continue
            if len(en_text) > 500 or len(tgt_text) > 500:
                continue

            # EN → Target language (styled)
            pairs.append({
                "input": f"[{style}] translate English to {lang_name}: {en_text}",
                "target": tgt_text,
                "style": style,
                "direction": f"en-{lang_code}",
                "source": "gemini_synthetic",
            })

            # Target language → EN (styled)
            pairs.append({
                "input": f"[{style}] translate {lang_name} to English: {tgt_text}",
                "target": en_text,
                "style": style,
                "direction": f"{lang_code}-en",
                "source": "gemini_synthetic",
            })

            # BONUS: Cross-style pairs (same language, style transfer)
            # e.g., "[formal] restyle English: hey whats up" → "Hello, how are you?"
            # This teaches the model about style independently of translation
            for other_style in STYLES:
                if other_style == style:
                    continue
                other_en = record.get(f"en_{other_style}", "").strip()
                if other_en and len(other_en) >= 5:
                    pairs.append({
                        "input": f"[{style}] restyle English: {other_en}",
                        "target": en_text,
                        "style": style,
                        "direction": "en-en",
                        "source": "gemini_restyle",
                    })

    return pairs


def deduplicate(pairs: list[dict]) -> list[dict]:
    """Remove exact duplicate input-target pairs."""
    seen = set()
    unique = []
    for p in pairs:
        key = (p["input"], p["target"])
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def split_data(pairs: list[dict], train_ratio=0.85, val_ratio=0.10, seed=42):
    """Split into train/val/test sets, stratified by style and direction."""
    random.seed(seed)
    random.shuffle(pairs)

    n = len(pairs)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    return {
        "train": pairs[:train_end],
        "val": pairs[train_end:val_end],
        "test": pairs[val_end:],
    }


def save_splits(splits: dict, lang: str):
    """Save train/val/test as CSV files."""
    output_dir = Path("data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)

    for split_name, data in splits.items():
        file_path = output_dir / f"{split_name}_{lang}.csv"
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False, quoting=csv.QUOTE_ALL)
        print(f"  Saved {split_name}: {len(data):,} pairs → {file_path}")


def print_stats(pairs: list[dict], lang: str):
    """Print dataset statistics."""
    style_counts = Counter(p["style"] for p in pairs)
    direction_counts = Counter(p["direction"] for p in pairs)
    source_counts = Counter(p["source"] for p in pairs)

    print(f"\n  {'─'*45}")
    print(f"  Stats for {lang.upper()}")
    print(f"  {'─'*45}")
    print(f"  Total pairs: {len(pairs):,}")
    print(f"\n  By style:")
    for s, c in sorted(style_counts.items()):
        print(f"    {s:>10}: {c:,}")
    print(f"\n  By direction:")
    for d, c in sorted(direction_counts.items()):
        print(f"    {d:>10}: {c:,}")
    print(f"\n  By source:")
    for s, c in sorted(source_counts.items()):
        print(f"    {s:>20}: {c:,}")
    print(f"  {'─'*45}\n")


def process_language(lang: str):
    """Full pipeline for one language."""
    print(f"\n{'='*60}")
    print(f"  Processing: {lang.upper()}")
    print(f"{'='*60}")

    # Step 1: Load raw data
    records = load_gemini_data(lang)
    if not records:
        return

    # Step 2: Convert to training pairs
    pairs = gemini_to_training_pairs(records, lang)
    print(f"  Generated {len(pairs):,} raw training pairs")

    # Step 3: Deduplicate
    pairs = deduplicate(pairs)
    print(f"  After dedup: {len(pairs):,} unique pairs")

    # Step 4: Print stats
    print_stats(pairs, lang)

    # Step 5: Split and save
    splits = split_data(pairs)
    save_splits(splits, lang)

    # Step 6: Also save a combined version for the classifier
    classifier_dir = Path("data/processed/classifier")
    classifier_dir.mkdir(parents=True, exist_ok=True)

    classifier_data = []
    for record in records:
        for style in STYLES:
            for lang_prefix in ["en", lang]:
                key = f"{lang_prefix}_{style}"
                text = record.get(key, "").strip()
                if text and len(text) >= 5:
                    classifier_data.append({
                        "text": text,
                        "style": style,
                        "language": lang_prefix if lang_prefix == "en" else LANG_CODES[lang],
                    })

    clf_df = pd.DataFrame(classifier_data).drop_duplicates(subset=["text"])
    clf_path = classifier_dir / f"classifier_{lang}.csv"
    clf_df.to_csv(clf_path, index=False, quoting=csv.QUOTE_ALL)
    print(f"  Saved classifier data: {len(clf_df):,} labeled sentences → {clf_path}")


def merge_all_languages():
    """Merge all language files into combined train/val/test."""
    output_dir = Path("data/processed")
    for split in ["train", "val", "test"]:
        frames = []
        for lang in LANG_CODES:
            f = output_dir / f"{split}_{lang}.csv"
            if f.exists():
                frames.append(pd.read_csv(f))
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            combined = combined.sample(frac=1, random_state=42).reset_index(drop=True)  # shuffle
            combined_path = output_dir / f"{split}_all.csv"
            combined.to_csv(combined_path, index=False, quoting=csv.QUOTE_ALL)
            print(f"  Combined {split}: {len(combined):,} pairs → {combined_path}")

    # Merge classifier data too
    clf_dir = output_dir / "classifier"
    clf_frames = []
    for lang in LANG_CODES:
        f = clf_dir / f"classifier_{lang}.csv"
        if f.exists():
            clf_frames.append(pd.read_csv(f))
    if clf_frames:
        combined_clf = pd.concat(clf_frames, ignore_index=True).drop_duplicates(subset=["text"])
        combined_clf.to_csv(clf_dir / "classifier_all.csv", index=False, quoting=csv.QUOTE_ALL)
        print(f"  Combined classifier: {len(combined_clf):,} sentences")


def main():
    parser = argparse.ArgumentParser(description="Preprocess style translation data")
    parser.add_argument("--lang", type=str, required=True,
                        choices=["turkish", "russian", "german", "all"],
                        help="Language to process (or 'all')")
    args = parser.parse_args()

    if args.lang == "all":
        for lang in LANG_CODES:
            process_language(lang)
        print(f"\n{'='*60}")
        print(f"  Merging all languages")
        print(f"{'='*60}")
        merge_all_languages()
    else:
        process_language(args.lang)

    print("\nDone! Next steps:")
    print("  1. Inspect data/processed/*.csv — spot-check 20-30 rows per language")
    print("  2. Run the style classifier training script")
    print("  3. Upload to Google Colab for model training")


if __name__ == "__main__":
    main()
