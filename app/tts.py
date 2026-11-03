"""
tts.py - Story narration with Google Cloud Text-to-Speech.

Plain narration splits long stories into chunks under the API byte limit.
Word-synced narration uses SSML <mark> tags so the reader can highlight
each word as it is spoken.
"""

from __future__ import annotations

import os
import re

from flask import Response, request

GOOGLE_TTS_VOICE_STYLE = os.environ.get("GOOGLE_TTS_VOICE_STYLE", "Aoede").strip() or "Aoede"
GOOGLE_TTS_LANGUAGE_CODES = {
    "tr": "tr-TR",
    "en": "en-US",
    "de": "de-DE",
    "ru": "ru-RU",
}
TTS_BYTE_LIMIT = 3500
MARKED_TTS_BYTE_LIMIT = 4600
MARKED_TTS_SYNC_VERSION = 2
STORY_SENTENCE_SPLIT_RE = r"(?<=[.!?\u3002\uff01\uff1f])\s+"
STORY_MARK_TOKEN_RE = re.compile(r"[^\W_]+(?:['\u2019-][^\W_]+)*", re.UNICODE)


def _utf8_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


def _split_long_token_for_tts(token: str) -> list[str]:
    chunks = []
    current = ""
    for char in token:
        candidate = current + char
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = char
    if current:
        chunks.append(current)
    return chunks


def _split_words_for_tts(text: str) -> list[str]:
    chunks = []
    current = ""
    for word in text.split():
        if _utf8_len(word) > TTS_BYTE_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_token_for_tts(word))
            continue

        candidate = f"{current} {word}".strip() if current else word
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word

    if current:
        chunks.append(current)
    return chunks


def _split_oversized_tts_sentence(sentence: str) -> list[str]:
    chunks = []
    current = ""
    parts = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]

    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if _utf8_len(part) > TTS_BYTE_LIMIT:
            chunks.extend(_split_words_for_tts(part))
            current = ""
        else:
            current = part

    if current:
        chunks.append(current)
    return chunks


def _split_text_for_tts(text: str) -> list[str]:
    """Split text into chunks safely below the Google TTS byte limit."""
    text = (text or "").strip()
    if not text:
        return []

    sentences = [
        sentence.strip()
        for sentence in re.split(STORY_SENTENCE_SPLIT_RE, text)
        if sentence.strip()
    ]

    chunks = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if _utf8_len(candidate) <= TTS_BYTE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if _utf8_len(sentence) > TTS_BYTE_LIMIT:
            chunks.extend(_split_oversized_tts_sentence(sentence))
            current = ""
        else:
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def synthesize_story_audio(provider: str, text: str, language: str) -> tuple[bytes, str]:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("No story text provided")

    provider = (provider or "").strip().lower()
    if provider != "google":
        raise RuntimeError("Unsupported TTS provider")

    try:
        from google.cloud import texttospeech
    except Exception as exc:
        raise RuntimeError("Google Cloud TTS is not installed. Run: pip install google-cloud-texttospeech") from exc

    language_code = GOOGLE_TTS_LANGUAGE_CODES.get(language, "en-US")
    voice_name = f"{language_code}-Chirp3-HD-{GOOGLE_TTS_VOICE_STYLE}"
    chunks = _split_text_for_tts(text)
    if not chunks:
        raise RuntimeError("No story text provided")

    try:
        client = texttospeech.TextToSpeechClient()
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )
        print(f"  [TTS] Total input: {_utf8_len(text)} bytes, {len(chunks)} chunk(s)")
        audio_parts = []
        for index, chunk in enumerate(chunks, start=1):
            print(f"  [TTS] Synthesizing chunk {index}/{len(chunks)} ({_utf8_len(chunk)} bytes)")
            synthesis_input = texttospeech.SynthesisInput(text=chunk)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
            audio_parts.append(response.audio_content)
        return b"".join(audio_parts), "audio/mpeg"
    except Exception as exc:
        raise RuntimeError(f"Google Cloud TTS failed: {exc}") from exc


def _ssml_escape(text: str) -> str:
    """Escape XML-significant characters before embedding token text in SSML."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _normalize_story_mark_token(value: str) -> str:
    return re.sub(r"^[\W_]+|[\W_]+$", "", str(value or ""), flags=re.UNICODE).casefold()


def _is_pure_story_punct(value: str) -> bool:
    return not bool(STORY_MARK_TOKEN_RE.search(str(value or "")))


def _word_item_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("word") or "")
    return str(item or "")


def _word_item_base(item) -> str:
    if isinstance(item, dict):
        return str(item.get("base_form") or "")
    return ""


def _next_story_word_index(word_items: list, start: int, display_token: str) -> int:
    first_usable = -1
    target = _normalize_story_mark_token(display_token)
    for index in range(max(0, start), len(word_items)):
        item = word_items[index]
        item_word = _word_item_text(item)
        if _is_pure_story_punct(item_word):
            continue
        if first_usable < 0:
            first_usable = index
        normalized_word = _normalize_story_mark_token(item_word)
        normalized_base = _normalize_story_mark_token(_word_item_base(item))
        if target and (normalized_word == target or normalized_base == target):
            return index
        if first_usable >= 0 and index - first_usable >= 4:
            break
    return first_usable


def _build_marked_story_ssml_from_text(story_text: str, word_items: list) -> tuple[str, int]:
    """
    Build SSML from the original story text, preserving punctuation and spacing.

    The matching mirrors the browser's renderWordsFromSource() logic so mark
    names line up with .word-span[data-index] instead of plain DOM position.
    """
    parts = ["<speak>"]
    last_offset = 0
    data_cursor = 0
    mark_count = 0

    for match in STORY_MARK_TOKEN_RE.finditer(story_text or ""):
        parts.append(_ssml_escape((story_text or "")[last_offset:match.start()]))
        token = match.group(0)
        data_index = _next_story_word_index(word_items, data_cursor, token)
        if data_index >= 0:
            parts.append(f'<mark name="w{data_index}"/>')
            parts.append(_ssml_escape(token))
            data_cursor = data_index + 1
            mark_count += 1
        else:
            parts.append(_ssml_escape(token))
        last_offset = match.end()

    parts.append(_ssml_escape((story_text or "")[last_offset:]))
    parts.append("</speak>")
    return "".join(parts), mark_count


def _build_marked_story_ssml_from_words(words: list[str]) -> tuple[str, int]:
    parts = ["<speak>"]
    mark_count = 0
    for index, word in enumerate(words):
        token = str(word or "").strip()
        parts.append(f'<mark name="w{index}"/>')
        mark_count += 1
        if token:
            parts.append(_ssml_escape(token))
            parts.append(" ")
    parts.append("</speak>")
    return "".join(parts), mark_count


def _ssml_mark_timepoint_value(texttospeech):
    """Return the SSML_MARK enum value across google-cloud-tts versions."""
    request_cls = texttospeech.SynthesizeSpeechRequest
    timepoint_type = getattr(request_cls, "TimepointType", None)
    if timepoint_type is not None and hasattr(timepoint_type, "SSML_MARK"):
        return timepoint_type.SSML_MARK
    if hasattr(request_cls, "SSML_MARK"):
        return request_cls.SSML_MARK
    module_type = getattr(texttospeech, "TimepointType", None)
    if module_type is not None and hasattr(module_type, "SSML_MARK"):
        return module_type.SSML_MARK
    return 1


def timepoints_are_current(timepoints: list[dict]) -> bool:
    return bool(timepoints) and all(
        isinstance(item, dict) and item.get("sync_version") == MARKED_TTS_SYNC_VERSION
        for item in timepoints
    )


def synthesize_marked_story_audio(word_items: list, language: str, story_text: str = "") -> tuple[bytes, list[dict]]:
    """
    Synthesize narration with SSML mark timepoints.

    The words list must come from story word_data in display order, so returned
    timepoint indexes line up with .word-span[data-index] in the story reader.
    """
    word_strings = [_word_item_text(item) for item in (word_items or [])]
    if not word_strings:
        raise RuntimeError("No words supplied for word-synced narration")

    ssml = ""
    mark_count = 0
    if (story_text or "").strip():
        ssml, mark_count = _build_marked_story_ssml_from_text(story_text, word_items or [])
    if not mark_count:
        ssml, mark_count = _build_marked_story_ssml_from_words(word_strings)

    ssml_bytes = _utf8_len(ssml)
    if ssml_bytes > MARKED_TTS_BYTE_LIMIT:
        raise RuntimeError(
            "This story is too long for word-synced narration right now. "
            "Turn off Sync words to play regular narration."
        )

    try:
        from google.cloud import texttospeech_v1beta1 as texttospeech
    except Exception:
        try:
            from google.cloud import texttospeech
        except Exception as exc:
            raise RuntimeError("Google Cloud TTS is not installed. Run: pip install google-cloud-texttospeech") from exc

    language_code = GOOGLE_TTS_LANGUAGE_CODES.get(language, "en-US")

    try:
        client = texttospeech.TextToSpeechClient()
        # Chirp3 HD ignores unsupported SSML tags such as <mark>, so word sync
        # uses the API's default non-Chirp voice for the language.
        request_payload = {
            "input": texttospeech.SynthesisInput(ssml=ssml),
            "voice": texttospeech.VoiceSelectionParams(language_code=language_code),
            "audio_config": texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
            ),
            "enable_time_pointing": [_ssml_mark_timepoint_value(texttospeech)],
        }
        print(f"  [TTS sync] Synthesizing marked narration ({ssml_bytes} SSML bytes, {len(word_strings)} marks)")
        response = client.synthesize_speech(request=request_payload)
    except Exception as exc:
        error_text = str(exc)
        if "enable_time_pointing" in error_text:
            raise RuntimeError(
                "Google Cloud TTS word sync is not supported by the installed client. "
                "Upgrade google-cloud-texttospeech or turn off Sync words for regular narration."
            ) from exc
        raise RuntimeError(f"Google Cloud TTS (word sync) failed: {exc}") from exc

    timepoints = []
    for timepoint in getattr(response, "timepoints", []) or []:
        mark_name = getattr(timepoint, "mark_name", "") or ""
        if not mark_name.startswith("w"):
            continue
        try:
            index = int(mark_name[1:])
        except ValueError:
            continue
        if index < 0 or index >= len(word_strings):
            continue
        timepoints.append({
            "index": index,
            "time": float(timepoint.time_seconds),
            "sync_version": MARKED_TTS_SYNC_VERSION,
        })
    timepoints.sort(key=lambda item: item["time"])
    if not timepoints:
        raise RuntimeError("Google Cloud TTS did not return word-sync timing data")
    return response.audio_content, timepoints


def audio_mpeg_response(audio: bytes) -> Response:
    """Return MP3 bytes with basic byte-range support for browser seeking."""
    total = len(audio)
    range_header = request.headers.get("Range", "")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/mpeg",
    }

    if range_header.startswith("bytes="):
        range_value = range_header.split("=", 1)[1].split(",", 1)[0].strip()
        start_text, _, end_text = range_value.partition("-")
        try:
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else total - 1
            else:
                suffix_length = int(end_text)
                start = max(total - suffix_length, 0)
                end = total - 1
            if start < 0 or end < start or start >= total:
                return Response(status=416, headers={**headers, "Content-Range": f"bytes */{total}"})
            end = min(end, total - 1)
            chunk = audio[start:end + 1]
            headers.update({
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(len(chunk)),
            })
            return Response(chunk, status=206, headers=headers)
        except (TypeError, ValueError):
            pass

    headers["Content-Length"] = str(total)
    return Response(audio, headers=headers)
