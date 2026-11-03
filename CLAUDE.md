# Ivy — notes for Claude

Ivy is a style-aware translator for language learners (English, Turkish, German, Russian) with
formal / neutral / casual registers, word-by-word analysis, vocabulary, flashcards (SM-2),
CEFR stories with audio, cloze practice and shared flashcard sets. Capstone project, İstinye
University. Owner: Zaid (GitHub `ifnotzaid`). Explain things simply; Zaid is not always at a
terminal and works on Windows (cmd).

## How it runs

- Backend: `app/app.py` (Flask), `app/auth_routes.py` (login, vocab, sets, friends, stories,
  practice), `app/database.py` (SQLite at `data/translator.db`), `app/word_analysis.py`.
- Translation: Helsinki-NLP opus-mt models (downloaded on first run), then Gemini 2.5 Flash
  restyles to the chosen register. Word analysis, stories and practice also use Gemini.
- Tone bars: a fine-tuned multilingual BERT classifier loaded from
  `models/style-classifier-final/`. Without it, every tone reads about 33/33/34%.
- Story audio: Google Cloud Text-to-Speech (needs `GOOGLE_APPLICATION_CREDENTIALS`), optional.
- Frontend: `app/templates/index.html` and `sets.html`, styles in `app/static/css/`, scripts in
  `app/static/js/`. Follow `DESIGN.md` for any UI change.
- Settings: `.env` in the repo root (copy of `.env.example`): `GEMINI_API_KEY`,
  `FLASK_SECRET_KEY`, optional TTS settings.

On Zaid's Windows machine (`C:\Users\zaid\Ivy`) the Python packages are installed in the main
Python 3.10 install, not in a `.venv`. Start the app with `python app\app.py` and open
http://localhost:5000. The startup summary says whether Gemini and the classifier loaded.

## Rules

- Anything from a user or an AI response goes through `escapeHtml()` before `innerHTML`.
  Public sets are shown to other users.
- Never commit `.env`, `models/`, `check this/`, model weights or zips. They are gitignored.
- Work on a branch and open a pull request; don't commit to `main` directly.

## Where things stand (Nov 3, 2026)

- **Branch `frontend-redesign`, pull request #1 open, not merged**
  (https://github.com/ifnotzaid/Ivy/pull/1). It fixes a stored-XSS bug on the Community page,
  polishes the UI (phone layout, tap/keyboard word details, contrast, accessibility, light
  theme on `/sets`, Formal colour changed from violet to cyan), moves CSS/JS into
  `app/static/`, and adds `DESIGN.md`, `docs/frontend-review.md`,
  `scripts/inspect_checkpoints.py` and two design skills in `.claude/skills/`. Zaid ran the
  app locally and it works. Merge after a final check of translations, stories and the
  classifier.
- **Classifier installed (done Nov 3, 2026).** `models\style-classifier-final\` holds the
  trained classifier (BertForSequenceClassification, 178M params, labels 0 formal / 1 casual /
  2 neutral, ~679 MB model.safetensors, tokenizer.json, tokenizer_config.json,
  training_args.bin), extracted from `C:\Users\zaid\Ivy\style-classifier-final.zip`. The app
  prints "Classifier: loaded" with no LayerNorm key warnings (the old `gamma`/`beta` names load
  fine, so no renaming is needed). `/api/detect-style` scored a formal, a casual and a neutral
  test sentence each above 99% for the right tone.
  - Copies: the zip in the repo folder, plus an identical older copy at
    `C:\Users\zaid\Desktop\studying stuff\8\project backup\models\style-classifier-final\`.
    Both are on the same machine, so remind Zaid to upload the zip to Google Drive.
  - `models\config.json` (loose, not in a subfolder) is a stray mT5 translator config. The
    app does not use it; safe to delete once Zaid agrees.
- **Classifier training notebook**: Zaid's Colab notebook (mBERT, 3 epochs, lr 2e-5,
  batch 32, max_length 128, 85/15 split with random_state 42, 88.8% validation accuracy) was
  shared in chat but is not in the repo yet. The training data is in the repo:
  `data/processed/classifier/classifier_all.csv` (13,800 rows). If the model is ever lost,
  retraining takes ~6 minutes on a Colab GPU.
- **Leftover downloads**: `C:\Users\zaid\Ivy\check this\` (~50 GB) and
  `mt5-style-translator-final.zip` are an older mT5-base "style translator" Ivy no longer
  uses. Duplicates and training state only; safe to delete once Zaid agrees. Originals are on
  his Google Drive (`MyDrive/mt5-style-translator-v2`).
- **Gemini billing**: AI Studio project `style-translator` is on the free tier. "Prepay
  required" only applies to upgrading (min $5 prepaid credit). Stay free unless requests start
  failing with 429 rate-limit errors.

## Ideas not started

- Show a friendly "daily limit reached, try again later" message when Gemini returns 429.
- Add the classifier training notebook to `notebooks/`.
- Set up Google Cloud TTS credentials so story audio works.
