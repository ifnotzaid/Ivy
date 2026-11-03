"""Describe model checkpoints and zip downloads in a folder, without loading them.

Usage (from the Ivy folder, with the virtual environment active):
    python -I scripts/inspect_checkpoints.py "check this"

For each file it prints what it is:
  - .safetensors: tensor count, data type, parameter count, a guess at the model
    type from tensor names, and a fingerprint to spot duplicate copies.
  - .zip: every entry inside, and the text of small config/tokenizer/training files.
  - .pt and unfinished downloads: size only. .pt files are never opened, because
    loading them runs pickled code.
Nothing is extracted, changed or executed.
"""

import hashlib
import json
import struct
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

TEXT_SUFFIXES = {".json", ".txt", ".md", ".yaml", ".yml", ".cfg", ".csv"}
MAX_TEXT_BYTES = 200_000
MAX_PRINT_CHARS = 2500
SAMPLE_BYTES = 8 * 1024 * 1024


def human(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def fingerprint(path):
    """Hash of the size, first 8 MB and last 8 MB: equal files give equal fingerprints."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            f.seek(max(size - SAMPLE_BYTES, SAMPLE_BYTES))
            h.update(f.read(SAMPLE_BYTES))
    return h.hexdigest()[:16]


def guess_model(names):
    joined = " ".join(names[:400])
    if "encoder.block" in joined or "decoder.block" in joined:
        kind = "T5 / mT5 (encoder-decoder, translates or rewrites text)"
    elif "bert." in joined or "embeddings.word_embeddings" in joined:
        kind = "BERT-style encoder"
    elif "model.encoder.layers" in joined and "model.decoder.layers" in joined:
        kind = "Marian / BART-style encoder-decoder"
    else:
        kind = "unknown architecture"
    if any(n.startswith("classifier") or ".classifier." in n for n in names):
        kind += ", with a classification head"
    return kind


def inspect_safetensors(path):
    with path.open("rb") as f:
        header_len = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(header_len))
    meta = header.pop("__metadata__", {})
    dtypes = defaultdict(int)
    params = 0
    for info in header.values():
        count = 1
        for dim in info["shape"]:
            count *= dim
        params += count
        dtypes[info["dtype"]] += 1
    names = sorted(header)
    print(f"  tensors: {len(names)}   parameters: {params:,}   dtypes: {dict(dtypes)}")
    print(f"  looks like: {guess_model(names)}")
    print("  first tensor names: " + ", ".join(names[:6]))
    if meta:
        print(f"  metadata: {meta}")


def inspect_zip(path):
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        print("  not a valid zip (incomplete or damaged download)")
        return
    with zf:
        for info in zf.infolist():
            print(f"  - {info.filename}  ({human(info.file_size)})")
        for info in zf.infolist():
            if info.is_dir() or info.file_size > MAX_TEXT_BYTES:
                continue
            if Path(info.filename).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = zf.read(info).decode("utf-8", errors="replace")
            if len(text) > MAX_PRINT_CHARS:
                text = text[:MAX_PRINT_CHARS] + "\n    [... cut ...]"
            print(f"\n  >>> {info.filename}")
            print("    " + text.replace("\n", "\n    "))


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    folder = Path(sys.argv[1])
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    groups = defaultdict(list)
    for path in files:
        size = path.stat().st_size
        print(f"\n=== {path.relative_to(folder)}  ({human(size)})")
        suffix = path.suffix.lower()
        try:
            if suffix == ".safetensors":
                inspect_safetensors(path)
                groups[fingerprint(path)].append(path.name)
            elif suffix == ".zip":
                inspect_zip(path)
                groups[fingerprint(path)].append(path.name)
            elif suffix == ".pt":
                print("  PyTorch file, not opened (optimizer.pt holds training state, not a usable model)")
                groups[fingerprint(path)].append(path.name)
            elif suffix in {".opdownload", ".crdownload", ".part"}:
                print("  unfinished browser download: safe to delete")
            else:
                print("  not inspected")
        except Exception as exc:  # keep going if one file is damaged
            print(f"  could not read: {exc}")
    print("\n=== Duplicates (same size and same content samples)")
    found = False
    for names in groups.values():
        if len(names) > 1:
            found = True
            print("  same file: " + " | ".join(names))
    if not found:
        print("  none")


if __name__ == "__main__":
    main()
