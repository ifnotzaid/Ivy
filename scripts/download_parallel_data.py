"""
download_parallel_data.py — Download real parallel translation data from OPUS/Tatoeba.

Downloads high-quality EN↔TR, EN↔RU, EN↔DE parallel sentences and formats
them as "neutral" style training pairs to supplement the synthetic style data.

Usage:
    pip install datasets
    python scripts/download_parallel_data.py
"""

import csv
import random
from pathlib import Path
from collections import Counter

import pandas as pd

try:
    from datasets import load_dataset
except ImportError:
    print("Install datasets: pip install datasets")
    exit(1)


LANG_PAIRS = {
    "tr": {"name": "Turkish", "tatoeba": "en-tr", "tatoeba_src": "en", "tatoeba_tgt": "tr"},
    "ru": {"name": "Russian", "tatoeba": "en-ru", "tatoeba_src": "en", "tatoeba_tgt": "ru"},
    "de": {"name": "German", "tatoeba": "en-de", "tatoeba_src": "en", "tatoeba_tgt": "de"},
}

TARGET_PER_LANG = 50000  # How many parallel pairs to collect per language
MIN_LEN = 5             # Minimum character length
MAX_LEN = 300           # Maximum character length


def clean_text(text: str) -> str:
    """Basic text cleaning."""
    if not isinstance(text, str):
        return ""
    text = text.strip()
    # Remove multiple spaces
    text = " ".join(text.split())
    return text


def is_valid_pair(src: str, tgt: str) -> bool:
    """Check if a sentence pair is usable."""
    if not src or not tgt:
        return False
    if len(src) < MIN_LEN or len(tgt) < MIN_LEN:
        return False
    if len(src) > MAX_LEN or len(tgt) > MAX_LEN:
        return False
    # Skip if they're identical (not translated)
    if src.lower().strip() == tgt.lower().strip():
        return False
    # Skip if it's just a number or URL
    if src.replace(" ", "").isdigit() or tgt.replace(" ", "").isdigit():
        return False
    return True


def format_as_training_pairs(en_text: str, other_text: str, lang_code: str, lang_name: str) -> list[dict]:
    """Convert a parallel pair into our training format (both directions)."""
    pairs = []

    # EN → target (neutral)
    pairs.append({
        "input": f"[neutral] translate English to {lang_name}: {en_text}",
        "target": other_text,
        "style": "neutral",
        "direction": f"en-{lang_code}",
        "source": "opus_parallel",
    })

    # Target → EN (neutral)
    pairs.append({
        "input": f"[neutral] translate {lang_name} to English: {other_text}",
        "target": en_text,
        "style": "neutral",
        "direction": f"{lang_code}-en",
        "source": "opus_parallel",
    })

    return pairs


def download_tatoeba(lang_code: str, lang_info: dict, max_pairs: int) -> list[dict]:
    """Download from Tatoeba dataset on HuggingFace."""
    pairs = []
    pair_key = lang_info["tatoeba"]

    print(f"  Downloading Tatoeba {pair_key}...")
    try:
        ds = load_dataset("Helsinki-NLP/tatoeba_mt", pair_key, split="test", trust_remote_code=True)
        print(f"  Found {len(ds)} pairs in Tatoeba")

        for item in ds:
            src_text = item.get("sourceString", "")
            tgt_text = item.get("targetString", "")

            src_text = clean_text(src_text)
            tgt_text = clean_text(tgt_text)

            if is_valid_pair(src_text, tgt_text):
                pairs.extend(format_as_training_pairs(src_text, tgt_text, lang_code, lang_info["name"]))

            if len(pairs) >= max_pairs * 2:
                break

    except Exception as e:
        print(f"  Tatoeba failed: {e}")
        print(f"  Trying alternative source...")

    return pairs


def download_opus_books(lang_code: str, lang_info: dict, max_pairs: int) -> list[dict]:
    """Download from OPUS-Books dataset."""
    pairs = []

    print(f"  Downloading OPUS-Books en-{lang_code}...")
    try:
        ds = load_dataset(
            "Helsinki-NLP/opus_books",
            f"en-{lang_code}",
            split="train",
            trust_remote_code=True,
        )
        print(f"  Found {len(ds)} pairs in OPUS-Books")

        for item in ds:
            trans = item.get("translation", {})
            en_text = clean_text(trans.get("en", ""))
            other_text = clean_text(trans.get(lang_code, ""))

            if is_valid_pair(en_text, other_text):
                pairs.extend(format_as_training_pairs(en_text, other_text, lang_code, lang_info["name"]))

            if len(pairs) >= max_pairs * 2:
                break

    except Exception as e:
        print(f"  OPUS-Books failed: {e}")

    return pairs


def download_opus100(lang_code: str, lang_info: dict, max_pairs: int) -> list[dict]:
    """Download from OPUS-100 dataset (large, diverse parallel corpus)."""
    pairs = []

    print(f"  Downloading OPUS-100 en-{lang_code}...")
    try:
        ds = load_dataset(
            "Helsinki-NLP/opus-100",
            f"en-{lang_code}",
            split="train",
            trust_remote_code=True,
        )
        print(f"  Found {len(ds)} pairs in OPUS-100")

        # Shuffle and take a subset (OPUS-100 can be huge)
        indices = list(range(min(len(ds), max_pairs * 3)))
        random.shuffle(indices)

        for idx in indices:
            item = ds[idx]
            trans = item.get("translation", {})
            en_text = clean_text(trans.get("en", ""))
            other_text = clean_text(trans.get(lang_code, ""))

            if is_valid_pair(en_text, other_text):
                pairs.extend(format_as_training_pairs(en_text, other_text, lang_code, lang_info["name"]))

            if len(pairs) >= max_pairs * 2:
                break

    except Exception as e:
        print(f"  OPUS-100 failed: {e}")

    return pairs


def download_for_language(lang_code: str) -> list[dict]:
    """Try multiple sources to get enough parallel data for one language."""
    lang_info = LANG_PAIRS[lang_code]
    all_pairs = []
    target = TARGET_PER_LANG * 2  # x2 because we create both directions

    print(f"\n{'='*60}")
    print(f"  Downloading parallel data for: {lang_info['name']} (en-{lang_code})")
    print(f"  Target: {TARGET_PER_LANG} unique pairs ({target} training examples)")
    print(f"{'='*60}")

    # Try OPUS-100 first (largest)
    pairs = download_opus100(lang_code, lang_info, TARGET_PER_LANG)
    all_pairs.extend(pairs)
    print(f"  After OPUS-100: {len(all_pairs)} training pairs")

    # If not enough, try OPUS-Books
    if len(all_pairs) < target:
        remaining = (target - len(all_pairs)) // 2
        pairs = download_opus_books(lang_code, lang_info, remaining)
        all_pairs.extend(pairs)
        print(f"  After OPUS-Books: {len(all_pairs)} training pairs")

    # If still not enough, try Tatoeba
    if len(all_pairs) < target:
        remaining = (target - len(all_pairs)) // 2
        pairs = download_tatoeba(lang_code, lang_info, remaining)
        all_pairs.extend(pairs)
        print(f"  After Tatoeba: {len(all_pairs)} training pairs")

    # Deduplicate
    seen = set()
    unique = []
    for p in all_pairs:
        key = (p["input"], p["target"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"  After dedup: {len(unique)} unique training pairs")
    return unique


def merge_with_existing():
    """Merge downloaded parallel data with existing style data."""
    processed_dir = Path("data/processed")

    # Load existing data
    existing_train = pd.read_csv(processed_dir / "train_all.csv")
    existing_val = pd.read_csv(processed_dir / "val_all.csv")
    existing_test = pd.read_csv(processed_dir / "test_all.csv")

    print(f"\nExisting data:")
    print(f"  Train: {len(existing_train)}")
    print(f"  Val: {len(existing_val)}")
    print(f"  Test: {len(existing_test)}")

    # Load all downloaded parallel data
    parallel_dir = Path("data/raw/parallel")
    all_parallel = []
    for f in parallel_dir.glob("parallel_*.csv"):
        df = pd.read_csv(f)
        all_parallel.append(df)

    if not all_parallel:
        print("No parallel data found! Run the download first.")
        return

    parallel_df = pd.concat(all_parallel, ignore_index=True)
    print(f"\nDownloaded parallel data: {len(parallel_df)}")

    # Split parallel data: 90% train, 5% val, 5% test
    parallel_df = parallel_df.sample(frac=1, random_state=42).reset_index(drop=True)
    n = len(parallel_df)
    train_end = int(n * 0.90)
    val_end = int(n * 0.95)

    parallel_train = parallel_df[:train_end]
    parallel_val = parallel_df[train_end:val_end]
    parallel_test = parallel_df[val_end:]

    # Merge
    merged_train = pd.concat([existing_train, parallel_train], ignore_index=True)
    merged_val = pd.concat([existing_val, parallel_val], ignore_index=True)
    merged_test = pd.concat([existing_test, parallel_test], ignore_index=True)

    # Shuffle
    merged_train = merged_train.sample(frac=1, random_state=42).reset_index(drop=True)
    merged_val = merged_val.sample(frac=1, random_state=42).reset_index(drop=True)

    # Save
    merged_train.to_csv(processed_dir / "train_all.csv", index=False, quoting=csv.QUOTE_ALL)
    merged_val.to_csv(processed_dir / "val_all.csv", index=False, quoting=csv.QUOTE_ALL)
    merged_test.to_csv(processed_dir / "test_all.csv", index=False, quoting=csv.QUOTE_ALL)

    print(f"\nMerged dataset:")
    print(f"  Train: {len(merged_train)}")
    print(f"  Val: {len(merged_val)}")
    print(f"  Test: {len(merged_test)}")

    # Print source breakdown
    print(f"\nTrain set by source:")
    print(merged_train["source"].value_counts().to_string())

    print(f"\nTrain set by direction:")
    print(merged_train["direction"].value_counts().to_string())


def main():
    random.seed(42)

    output_dir = Path("data/raw/parallel")
    output_dir.mkdir(parents=True, exist_ok=True)

    for lang_code in LANG_PAIRS:
        pairs = download_for_language(lang_code)

        if pairs:
            df = pd.DataFrame(pairs)
            output_file = output_dir / f"parallel_{lang_code}.csv"
            df.to_csv(output_file, index=False, quoting=csv.QUOTE_ALL)
            print(f"  Saved to: {output_file}")

    print(f"\n{'='*60}")
    print(f"  Merging with existing style data...")
    print(f"{'='*60}")
    merge_with_existing()

    print(f"\n{'='*60}")
    print(f"  DONE!")
    print(f"  Next step: retrain mT5 on the merged dataset in Colab")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
