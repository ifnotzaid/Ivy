"""
database.py — SQLite database for user accounts, vocabulary, and flashcards.

Tables:
  - users: email, password hash, created_at
  - vocabulary: user_id, word, meaning, pos, case, gender, base_form,
                difficulty, sentence, translation, language, style, saved_at
  - flashcard_progress: user_id, vocab_id, ease_factor, interval, next_review, reviews
"""

import sqlite3
import bcrypt
import os
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "translator.db"


def get_db():
    """Get a database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            meaning TEXT,
            pos TEXT,
            grammatical_case TEXT,
            gender TEXT,
            base_form TEXT,
            difficulty TEXT,
            sentence TEXT,
            translation TEXT,
            source_lang TEXT,
            target_lang TEXT,
            style TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcard_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            vocab_id INTEGER NOT NULL,
            ease_factor REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_review TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vocab_id) REFERENCES vocabulary(id) ON DELETE CASCADE,
            UNIQUE(user_id, vocab_id)
        );

        CREATE INDEX IF NOT EXISTS idx_vocab_user ON vocabulary(user_id);
        CREATE INDEX IF NOT EXISTS idx_flashcard_user ON flashcard_progress(user_id);
        CREATE INDEX IF NOT EXISTS idx_flashcard_review ON flashcard_progress(next_review);
        CREATE TABLE IF NOT EXISTS flashcard_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            target_lang TEXT,
            is_public INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcard_set_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL,
            vocab_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (set_id) REFERENCES flashcard_sets(id) ON DELETE CASCADE,
            FOREIGN KEY (vocab_id) REFERENCES vocabulary(id) ON DELETE CASCADE,
            UNIQUE(set_id, vocab_id)
        );

        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, friend_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sets_user ON flashcard_sets(user_id);
        CREATE INDEX IF NOT EXISTS idx_set_items ON flashcard_set_items(set_id);
        CREATE INDEX IF NOT EXISTS idx_friends ON friendships(user_id, friend_id);

        CREATE TABLE IF NOT EXISTS saved_stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            story_text TEXT NOT NULL,
            summary TEXT,
            target_lang TEXT NOT NULL,
            support_lang TEXT NOT NULL,
            cefr_level TEXT NOT NULL,
            theme TEXT,
            length_label TEXT,
            comprehension_json TEXT,
            focus_vocab_json TEXT,
            word_data_json TEXT,
            story_hash TEXT,
            audio_blob BLOB,
            timepoints_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_saved_stories_user ON saved_stories(user_id, created_at DESC);
    """)
    try:
        conn.execute("ALTER TABLE saved_stories ADD COLUMN word_data_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE saved_stories ADD COLUMN story_hash TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE saved_stories ADD COLUMN audio_blob BLOB")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE saved_stories ADD COLUMN timepoints_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    rows = conn.execute("SELECT id, user_id, story_text FROM saved_stories ORDER BY id ASC").fetchall()
    seen_story_hashes = set()
    for row in rows:
        story_hash = hashlib.sha256((row["story_text"] or "").strip().encode("utf-8")).hexdigest()
        key = (row["user_id"], story_hash)
        if key in seen_story_hashes:
            conn.execute("DELETE FROM saved_stories WHERE id = ?", (row["id"],))
        else:
            seen_story_hashes.add(key)
            conn.execute("UPDATE saved_stories SET story_hash = ? WHERE id = ?", (story_hash, row["id"]))
    conn.commit()
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_stories_unique ON saved_stories(user_id, story_hash)"
    )
    conn.commit()
    conn.close()
    print("  Database initialized!")


# ──────────────────────────────────────────────
# User management
# ──────────────────────────────────────────────
def create_user(email: str, password: str, display_name: str = "") -> dict | None:
    """Create a new user. Returns user dict or None if email exists."""
    conn = get_db()
    try:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, display_name) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, display_name.strip() or email.split("@")[0])
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {"id": user_id, "email": email.lower(), "display_name": display_name or email.split("@")[0]}
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_user(email: str, password: str) -> dict | None:
    """Verify login credentials. Returns user dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()

    if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}
    return None


def get_user_by_id(user_id: int) -> dict | None:
    """Get user by ID."""
    conn = get_db()
    row = conn.execute("SELECT id, email, display_name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ──────────────────────────────────────────────
# Vocabulary management
# ──────────────────────────────────────────────
def save_word(user_id: int, word_data: dict) -> int:
    """Save a word to user's vocabulary. Returns vocab ID."""
    conn = get_db()

    # Check if word already saved
    existing = conn.execute(
        "SELECT id FROM vocabulary WHERE user_id = ? AND word = ? AND target_lang = ?",
        (user_id, word_data.get("word", ""), word_data.get("target_lang", ""))
    ).fetchone()

    if existing:
        conn.close()
        return existing["id"]

    cursor = conn.execute(
        """INSERT INTO vocabulary
        (user_id, word, meaning, pos, grammatical_case, gender, base_form,
         difficulty, sentence, translation, source_lang, target_lang, style)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            word_data.get("word", ""),
            word_data.get("meaning", ""),
            word_data.get("pos", ""),
            word_data.get("case", ""),
            word_data.get("gender", ""),
            word_data.get("base_form", ""),
            word_data.get("difficulty", ""),
            word_data.get("sentence", ""),
            word_data.get("translation", ""),
            word_data.get("source_lang", ""),
            word_data.get("target_lang", ""),
            word_data.get("style", ""),
        )
    )
    conn.commit()
    vocab_id = cursor.lastrowid

    # Create flashcard progress entry
    conn.execute(
        "INSERT OR IGNORE INTO flashcard_progress (user_id, vocab_id) VALUES (?, ?)",
        (user_id, vocab_id)
    )
    conn.commit()
    conn.close()
    return vocab_id


def get_vocabulary(user_id: int, language: str = None) -> list[dict]:
    """Get all saved words for a user, optionally filtered by language."""
    conn = get_db()
    if language:
        rows = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id = ? AND target_lang = ? ORDER BY saved_at DESC",
            (user_id, language)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id = ? ORDER BY saved_at DESC",
            (user_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_word(user_id: int, vocab_id: int) -> bool:
    """Delete a word from vocabulary."""
    conn = get_db()
    conn.execute("DELETE FROM vocabulary WHERE id = ? AND user_id = ?", (vocab_id, user_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def get_vocab_stats(user_id: int) -> dict:
    """Get vocabulary statistics."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM vocabulary WHERE user_id = ?", (user_id,)).fetchone()["c"]
    by_lang = conn.execute(
        "SELECT target_lang, COUNT(*) as c FROM vocabulary WHERE user_id = ? GROUP BY target_lang",
        (user_id,)
    ).fetchall()
    by_diff = conn.execute(
        "SELECT difficulty, COUNT(*) as c FROM vocabulary WHERE user_id = ? GROUP BY difficulty",
        (user_id,)
    ).fetchall()
    conn.close()

    return {
        "total": total,
        "by_language": {r["target_lang"]: r["c"] for r in by_lang},
        "by_difficulty": {r["difficulty"]: r["c"] for r in by_diff},
    }


# ──────────────────────────────────────────────
# Flashcard / Spaced Repetition (SM-2 algorithm)
# ──────────────────────────────────────────────
def get_due_flashcards(user_id: int, language: str = None, limit: int = 20, set_id: int = None) -> list[dict]:
    """Get flashcards due for review, optionally scoped to a flashcard set."""
    conn = get_db()
    now = datetime.utcnow().isoformat()

    sql = [
        "SELECT v.*, fp.ease_factor, fp.interval_days, fp.repetitions, fp.next_review",
        "FROM vocabulary v",
        "JOIN flashcard_progress fp ON fp.vocab_id = v.id AND fp.user_id = v.user_id",
    ]
    where = ["v.user_id = ?", "fp.next_review <= ?"]
    params = [user_id, now]

    if language:
        where.append("v.target_lang = ?")
        params.append(language)

    if set_id:
        sql.append("JOIN flashcard_set_items fsi ON fsi.vocab_id = v.id")
        where.append("fsi.set_id = ?")
        params.append(set_id)

    sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY fp.next_review ASC LIMIT ?")
    params.append(limit)

    rows = conn.execute(" ".join(sql), params).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def review_flashcard(user_id: int, vocab_id: int, quality: int) -> dict:
    """
    Update flashcard after review using SM-2 algorithm.
    quality: 0-5 (0=complete fail, 5=perfect)
    Returns updated progress.
    """
    conn = get_db()
    fp = conn.execute(
        "SELECT * FROM flashcard_progress WHERE user_id = ? AND vocab_id = ?",
        (user_id, vocab_id)
    ).fetchone()

    if not fp:
        conn.close()
        return {}

    ease = fp["ease_factor"]
    interval = fp["interval_days"]
    reps = fp["repetitions"]

    # SM-2 algorithm
    if quality >= 3:  # Correct
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        reps += 1
    else:  # Incorrect
        reps = 0
        interval = 0

    # Update ease factor
    ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

    next_review = (datetime.utcnow() + timedelta(days=max(interval, 0))).isoformat()

    conn.execute(
        """UPDATE flashcard_progress
        SET ease_factor = ?, interval_days = ?, repetitions = ?,
            next_review = ?, last_review = ?
        WHERE user_id = ? AND vocab_id = ?""",
        (ease, interval, reps, next_review, datetime.utcnow().isoformat(), user_id, vocab_id)
    )
    conn.commit()
    conn.close()

    return {
        "ease_factor": round(ease, 2),
        "interval_days": interval,
        "repetitions": reps,
        "next_review": next_review,
    }



# ── Flashcard Sets ────────────────────────────

def create_flashcard_set(user_id: int, name: str, description: str = "",
                         target_lang: str = "", is_public: bool = False) -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO flashcard_sets (user_id, name, description, target_lang, is_public) VALUES (?, ?, ?, ?, ?)",
        (user_id, name.strip(), description.strip(), target_lang, 1 if is_public else 0)
    )
    conn.commit()
    set_id = cursor.lastrowid
    conn.close()
    return set_id


def get_user_sets(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT fs.*, COUNT(fsi.id) as word_count, u.display_name as owner_name
        FROM flashcard_sets fs
        LEFT JOIN flashcard_set_items fsi ON fsi.set_id = fs.id
        LEFT JOIN users u ON u.id = fs.user_id
        WHERE fs.user_id = ?
        GROUP BY fs.id ORDER BY fs.created_at DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_set_by_id(set_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT fs.*, u.display_name as owner_name
        FROM flashcard_sets fs
        LEFT JOIN users u ON u.id = fs.user_id
        WHERE fs.id = ?""",
        (set_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_set_words(set_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT v.* FROM vocabulary v
        JOIN flashcard_set_items fsi ON fsi.vocab_id = v.id
        WHERE fsi.set_id = ?
        ORDER BY fsi.added_at DESC""",
        (set_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_word_to_set(set_id: int, vocab_id: int) -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO flashcard_set_items (set_id, vocab_id) VALUES (?, ?)",
            (set_id, vocab_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def remove_word_from_set(set_id: int, vocab_id: int) -> bool:
    conn = get_db()
    conn.execute(
        "DELETE FROM flashcard_set_items WHERE set_id = ? AND vocab_id = ?",
        (set_id, vocab_id)
    )
    conn.commit()
    conn.close()
    return True


def delete_flashcard_set(user_id: int, set_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM flashcard_sets WHERE id = ? AND user_id = ?", (set_id, user_id))
    conn.commit()
    conn.close()
    return True


def update_set_visibility(user_id: int, set_id: int, is_public: bool) -> bool:
    conn = get_db()
    conn.execute(
        "UPDATE flashcard_sets SET is_public = ? WHERE id = ? AND user_id = ?",
        (1 if is_public else 0, set_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def fork_public_set(source_set_id: int, target_user_id: int) -> dict:
    """Snapshot-fork a public set into target user's library.

    Copies each word from the source set into the target user's vocabulary
    (using save_word, which dedupes by word+target_lang so users who already
    have a word keep their existing SRS progress on it), then creates a new
    flashcard_sets row owned by target_user with copies of all the items.
    """
    source = get_set_by_id(source_set_id)
    if not source:
        raise ValueError("Set not found")
    if not source.get("is_public"):
        raise ValueError("Set is not public")
    if source["user_id"] == target_user_id:
        return {
            "new_set_id": source_set_id,
            "words_copied": 0,
            "words_existing": 0,
            "source_name": source.get("name", ""),
            "self_fork": True,
        }

    source_words = get_set_words(source_set_id)
    new_vocab_ids = []
    words_existing = 0
    conn = get_db()
    for word in source_words:
        existing = conn.execute(
            "SELECT id FROM vocabulary WHERE user_id = ? AND word = ? AND target_lang = ?",
            (target_user_id, word.get("word", ""), word.get("target_lang", "")),
        ).fetchone()
        if existing:
            words_existing += 1
            new_vocab_ids.append(existing["id"])
            continue

        word_data = {
            "word": word.get("word", ""),
            "meaning": word.get("meaning", ""),
            "pos": word.get("pos", ""),
            "case": word.get("grammatical_case", ""),
            "gender": word.get("gender", ""),
            "base_form": word.get("base_form", ""),
            "difficulty": word.get("difficulty", ""),
            "sentence": word.get("sentence", ""),
            "translation": word.get("translation", ""),
            "source_lang": word.get("source_lang", ""),
            "target_lang": word.get("target_lang", ""),
            "style": word.get("style", ""),
        }
        conn.close()
        new_vocab_ids.append(save_word(target_user_id, word_data))
        conn = get_db()
    conn.close()

    new_set_id = create_flashcard_set(
        user_id=target_user_id,
        name=source.get("name", "Untitled"),
        description=source.get("description", ""),
        target_lang=source.get("target_lang", ""),
        is_public=False,
    )
    for vocab_id in new_vocab_ids:
        add_word_to_set(new_set_id, vocab_id)

    return {
        "new_set_id": new_set_id,
        "words_copied": len(new_vocab_ids) - words_existing,
        "words_existing": words_existing,
        "source_name": source.get("name", ""),
        "self_fork": False,
    }


# ── Friends ───────────────────────────────────

def send_friend_request(user_id: int, friend_email: str) -> dict:
    conn = get_db()
    friend = conn.execute("SELECT id, display_name, email FROM users WHERE email = ?",
                          (friend_email.lower().strip(),)).fetchone()
    if not friend:
        conn.close()
        return {"error": "User not found"}
    if friend["id"] == user_id:
        conn.close()
        return {"error": "Cannot add yourself"}

    existing = conn.execute(
        "SELECT * FROM friendships WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
        (user_id, friend["id"], friend["id"], user_id)
    ).fetchone()

    if existing:
        conn.close()
        if existing["status"] == "accepted":
            return {"error": "Already friends"}
        return {"error": "Request already sent"}

    conn.execute(
        "INSERT INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'pending')",
        (user_id, friend["id"])
    )
    conn.commit()
    conn.close()
    return {"ok": True, "friend": {"id": friend["id"], "name": friend["display_name"]}}


def accept_friend_request(user_id: int, friendship_id: int) -> bool:
    conn = get_db()
    conn.execute(
        "UPDATE friendships SET status = 'accepted' WHERE id = ? AND friend_id = ?",
        (friendship_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def reject_friend_request(user_id: int, friendship_id: int) -> bool:
    conn = get_db()
    conn.execute(
        "DELETE FROM friendships WHERE id = ? AND friend_id = ?",
        (friendship_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def remove_friend(user_id: int, friendship_id: int) -> bool:
    """Remove an accepted friendship where the current user is either side."""
    conn = get_db()
    cursor = conn.execute(
        """DELETE FROM friendships
           WHERE id = ?
             AND status = 'accepted'
             AND (user_id = ? OR friend_id = ?)""",
        (friendship_id, user_id, user_id),
    )
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def get_friends(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT f.id as friendship_id, f.status,
        CASE WHEN f.user_id = ? THEN f.friend_id ELSE f.user_id END as friend_id,
        u.display_name, u.email
        FROM friendships f
        JOIN users u ON u.id = CASE WHEN f.user_id = ? THEN f.friend_id ELSE f.user_id END
        WHERE (f.user_id = ? OR f.friend_id = ?) AND f.status = 'accepted'""",
        (user_id, user_id, user_id, user_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_requests(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT f.id as friendship_id, f.user_id as from_id,
        u.display_name, u.email
        FROM friendships f
        JOIN users u ON u.id = f.user_id
        WHERE f.friend_id = ? AND f.status = 'pending'""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_friend_public_sets(friend_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT fs.*, COUNT(fsi.id) as word_count, u.display_name as owner_name
        FROM flashcard_sets fs
        LEFT JOIN flashcard_set_items fsi ON fsi.set_id = fs.id
        LEFT JOIN users u ON u.id = fs.user_id
        WHERE fs.user_id = ? AND fs.is_public = 1
        GROUP BY fs.id ORDER BY fs.created_at DESC""",
        (friend_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_public_sets_browse(exclude_user_id: int = 0, limit: int = 20) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT fs.*, COUNT(fsi.id) as word_count, u.display_name as owner_name
        FROM flashcard_sets fs
        LEFT JOIN flashcard_set_items fsi ON fsi.set_id = fs.id
        LEFT JOIN users u ON u.id = fs.user_id
        WHERE fs.is_public = 1 AND fs.user_id != ?
        GROUP BY fs.id
        HAVING word_count > 0
        ORDER BY word_count DESC LIMIT ?""",
        (exclude_user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# —— Short stories ——————————————————————————————————————

def _json_list_has_items(value: str) -> bool:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, list) and len(parsed) > 0


def save_story(user_id: int, story_data: dict) -> int:
    """Save a generated story for later review."""
    conn = get_db()
    story_text = story_data.get("story_text", "").strip()
    word_data_json = story_data.get("word_data_json", "[]")
    story_hash = hashlib.sha256(story_text.encode("utf-8")).hexdigest()
    existing = conn.execute(
        "SELECT id FROM saved_stories WHERE user_id = ? AND story_hash = ?",
        (user_id, story_hash)
    ).fetchone()
    if existing:
        if _json_list_has_items(word_data_json):
            conn.execute(
                """UPDATE saved_stories
                SET word_data_json = ?
                WHERE id = ?
                  AND (word_data_json IS NULL OR TRIM(word_data_json) = '' OR TRIM(word_data_json) = '[]')""",
                (word_data_json, existing["id"]),
            )
            conn.commit()
        conn.close()
        return existing["id"]

    cursor = conn.execute(
        """INSERT INTO saved_stories
        (user_id, title, story_text, summary, target_lang, support_lang,
         cefr_level, theme, length_label, comprehension_json, focus_vocab_json, word_data_json, story_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            story_data.get("title", "").strip() or "Untitled story",
            story_text,
            story_data.get("summary", "").strip(),
            story_data.get("target_lang", "").strip(),
            story_data.get("support_lang", "").strip(),
            story_data.get("cefr_level", "").strip(),
            story_data.get("theme", "").strip(),
            story_data.get("length_label", "").strip(),
            story_data.get("comprehension_json", "[]"),
            story_data.get("focus_vocab_json", "[]"),
            word_data_json,
            story_hash,
        )
    )
    conn.commit()
    story_id = cursor.lastrowid
    conn.close()
    return story_id


_SAVED_STORY_COLUMNS = """
    id, user_id, title, story_text, summary, target_lang, support_lang,
    cefr_level, theme, length_label, comprehension_json, focus_vocab_json,
    word_data_json, story_hash, created_at,
    CASE WHEN audio_blob IS NOT NULL AND length(audio_blob) > 0
         THEN 1 ELSE 0 END AS has_audio,
    CASE WHEN audio_blob IS NOT NULL AND length(audio_blob) > 0
              AND timepoints_json IS NOT NULL AND TRIM(timepoints_json) NOT IN ('', '[]')
         THEN 1 ELSE 0 END AS has_narration
"""


def get_saved_stories(user_id: int, target_lang: str | None = None, limit: int = 24) -> list[dict]:
    """List saved stories for a user without loading narration blobs."""
    conn = get_db()
    if target_lang:
        rows = conn.execute(
            f"""SELECT {_SAVED_STORY_COLUMNS} FROM saved_stories
            WHERE user_id = ? AND target_lang = ?
            ORDER BY created_at DESC
            LIMIT ?""",
            (user_id, target_lang, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT {_SAVED_STORY_COLUMNS} FROM saved_stories
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?""",
            (user_id, limit)
        ).fetchall()
    conn.close()
    stories = [dict(r) for r in rows]
    for story in stories:
        story["has_audio"] = bool(story.get("has_audio"))
        story["has_narration"] = bool(story.get("has_narration"))
    return stories


def get_saved_story(user_id: int, story_id: int) -> dict | None:
    """Fetch one saved story owned by the user without loading narration blobs."""
    conn = get_db()
    row = conn.execute(
        f"""SELECT {_SAVED_STORY_COLUMNS}
           FROM saved_stories WHERE id = ? AND user_id = ?""",
        (story_id, user_id)
    ).fetchone()
    conn.close()
    if not row:
        return None
    story = dict(row)
    story["has_audio"] = bool(story.get("has_audio"))
    story["has_narration"] = bool(story.get("has_narration"))
    return story


def set_story_audio(user_id: int, story_id: int, audio_bytes: bytes) -> bool:
    """Attach audio bytes to a saved story owned by the user."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE saved_stories SET audio_blob = ?, timepoints_json = NULL WHERE id = ? AND user_id = ?",
        (sqlite3.Binary(audio_bytes), story_id, user_id),
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def get_story_audio(user_id: int, story_id: int) -> bytes | None:
    """Fetch cached audio bytes for a saved story, or None if not yet generated."""
    conn = get_db()
    row = conn.execute(
        "SELECT audio_blob FROM saved_stories WHERE id = ? AND user_id = ?",
        (story_id, user_id),
    ).fetchone()
    conn.close()
    if row is None or row["audio_blob"] is None:
        return None
    return bytes(row["audio_blob"])


def set_story_narration(user_id: int, story_id: int, audio_bytes: bytes, timepoints: list[dict]) -> bool:
    """Attach synced narration bytes and timing data to a saved story owned by the user."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE saved_stories SET audio_blob = ?, timepoints_json = ? WHERE id = ? AND user_id = ?",
        (
            sqlite3.Binary(audio_bytes),
            json.dumps(timepoints or [], ensure_ascii=False),
            story_id,
            user_id,
        ),
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def get_story_narration(user_id: int, story_id: int) -> dict | None:
    """Fetch cached synced narration for a saved story, or None if it is missing."""
    conn = get_db()
    row = conn.execute(
        "SELECT audio_blob, timepoints_json FROM saved_stories WHERE id = ? AND user_id = ?",
        (story_id, user_id),
    ).fetchone()
    conn.close()
    if row is None or row["audio_blob"] is None or not row["timepoints_json"]:
        return None
    try:
        timepoints = json.loads(row["timepoints_json"]) or []
    except (TypeError, ValueError):
        timepoints = []
    if not timepoints:
        return None
    return {
        "audio_bytes": bytes(row["audio_blob"]),
        "timepoints": timepoints,
    }


_CLOZE_PRIORITY_POS = {"verb", "noun", "adj", "adv"}
_CLOZE_MIN_WORD_LEN = 3
_CLOZE_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？", "…")


def _split_sentences_from_word_data(word_data: list) -> list[list[dict]]:
    """Split a story word_data array into sentence-sized token chunks."""
    sentences = []
    current = []
    for token in word_data or []:
        if not isinstance(token, dict):
            continue
        current.append(token)
        word = (token.get("word") or "").strip()
        if word.endswith(_CLOZE_SENTENCE_ENDINGS):
            if any(any(ch.isalpha() for ch in (item.get("word") or "")) for item in current):
                sentences.append(current)
            current = []
    if current and any(any(ch.isalpha() for ch in (item.get("word") or "")) for item in current):
        sentences.append(current)
    return sentences


def _cloze_token_is_punctuation(token: str) -> bool:
    return bool(token) and not any(ch.isalnum() for ch in token)


def _split_cloze_word_affixes(token: str) -> tuple[str, str, str]:
    """Split a token into leading punctuation, core word, and trailing punctuation."""
    token = (token or "").strip()
    start = 0
    end = len(token)
    while start < end and not token[start].isalnum():
        start += 1
    while end > start and not token[end - 1].isalnum():
        end -= 1
    return token[:start], token[start:end], token[end:]


def _cloze_surface_word(token: str) -> str:
    """Return the answerable word without surrounding punctuation."""
    _, core, _ = _split_cloze_word_affixes(token)
    return core.strip()


def _reconstruct_sentence(tokens: list[dict], blank_index: int) -> tuple[str, str]:
    """Return a display sentence with the selected token replaced by ___."""
    parts = []
    answer = ""
    open_hug_next = set('([{"\u00AB\u201C\u2018\u300C\u300E')
    prev_attaches_next = False
    for index, token in enumerate(tokens):
        word = (token.get("word") or "").strip()
        is_blank = index == blank_index
        if is_blank:
            prefix, core, suffix = _split_cloze_word_affixes(word)
            answer = core or word
            display = f"{prefix}___{suffix}"
        else:
            display = word
        if not display:
            continue
        if not parts:
            parts.append(display)
        elif prev_attaches_next:
            parts[-1] = parts[-1] + display
        elif (not is_blank) and (_cloze_token_is_punctuation(display) or display[0] in ",.;:!?)]}»”’"):
            parts[-1] = parts[-1] + display
        else:
            parts.append(display)
        prev_attaches_next = (
            not is_blank
            and len(display) == 1
            and display in open_hug_next
        )
    return " ".join(parts).strip(), answer


def _candidate_words_in_sentence(tokens: list[dict]) -> list[int]:
    """Return token indexes worth blanking from a sentence."""
    candidates = []
    for index, token in enumerate(tokens):
        word = (token.get("word") or "").strip()
        core_word = _cloze_surface_word(word)
        pos = (token.get("pos") or "").strip().lower()
        if pos not in _CLOZE_PRIORITY_POS:
            continue
        if len(core_word) < _CLOZE_MIN_WORD_LEN:
            continue
        if not any(ch.isalpha() for ch in core_word):
            continue
        if _cloze_token_is_punctuation(word):
            continue
        candidates.append(index)
    return candidates


def get_cloze_distractor_pool(user_id: int, target_lang: str, pos: str, exclude_word: str) -> list[str]:
    """Return same-POS distractors from the user's saved vocabulary."""
    conn = get_db()
    rows = conn.execute(
        """SELECT DISTINCT word, base_form FROM vocabulary
           WHERE user_id = ? AND target_lang = ? AND LOWER(pos) = ?""",
        (user_id, target_lang, pos.lower()),
    ).fetchall()
    conn.close()
    exclude = (exclude_word or "").strip().lower()
    seen = set()
    pool = []
    for row in rows:
        for candidate in (row["word"], row["base_form"]):
            word = (candidate or "").strip()
            key = word.lower()
            if not word or key == exclude or key in seen:
                continue
            seen.add(key)
            pool.append(word)
    return pool


def build_cloze_items_for_user(
    user_id: int,
    target_lang: str,
    cefr_level: str | None = None,
    story_id: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Build a multiple-choice cloze quiz from a user's saved stories."""
    import random

    conn = get_db()
    sql_parts = [
        "SELECT id, title, word_data_json, cefr_level, support_lang FROM saved_stories",
        "WHERE user_id = ? AND target_lang = ?",
    ]
    params: list = [user_id, target_lang]
    if story_id:
        sql_parts.append("AND id = ?")
        params.append(story_id)
    if cefr_level:
        sql_parts.append("AND UPPER(cefr_level) = ?")
        params.append(cefr_level.upper())
    sql_parts.append("ORDER BY created_at DESC LIMIT 50")
    stories = conn.execute(" ".join(sql_parts), params).fetchall()
    conn.close()
    if not stories:
        return []

    candidate_items = []
    for story in stories:
        try:
            word_data = json.loads(story["word_data_json"] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(word_data, list) or not word_data:
            continue
        for sentence_tokens in _split_sentences_from_word_data(word_data):
            for blank_index in _candidate_words_in_sentence(sentence_tokens):
                token = sentence_tokens[blank_index]
                answer = _cloze_surface_word(token.get("word") or "")
                if not answer:
                    continue
                candidate_items.append({
                    "tokens": sentence_tokens,
                    "blank_index": blank_index,
                    "pos": (token.get("pos") or "").strip().lower(),
                    "answer": answer,
                    "meaning": (token.get("meaning") or "").strip(),
                    "base_form": (token.get("base_form") or "").strip(),
                    "story_id": story["id"],
                    "story_title": story["title"],
                    "support_lang": story["support_lang"],
                })
    if not candidate_items:
        return []

    random.shuffle(candidate_items)
    distractor_pools_by_pos = {}

    def pool_for(pos: str, answer: str) -> list[str]:
        if pos not in distractor_pools_by_pos:
            distractor_pools_by_pos[pos] = get_cloze_distractor_pool(user_id, target_lang, pos, answer)
        answer_key = answer.lower()
        pool = [word for word in distractor_pools_by_pos[pos] if word.lower() != answer_key]
        if len(pool) < 3:
            pool.extend(_builtin_distractors(target_lang, pos, answer))
        deduped = []
        seen = set()
        for word in pool:
            key = word.lower()
            if key == answer_key or key in seen:
                continue
            seen.add(key)
            deduped.append(word)
        return deduped

    items = []
    seen_items = set()
    for candidate in candidate_items:
        if len(items) >= limit:
            break
        sentence, answer = _reconstruct_sentence(candidate["tokens"], candidate["blank_index"])
        key = (sentence.lower(), answer.lower())
        if key in seen_items:
            continue
        pool = pool_for(candidate["pos"], answer)
        if len(pool) < 3:
            continue
        options = random.sample(pool, 3) + [answer]
        random.shuffle(options)
        items.append({
            "sentence": sentence,
            "answer": answer,
            "options": options,
            "pos": candidate["pos"],
            "meaning": candidate["meaning"],
            "base_form": candidate["base_form"],
            "story_id": candidate["story_id"],
            "story_title": candidate["story_title"],
            "support_lang": candidate.get("support_lang") or "en",
        })
        seen_items.add(key)
    return items


_BUILTIN_DISTRACTORS = {
    "tr": {
        "noun": ["ev", "okul", "kitap", "araba", "su", "yemek", "şehir", "zaman", "yol", "iş", "kapı", "pencere"],
        "verb": ["gitmek", "gelmek", "yapmak", "almak", "vermek", "görmek", "bilmek", "sevmek", "anlamak", "bulmak"],
        "adj": ["büyük", "küçük", "iyi", "kötü", "yeni", "eski", "güzel", "kolay", "zor", "sıcak"],
        "adv": ["çok", "az", "hep", "asla", "şimdi", "sonra", "önce", "yavaşça", "hızlıca", "burada"],
    },
    "de": {
        "noun": ["Haus", "Schule", "Buch", "Auto", "Wasser", "Essen", "Stadt", "Zeit", "Weg", "Arbeit"],
        "verb": ["gehen", "kommen", "machen", "nehmen", "geben", "sehen", "wissen", "lieben", "verstehen", "finden"],
        "adj": ["groß", "klein", "gut", "schlecht", "neu", "alt", "schön", "leicht", "schwer", "warm"],
        "adv": ["sehr", "wenig", "immer", "nie", "jetzt", "später", "früher", "langsam", "schnell", "hier"],
    },
    "ru": {
        "noun": ["дом", "школа", "книга", "машина", "вода", "еда", "город", "время", "путь", "работа"],
        "verb": ["идти", "приходить", "делать", "брать", "давать", "видеть", "знать", "любить", "понимать", "находить"],
        "adj": ["большой", "маленький", "хороший", "плохой", "новый", "старый", "красивый", "лёгкий", "трудный", "тёплый"],
        "adv": ["очень", "мало", "всегда", "никогда", "сейчас", "потом", "раньше", "медленно", "быстро", "здесь"],
    },
    "en": {
        "noun": ["house", "school", "book", "car", "water", "food", "city", "time", "way", "work"],
        "verb": ["go", "come", "make", "take", "give", "see", "know", "love", "understand", "find"],
        "adj": ["big", "small", "good", "bad", "new", "old", "nice", "easy", "hard", "warm"],
        "adv": ["very", "little", "always", "never", "now", "later", "before", "slowly", "quickly", "here"],
    },
}


def _builtin_distractors(language: str, pos: str, exclude_word: str) -> list[str]:
    exclude = (exclude_word or "").lower()
    return [word for word in _BUILTIN_DISTRACTORS.get(language, {}).get(pos, []) if word.lower() != exclude]


def find_vocab_id_by_word(user_id: int, target_lang: str, word: str) -> int | None:
    """Find a saved vocabulary row by surface form or base form."""
    needle = _cloze_surface_word(word).lower()
    if not needle:
        return None
    conn = get_db()
    row = conn.execute(
        """SELECT id FROM vocabulary
           WHERE user_id = ? AND target_lang = ?
             AND (LOWER(word) = ? OR LOWER(base_form) = ?)
           LIMIT 1""",
        (user_id, target_lang, needle, needle),
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def get_vocab_count_for_lang(user_id: int, target_lang: str) -> int:
    """Count saved vocabulary in one target language for personalization gating."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM vocabulary WHERE user_id = ? AND target_lang = ?",
        (user_id, target_lang),
    ).fetchone()
    conn.close()
    return int(row["n"]) if row else 0


def get_user_known_words(user_id: int, target_lang: str, limit: int = 25) -> list[dict]:
    """
    Words the learner has likely mastered.

    Primary signal is SM-2 progress: ease_factor >= 2.3 and at least two
    repetitions. If the learner has saved words but has not reviewed cards yet,
    fall back to recent saves so personalization can still work in early demos.
    """
    conn = get_db()
    rows = conn.execute(
        """
        SELECT v.base_form, v.word, v.meaning, v.pos, v.difficulty,
               COALESCE(fp.ease_factor, 2.5) AS ease_factor,
               COALESCE(fp.repetitions, 0) AS repetitions
        FROM vocabulary v
        LEFT JOIN flashcard_progress fp
               ON fp.vocab_id = v.id AND fp.user_id = v.user_id
        WHERE v.user_id = ?
          AND v.target_lang = ?
          AND COALESCE(fp.ease_factor, 2.5) >= 2.3
          AND COALESCE(fp.repetitions, 0) >= 2
        ORDER BY fp.ease_factor DESC, fp.repetitions DESC, v.saved_at DESC
        LIMIT ?
        """,
        (user_id, target_lang, limit),
    ).fetchall()

    if not rows:
        rows = conn.execute(
            """
            SELECT v.base_form, v.word, v.meaning, v.pos, v.difficulty,
                   2.5 AS ease_factor, 0 AS repetitions
            FROM vocabulary v
            WHERE v.user_id = ? AND v.target_lang = ?
            ORDER BY v.saved_at DESC
            LIMIT ?
            """,
            (user_id, target_lang, limit),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_user_struggling_words(user_id: int, target_lang: str, limit: int = 3) -> list[dict]:
    """Words reviewed at least once with low SM-2 ease, used as stretch vocab."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT v.base_form, v.word, v.meaning, v.pos, v.difficulty,
               fp.ease_factor, fp.repetitions
        FROM vocabulary v
        JOIN flashcard_progress fp
             ON fp.vocab_id = v.id AND fp.user_id = v.user_id
        WHERE v.user_id = ?
          AND v.target_lang = ?
          AND fp.repetitions > 0
          AND fp.ease_factor < 2.0
        ORDER BY fp.ease_factor ASC, fp.repetitions DESC
        LIMIT ?
        """,
        (user_id, target_lang, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_saved_story(user_id: int, story_id: int) -> bool:
    """Delete one saved story."""
    conn = get_db()
    conn.execute("DELETE FROM saved_stories WHERE id = ? AND user_id = ?", (story_id, user_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0
