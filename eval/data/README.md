# Evaluation Data

These JSONL files are seed sets for validating the evaluation harness.

Before final submission, expand them to the target sizes:

- `translation_test.jsonl`: 50 examples per direction, 300 total.
- `style_test.jsonl`: 30-40 examples per language per style, roughly 400 total.
- `word_analysis_test.jsonl`: 100 hand-annotated Turkish words.

Current expanded set sizes:

- `translation_test.jsonl`: 300 examples.
- `style_test.jsonl`: 432 examples.
- `word_analysis_test.jsonl`: 100 examples.

The raw Tatoeba downloads live in `eval/data/tatoeba/` locally and are ignored by git because they are large. The generated JSONL files are the datasets to keep with the project.

Builder scripts:

- `py eval/build_translation_data.py`
- `py eval/build_style_data.py`
- `py eval/build_word_analysis_data.py`

Run the harness from the project root:

```powershell
py -m eval.run_all
```

For a dependency-free smoke test that only verifies report generation:

```powershell
py -m eval.run_all --skip-translation --skip-style --skip-word-analysis --skip-latency
```
