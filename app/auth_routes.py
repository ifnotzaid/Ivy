"""
auth_routes.py — User authentication, vocabulary, and flashcard routes.

Register this blueprint in app.py with:
    from auth_routes import auth_bp
    app.register_blueprint(auth_bp)
"""

from flask import Blueprint, request, jsonify, session

import gemini
from translation import LANGUAGES as LANGUAGE_NAMES
from database import (
    create_user, verify_user, get_user_by_id,
    save_word, get_vocabulary, delete_word, get_vocab_stats,
    get_due_flashcards, review_flashcard,
    create_flashcard_set, get_user_sets, get_set_by_id,
    get_set_words, add_word_to_set, remove_word_from_set,
    delete_flashcard_set, update_set_visibility, fork_public_set,
    send_friend_request, accept_friend_request, reject_friend_request, remove_friend,
    get_friends, get_pending_requests, get_friend_public_sets,
    get_public_sets_browse, save_story, get_saved_stories,
    get_saved_story, delete_saved_story,
    get_vocab_count_for_lang, build_cloze_items_for_user, find_vocab_id_by_word,
)

auth_bp = Blueprint("auth", __name__)


def _translate_cloze_batch(items: list[dict], target_lang: str, support_lang: str) -> list[dict]:
    """
    Translate cloze sentences in one Gemini call.
    Returns {"translation": str, "highlight": str} rows, with empty strings on failure
    so the quiz remains playable.
    """
    n = len(items or [])
    if not n or target_lang == support_lang:
        return [{"translation": "", "highlight": ""} for _ in range(n)]
    if not gemini.is_ready():
        return [{"translation": "", "highlight": ""} for _ in range(n)]

    target_name = LANGUAGE_NAMES.get(target_lang, target_lang)
    support_name = LANGUAGE_NAMES.get(support_lang, support_lang)
    numbered = []
    for i, item in enumerate(items):
        answer = (item.get("answer") or "").strip()
        full_sentence = (item.get("sentence") or "").replace("___", answer, 1)
        meaning = (item.get("meaning") or "").strip()
        meaning_hint = f' | Meaning hint: "{meaning}"' if meaning else ""
        numbered.append(f'{i + 1}. Sentence: "{full_sentence}" | Target word: "{answer}"{meaning_hint}')
    prompt = f"""For each {target_name} sentence below, translate it into natural {support_name} and identify which {support_name} word or phrase corresponds to the target word.

Items:
{chr(10).join(numbered)}

Rules:
- "translation" is the complete, natural {support_name} sentence. No blanks or placeholders.
- "highlight" is the exact substring from "translation" that conveys the target word's meaning. It must appear verbatim in "translation".
- Usually the highlight is 1 to 3 words.
- The items array must have exactly {n} entries in input order.
- Return only JSON in this exact shape: {{"items": [{{"translation": "...", "highlight": "..."}}, ...]}}

No commentary, no markdown fences."""
    try:
        payload = gemini.extract_json_payload(gemini.generate(prompt, temperature=0.2, max_tokens=2200))
        rows = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return [{"translation": "", "highlight": ""} for _ in range(n)]
        cleaned = []
        for row in rows[:n]:
            if isinstance(row, dict):
                cleaned.append({
                    "translation": str(row.get("translation", "")).strip(),
                    "highlight": str(row.get("highlight", "")).strip(),
                })
            else:
                cleaned.append({"translation": "", "highlight": ""})
        while len(cleaned) < n:
            cleaned.append({"translation": "", "highlight": ""})
        return cleaned
    except Exception as exc:
        print(f"[practice] cloze translation skipped: {exc}")
        return [{"translation": "", "highlight": ""} for _ in range(n)]


def _add_cloze_translations(items: list[dict], target_lang: str) -> None:
    """Attach support-language translations to cloze items in-place."""
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for index, item in enumerate(items):
        item["translation"] = ""
        item["highlight"] = ""
        support_lang = (item.get("support_lang") or "en").strip()
        if support_lang == target_lang:
            continue
        grouped.setdefault(support_lang, []).append((index, item))

    for support_lang, indexed_items in grouped.items():
        translations = _translate_cloze_batch([item for _, item in indexed_items], target_lang, support_lang)
        for (item_index, _), payload in zip(indexed_items, translations):
            items[item_index]["translation"] = payload.get("translation", "")
            items[item_index]["highlight"] = payload.get("highlight", "")


def get_current_user():
    """Get current logged-in user from session."""
    user_id = session.get("user_id")
    if user_id:
        return get_user_by_id(user_id)
    return None


# ──────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────
@auth_bp.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    name = data.get("name", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if "@" not in email:
        return jsonify({"error": "Invalid email"}), 400

    user = create_user(email, password, name)
    if user is None:
        return jsonify({"error": "Email already registered"}), 409

    session["user_id"] = user["id"]
    return jsonify({"user": user})


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = verify_user(email, password)
    if user is None:
        return jsonify({"error": "Invalid email or password"}), 401

    session["user_id"] = user["id"]
    return jsonify({"user": user})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    user = get_current_user()
    if user:
        return jsonify({"user": user})
    return jsonify({"user": None}), 401


# ──────────────────────────────────────────────
# Vocabulary routes
# ──────────────────────────────────────────────
@auth_bp.route("/api/vocab/save", methods=["POST"])
def api_save_word():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    vocab_id = save_word(user["id"], data)
    return jsonify({"vocab_id": vocab_id})


@auth_bp.route("/api/vocab/list", methods=["GET"])
def api_list_vocab():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    language = request.args.get("lang")
    words = get_vocabulary(user["id"], language)
    return jsonify({"words": words})


@auth_bp.route("/api/vocab/delete/<int:vocab_id>", methods=["DELETE"])
def api_delete_word(vocab_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    success = delete_word(user["id"], vocab_id)
    return jsonify({"ok": success})


@auth_bp.route("/api/vocab/stats", methods=["GET"])
def api_vocab_stats():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    stats = get_vocab_stats(user["id"])
    return jsonify(stats)


@auth_bp.route("/api/vocab/count", methods=["GET"])
def api_vocab_count():
    """Lightweight per-language counts for adaptive story personalization."""
    user = get_current_user()
    if not user:
        return jsonify({"counts": {}})

    counts = {}
    for lang in ("tr", "de", "ru", "en"):
        counts[lang] = get_vocab_count_for_lang(user["id"], lang)
    return jsonify({"counts": counts})


# ──────────────────────────────────────────────
# Flashcard routes
# ──────────────────────────────────────────────
@auth_bp.route("/api/flashcards/due", methods=["GET"])
def api_due_flashcards():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    language = request.args.get("lang")
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    set_id = request.args.get("set_id")
    try:
        set_id = int(set_id) if set_id else None
    except (TypeError, ValueError):
        set_id = None
    cards = get_due_flashcards(user["id"], language, limit, set_id=set_id)
    return jsonify({"cards": cards})


@auth_bp.route("/api/flashcards/review", methods=["POST"])
def api_review_flashcard():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    vocab_id = data.get("vocab_id")
    quality = data.get("quality", 0)  # 0-5

    if vocab_id is None:
        return jsonify({"error": "vocab_id required"}), 400

    result = review_flashcard(user["id"], vocab_id, quality)
    return jsonify(result)

# ──────────────────────────────────────────────
# Flashcard Set routes
# ──────────────────────────────────────────────

@auth_bp.route("/api/sets/create", methods=["POST"])
def api_create_set():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Set name required"}), 400
    set_id = create_flashcard_set(
        user["id"], name,
        data.get("description", ""),
        data.get("target_lang", ""),
        data.get("is_public", False)
    )
    return jsonify({"set_id": set_id})


@auth_bp.route("/api/sets/list", methods=["GET"])
def api_list_sets():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    sets = get_user_sets(user["id"])
    return jsonify({"sets": sets})


@auth_bp.route("/api/sets/<int:set_id>", methods=["GET"])
def api_get_set(set_id):
    user = get_current_user()
    set_data = get_set_by_id(set_id)
    if not set_data:
        return jsonify({"error": "Set not found"}), 404
    # Check access: own set or public set
    if set_data["user_id"] != (user["id"] if user else -1) and not set_data["is_public"]:
        return jsonify({"error": "Access denied"}), 403
    words = get_set_words(set_id)
    return jsonify({"set": set_data, "words": words})


@auth_bp.route("/api/sets/<int:set_id>/add", methods=["POST"])
def api_add_to_set(set_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    data = request.get_json(silent=True) or {}
    vocab_id = data.get("vocab_id")
    if not vocab_id:
        return jsonify({"error": "vocab_id required"}), 400
    set_data = get_set_by_id(set_id)
    if not set_data or set_data["user_id"] != user["id"]:
        return jsonify({"error": "Not your set"}), 403
    add_word_to_set(set_id, vocab_id)
    return jsonify({"ok": True})


@auth_bp.route("/api/sets/<int:set_id>/remove", methods=["POST"])
def api_remove_from_set(set_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    data = request.get_json(silent=True) or {}
    vocab_id = data.get("vocab_id")
    set_data = get_set_by_id(set_id)
    if not set_data or set_data["user_id"] != user["id"]:
        return jsonify({"error": "Not your set"}), 403
    remove_word_from_set(set_id, vocab_id)
    return jsonify({"ok": True})


@auth_bp.route("/api/sets/<int:set_id>/delete", methods=["DELETE"])
def api_delete_set(set_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    delete_flashcard_set(user["id"], set_id)
    return jsonify({"ok": True})


@auth_bp.route("/api/sets/<int:set_id>/visibility", methods=["POST"])
def api_set_visibility(set_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    data = request.get_json(silent=True) or {}
    update_set_visibility(user["id"], set_id, data.get("is_public", False))
    return jsonify({"ok": True})


@auth_bp.route("/api/sets/<int:set_id>/fork", methods=["POST"])
def api_fork_set(set_id):
    """Snapshot-fork a public set into the current user's library."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    try:
        result = fork_public_set(set_id, user["id"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(result)


@auth_bp.route("/api/sets/browse", methods=["GET"])
def api_browse_sets():
    user = get_current_user()
    user_id = user["id"] if user else 0
    sets = get_public_sets_browse(user_id)
    return jsonify({"sets": sets})


# ──────────────────────────────────────────────
# Friend routes
# ──────────────────────────────────────────────

@auth_bp.route("/api/friends/request", methods=["POST"])
def api_friend_request():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    data = request.get_json(silent=True) or {}
    email = data.get("email", "")
    if not email:
        return jsonify({"error": "Email required"}), 400
    result = send_friend_request(user["id"], email)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@auth_bp.route("/api/friends/accept/<int:friendship_id>", methods=["POST"])
def api_accept_friend(friendship_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    accept_friend_request(user["id"], friendship_id)
    return jsonify({"ok": True})


@auth_bp.route("/api/friends/reject/<int:friendship_id>", methods=["POST"])
def api_reject_friend(friendship_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    reject_friend_request(user["id"], friendship_id)
    return jsonify({"ok": True})


@auth_bp.route("/api/friends/remove/<int:friendship_id>", methods=["POST", "DELETE"])
def api_remove_friend(friendship_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    if not remove_friend(user["id"], friendship_id):
        return jsonify({"error": "Friendship not found"}), 404
    return jsonify({"ok": True})


@auth_bp.route("/api/friends/list", methods=["GET"])
def api_list_friends():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    friends = get_friends(user["id"])
    pending = get_pending_requests(user["id"])
    return jsonify({"friends": friends, "pending": pending})


@auth_bp.route("/api/friends/<int:friend_id>/sets", methods=["GET"])
def api_friend_sets(friend_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
    # Verify they're actually friends
    friends = get_friends(user["id"])
    friend_ids = [f["friend_id"] for f in friends]
    if friend_id not in friend_ids:
        return jsonify({"error": "Not your friend"}), 403
    sets = get_friend_public_sets(friend_id)
    return jsonify({"sets": sets})


# —— Saved stories routes —————————————————————————————————

@auth_bp.route("/api/stories/save", methods=["POST"])
def api_save_story():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    story_text = data.get("story_text", "").strip()
    title = data.get("title", "").strip()

    if not story_text or not title:
        return jsonify({"error": "Story title and text are required"}), 400

    story_id = save_story(user["id"], data)
    return jsonify({"story_id": story_id})


@auth_bp.route("/api/stories/list", methods=["GET"])
def api_list_saved_stories():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    target_lang = request.args.get("lang")
    stories = get_saved_stories(user["id"], target_lang)
    return jsonify({"stories": stories})


@auth_bp.route("/api/stories/<int:story_id>", methods=["GET"])
def api_get_saved_story(story_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    story = get_saved_story(user["id"], story_id)
    if not story:
        return jsonify({"error": "Story not found"}), 404

    return jsonify({"story": story})


@auth_bp.route("/api/stories/<int:story_id>", methods=["DELETE"])
def api_delete_saved_story(story_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    deleted = delete_saved_story(user["id"], story_id)
    return jsonify({"ok": deleted})


# Practice / cloze quiz routes
@auth_bp.route("/api/practice/build", methods=["POST"])
def api_practice_build():
    """Assemble a multiple-choice cloze quiz from the user's saved stories."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    target_lang = (data.get("target_lang") or "").strip()
    if target_lang not in ("tr", "de", "ru", "en"):
        return jsonify({"error": "Unsupported language"}), 400

    story_id = data.get("story_id")
    try:
        parsed_story_id = int(story_id) if story_id else None
    except (TypeError, ValueError):
        parsed_story_id = None
    cefr_level = (data.get("cefr_level") or "").strip().upper() or None
    try:
        limit = max(1, min(int(data.get("limit", 10)), 25))
    except (TypeError, ValueError):
        limit = 10

    items = build_cloze_items_for_user(
        user_id=user["id"],
        target_lang=target_lang,
        cefr_level=cefr_level,
        story_id=parsed_story_id,
        limit=limit,
    )
    _add_cloze_translations(items, target_lang)
    return jsonify({
        "items": items,
        "target_lang": target_lang,
        "source": "story" if parsed_story_id else "all",
    })


@auth_bp.route("/api/practice/answer", methods=["POST"])
def api_practice_answer():
    """Record a cloze answer and feed the flashcard SRS when possible."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    target_lang = (data.get("target_lang") or "").strip()
    correct = bool(data.get("correct"))

    if not word or target_lang not in ("tr", "de", "ru", "en"):
        return jsonify({"error": "word and target_lang required"}), 400

    vocab_id = find_vocab_id_by_word(user["id"], target_lang, word)
    if not vocab_id:
        return jsonify({"srs_updated": False})

    from database import get_db
    conn = get_db()
    progress_row = conn.execute(
        "SELECT id FROM flashcard_progress WHERE user_id = ? AND vocab_id = ?",
        (user["id"], vocab_id),
    ).fetchone()
    if not progress_row:
        conn.execute(
            "INSERT INTO flashcard_progress (user_id, vocab_id) VALUES (?, ?)",
            (user["id"], vocab_id),
        )
        conn.commit()
    conn.close()

    progress = review_flashcard(user["id"], vocab_id, 5 if correct else 1)
    return jsonify({
        "srs_updated": True,
        "vocab_id": vocab_id,
        "progress": progress,
    })
