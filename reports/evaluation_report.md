# ivy Evaluation Report
Generated: 2026-05-14 23:39:38

## Summary
- Translation: average pipeline BLEU 53.32 (baseline 53.32, delta +0.00).
- Style classifier: macro-F1 0.7667 across 432 examples.
- Word analysis: POS accuracy 98.00%, base-form accuracy 88.00% (found 100/100).

## Translation Quality

| Pair | n | Baseline BLEU | Pipeline BLEU | Delta | Baseline chrF++ | Pipeline chrF++ |
|------|---|---------------|---------------|-------|---------------|---------------|
| de->en | 50 | 62.78 | 62.78 | +0.00 | 72.92 | 72.92 |
| en->de | 50 | 51.62 | 51.62 | +0.00 | 67.70 | 67.70 |
| en->ru | 50 | 46.70 | 46.70 | +0.00 | 62.53 | 62.53 |
| en->tr | 50 | 44.85 | 44.85 | +0.00 | 69.37 | 69.37 |
| ru->en | 50 | 56.75 | 56.75 | +0.00 | 70.11 | 70.11 |
| tr->en | 50 | 57.23 | 57.23 | +0.00 | 72.61 | 72.61 |

## Style Classifier

### de
n=108, accuracy=0.7685, macro-F1=0.7655

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| formal | 1.0000 | 0.5000 | 0.6667 | 36 |
| neutral | 0.5965 | 0.9444 | 0.7312 | 36 |
| casual | 0.9394 | 0.8611 | 0.8986 | 36 |

Confusion matrix:

| actual \ predicted | formal | neutral | casual |
|---|---|---|---|
| formal | 18 | 18 | 0 |
| neutral | 0 | 34 | 2 |
| casual | 0 | 5 | 31 |

### en
n=108, accuracy=0.8611, macro-F1=0.8640

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| formal | 1.0000 | 0.8889 | 0.9412 | 36 |
| neutral | 0.7442 | 0.8889 | 0.8101 | 36 |
| casual | 0.8788 | 0.8056 | 0.8406 | 36 |

Confusion matrix:

| actual \ predicted | formal | neutral | casual |
|---|---|---|---|
| formal | 32 | 4 | 0 |
| neutral | 0 | 32 | 4 |
| casual | 0 | 7 | 29 |

### ru
n=108, accuracy=0.7500, macro-F1=0.7533

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| formal | 1.0000 | 0.5556 | 0.7143 | 36 |
| neutral | 0.5789 | 0.9167 | 0.7097 | 36 |
| casual | 0.9032 | 0.7778 | 0.8358 | 36 |

Confusion matrix:

| actual \ predicted | formal | neutral | casual |
|---|---|---|---|
| formal | 20 | 16 | 0 |
| neutral | 0 | 33 | 3 |
| casual | 0 | 8 | 28 |

### tr
n=108, accuracy=0.6667, macro-F1=0.6679

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| formal | 1.0000 | 0.4722 | 0.6415 | 36 |
| neutral | 0.5000 | 0.9722 | 0.6604 | 36 |
| casual | 0.9524 | 0.5556 | 0.7018 | 36 |

Confusion matrix:

| actual \ predicted | formal | neutral | casual |
|---|---|---|---|
| formal | 17 | 19 | 0 |
| neutral | 0 | 35 | 1 |
| casual | 0 | 16 | 20 |

### overall
n=432, accuracy=0.7616, macro-F1=0.7667

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| formal | 1.0000 | 0.6042 | 0.7532 | 144 |
| neutral | 0.5903 | 0.9306 | 0.7224 | 144 |
| casual | 0.9153 | 0.7500 | 0.8244 | 144 |

Confusion matrix:

| actual \ predicted | formal | neutral | casual |
|---|---|---|---|
| formal | 87 | 57 | 0 |
| neutral | 0 | 134 | 10 |
| casual | 0 | 36 | 108 |


## Word Analysis

- n: 100
- found: 100
- coverage: 100.00%
- POS accuracy: 98.00%
- base-form accuracy: 88.00%
- mismatches: 13

Sample mismatches:

| Word | Expected POS | Predicted POS | Expected Base | Predicted Base |
|------|--------------|---------------|---------------|----------------|
| girdiler | verb | verb | girmek | gir |
| uyuyordu | verb | verb | uyumak | uyu |
| hızlıca | adv | adv | hızlı | hızlıca |
| okudu | verb | verb | okumak | oku |
| geç | adv | adj | geç | geç |
| sabırsızca | adv | adv | sabırsız | sabırsızca |
| bekleyen | verb | adj | beklemek | bekle |
| gülümsedi | verb | verb | gülümsemek | gülümse |
| sessizce | adv | adv | sessiz | sessizce |
| titremeye | verb | verb | titremek | titre |

## Latency (ms)

No latency results.

## Dataset Sizes

- translation examples: 300 (target for final defense: 300)
- style examples: 432 (target for final defense: ~400)
- word-analysis examples: 100 (target for final defense: 100)
