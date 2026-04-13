# Style-Aware Multilingual Translator

An AI translation system that preserves tone and formality across languages.  
Supports **English ↔ Turkish**, **English ↔ Russian**, **English ↔ German** with 3 style modes: formal, casual, neutral.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate training data (run for each language)
python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang turkish
python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang russian
python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang german

# 3. Preprocess into training format
python scripts/preprocess_data.py --lang all

# 4. Train style classifier (local or Colab)
python scripts/train_classifier.py

# 5. Train mT5 translation model (Colab recommended)
# See notebooks/train_mt5.ipynb

# 6. Run the web app
streamlit run app/app.py
```

## Project Structure

```
├── data/raw/              # Raw generated data (JSONL)
├── data/processed/        # Clean train/val/test splits (CSV)
├── models/                # Saved model checkpoints
├── notebooks/             # Colab training notebooks
├── scripts/               # Data generation & preprocessing
├── app/                   # Streamlit web application
└── requirements.txt
```

## Architecture

See `architecture.png` for the full system diagram.

## Tech Stack

- **Model**: mT5-small (300M params) fine-tuned with style token prefixes
- **Style Classifier**: bert-base-multilingual-cased
- **Framework**: PyTorch + HuggingFace Transformers
- **Web UI**: Streamlit
- **Data Generation**: Gemini 2.0 Flash API
