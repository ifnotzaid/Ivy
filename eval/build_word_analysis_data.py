"""Build the hand-curated Turkish word-analysis evaluation set.

The word-analysis runner checks only POS and base form, so this file keeps the
gold labels focused on fields we can defend by hand. The set is Turkish-only on
purpose: Turkish is the language we can verify most confidently, and evaluating
one language with clean labels is stronger than spreading weak labels across
several languages.

Run from the project root:
    py eval/build_word_analysis_data.py
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "eval" / "data" / "word_analysis_test.jsonl"
SEED_BACKUP = ROOT / "eval" / "data" / "word_analysis_test_seed.jsonl"


SENTENCES: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Ayşe sabah erkenden okula gitti.",
        [
            ("Ayşe", "noun", "Ayşe"),
            ("sabah", "noun", "sabah"),
            ("erkenden", "adv", "erken"),
            ("okula", "noun", "okul"),
            ("gitti", "verb", "gitmek"),
        ],
    ),
    (
        "Deniz çantasına su ve elma koydu.",
        [
            ("Deniz", "noun", "Deniz"),
            ("çantasına", "noun", "çanta"),
            ("su", "noun", "su"),
            ("ve", "conj", "ve"),
            ("elma", "noun", "elma"),
            ("koydu", "verb", "koymak"),
        ],
    ),
    (
        "Hava çok soğuk olduğu için kalın ceketini giydi.",
        [
            ("Hava", "noun", "hava"),
            ("çok", "adv", "çok"),
            ("soğuk", "adj", "soğuk"),
            ("olduğu", "verb", "olmak"),
            ("için", "prep", "için"),
            ("kalın", "adj", "kalın"),
            ("ceketini", "noun", "ceket"),
            ("giydi", "verb", "giymek"),
        ],
    ),
    (
        "Öğrenciler sessizce sınıfa girdiler.",
        [
            ("Öğrenciler", "noun", "öğrenci"),
            ("sessizce", "adv", "sessiz"),
            ("sınıfa", "noun", "sınıf"),
            ("girdiler", "verb", "girmek"),
        ],
    ),
    (
        "Küçük kedi bahçede uyuyordu.",
        [
            ("Küçük", "adj", "küçük"),
            ("kedi", "noun", "kedi"),
            ("bahçede", "noun", "bahçe"),
            ("uyuyordu", "verb", "uyumak"),
        ],
    ),
    (
        "Arkadaşım bana uzun bir mektup yazdı.",
        [
            ("Arkadaşım", "noun", "arkadaş"),
            ("bana", "pron", "ben"),
            ("uzun", "adj", "uzun"),
            ("bir", "det", "bir"),
            ("mektup", "noun", "mektup"),
            ("yazdı", "verb", "yazmak"),
        ],
    ),
    (
        "Annem mutfakta lezzetli çorba pişiriyor.",
        [
            ("Annem", "noun", "anne"),
            ("mutfakta", "noun", "mutfak"),
            ("lezzetli", "adj", "lezzetli"),
            ("çorba", "noun", "çorba"),
            ("pişiriyor", "verb", "pişirmek"),
        ],
    ),
    (
        "Çocuklar parkta hızlıca koşarken yağmur başladı.",
        [
            ("Çocuklar", "noun", "çocuk"),
            ("parkta", "noun", "park"),
            ("hızlıca", "adv", "hızlı"),
            ("koşarken", "verb", "koşmak"),
            ("yağmur", "noun", "yağmur"),
            ("başladı", "verb", "başlamak"),
        ],
    ),
    (
        "Yaşlı adam dikkatlice eski kitabı okudu.",
        [
            ("Yaşlı", "adj", "yaşlı"),
            ("adam", "noun", "adam"),
            ("dikkatlice", "adv", "dikkatli"),
            ("eski", "adj", "eski"),
            ("kitabı", "noun", "kitap"),
            ("okudu", "verb", "okumak"),
        ],
    ),
    (
        "Bugün toplantıya geç kaldığım için üzgünüm.",
        [
            ("Bugün", "adv", "bugün"),
            ("toplantıya", "noun", "toplantı"),
            ("geç", "adv", "geç"),
            ("kaldığım", "verb", "kalmak"),
            ("için", "prep", "için"),
            ("üzgünüm", "adj", "üzgün"),
        ],
    ),
    (
        "Kardeşim yeni bisikletini garajda sakladı.",
        [
            ("Kardeşim", "noun", "kardeş"),
            ("yeni", "adj", "yeni"),
            ("bisikletini", "noun", "bisiklet"),
            ("garajda", "noun", "garaj"),
            ("sakladı", "verb", "saklamak"),
        ],
    ),
    (
        "Otobüs durağında sabırsızca bekleyen kadın gülümsedi.",
        [
            ("Otobüs", "noun", "otobüs"),
            ("durağında", "noun", "durak"),
            ("sabırsızca", "adv", "sabırsız"),
            ("bekleyen", "verb", "beklemek"),
            ("kadın", "noun", "kadın"),
            ("gülümsedi", "verb", "gülümsemek"),
        ],
    ),
    (
        "Bu soruyu dikkatle cevaplamanız gerekiyor.",
        [
            ("Bu", "det", "bu"),
            ("soruyu", "noun", "soru"),
            ("dikkatle", "adv", "dikkat"),
            ("cevaplamanız", "verb", "cevaplamak"),
            ("gerekiyor", "verb", "gerekmek"),
        ],
    ),
    (
        "Kalabalık sokakta sessizce yürüdük.",
        [
            ("Kalabalık", "adj", "kalabalık"),
            ("sokakta", "noun", "sokak"),
            ("sessizce", "adv", "sessiz"),
            ("yürüdük", "verb", "yürümek"),
        ],
    ),
    (
        "Misafirler salonda kahve içip sohbet ettiler.",
        [
            ("Misafirler", "noun", "misafir"),
            ("salonda", "noun", "salon"),
            ("kahve", "noun", "kahve"),
            ("içip", "verb", "içmek"),
            ("sohbet", "noun", "sohbet"),
            ("ettiler", "verb", "etmek"),
        ],
    ),
    (
        "Telefonum masada aniden titremeye başladı.",
        [
            ("Telefonum", "noun", "telefon"),
            ("masada", "noun", "masa"),
            ("aniden", "adv", "aniden"),
            ("titremeye", "verb", "titremek"),
            ("başladı", "verb", "başlamak"),
        ],
    ),
    (
        "Genç doktor hastayı dikkatlice muayene etti.",
        [
            ("Genç", "adj", "genç"),
            ("doktor", "noun", "doktor"),
            ("hastayı", "noun", "hasta"),
            ("dikkatlice", "adv", "dikkatli"),
            ("muayene", "noun", "muayene"),
            ("etti", "verb", "etmek"),
        ],
    ),
    (
        "Çiçekler ilkbaharda güzelce açtı.",
        [
            ("Çiçekler", "noun", "çiçek"),
            ("ilkbaharda", "noun", "ilkbahar"),
            ("güzelce", "adv", "güzel"),
            ("açtı", "verb", "açmak"),
        ],
    ),
    (
        "Ben seni dün aradım.",
        [
            ("Ben", "pron", "ben"),
            ("seni", "pron", "sen"),
            ("aradım", "verb", "aramak"),
        ],
    ),
]


def build_entries() -> list[dict[str, str]]:
    entries = []
    for sentence, words in SENTENCES:
        for word, pos, base in words:
            entries.append(
                {
                    "sentence": sentence,
                    "word": word,
                    "language": "tr",
                    "expected_pos": pos,
                    "expected_base_form": base,
                }
            )
    return entries


def main() -> None:
    entries = build_entries()
    if len(entries) != 100:
        raise SystemExit(f"Expected exactly 100 entries, got {len(entries)}")

    if OUT_PATH.exists() and not SEED_BACKUP.exists():
        SEED_BACKUP.write_text(OUT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    with OUT_PATH.open("w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Wrote {len(entries)} entries to {OUT_PATH}")
    print(f"Backup seed file: {SEED_BACKUP if SEED_BACKUP.exists() else 'not created'}")


if __name__ == "__main__":
    main()
