import math
import re
import unicodedata


def _text_key(value):
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_rating_5(value):
    """Accept only explicit 0-5 NU values supplied by game_data, not percentages."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 5 else None


def _round_to_half(value):
    return round(value * 2) / 2


def _render_stars(value):
    if value is None:
        return "Unknown"
    value = max(0.0, min(5.0, value))
    full = int(value)
    half = (value - full) >= 0.5
    return "★" * full + ("½" if half else "") or "0 stars"


def _genre_map(values):
    result = {}
    if not isinstance(values, list):
        return result
    for value in values:
        key = _text_key(value)
        if key and key not in {"chinese", "korean"}:
            result.setdefault(key, value.strip())
    return result


def _author_keys(novel):
    values = [novel.get("author")]
    aliases = novel.get("author_aliases")
    if isinstance(aliases, list):
        values.extend(aliases)
    return {key for value in values if (key := _text_key(value))}


def _author_values(novel):
    aliases = novel.get("author_aliases")
    values = [novel.get("author")] + (aliases if isinstance(aliases, list) else [])
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def _latin_name(value):
    letters = [c for c in value if c.isalpha()]
    return bool(letters) and all("LATIN" in unicodedata.name(c, "") for c in letters)


def _matched_author_name(guess, shared):
    # prefer a shared Latin-script name. If matching happened through a native alias, use a Latin alias already present on the guess, not an answer-only name.
    values = _author_values(guess)
    common = [v for v in values if _text_key(v) in shared]
    return next((v for v in common if _latin_name(v)), None) or next(
        (v for v in values if _latin_name(v)), None
    ) or common[0]


def compare_guess(guess, answer):
    title = _text_key(guess.get("title"))
    if title and title == _text_key(answer.get("title")):
        return {"title": "🎉 Correct!"}

    result = {}
    guess_authors, answer_authors = _author_keys(guess), _author_keys(answer)
    if not guess_authors or not answer_authors:
        result["author"] = "Author unknown"
    elif guess_authors & answer_authors:
        result["author"] = "✔️ Same author — " + _matched_author_name(guess, guess_authors & answer_authors)
    else:
        result["author"] = "❌ Different author"

    g_genres, a_genres = _genre_map(guess.get("genres")), _genre_map(answer.get("genres"))
    if not g_genres or not a_genres:
        result["genres"] = {"summary": "Genre data unavailable", "matched": [], "available": False}
    else:
        common = sorted(g_genres.keys() & a_genres.keys())
        result["genres"] = {
            "summary": f"{len(common)}/{len(a_genres)} match",
            "matched": [g_genres[key] for key in common], "available": True,
        }

    g_rating = _normalize_rating_5(guess.get("rating"))
    a_rating = _normalize_rating_5(answer.get("rating"))
    if g_rating is None or a_rating is None:
        result["rating"] = {"summary": "Rating unknown", "higher_or_lower": None}
    else:
        g_rating, a_rating = _round_to_half(g_rating), _round_to_half(a_rating)
        direction = "higher" if g_rating > a_rating else "lower" if g_rating < a_rating else "equal"
        hint = {"higher": "🔽 Lower", "lower": "🔼 Higher", "equal": "✔️"}[direction]
        result["rating"] = {
            "summary": f"{_render_stars(g_rating)} · {hint}",
            "higher_or_lower": direction,
        }

    statuses = {"completed", "ongoing", "hiatus", "dropped", "cancelled"}
    g_status, a_status = guess.get("publication_status"), answer.get("publication_status")
    if g_status not in statuses:
        status_feedback = "Your guess: Unknown · Comparison unavailable—guess status unknown"
    elif a_status not in statuses:
        status_feedback = f"Your guess: {g_status.capitalize()} · Comparison unavailable—answer status unknown"
    else:
        match = "✔️ Same status" if g_status == a_status else "❌ Different status"
        status_feedback = f"Your guess: {g_status.capitalize()} · {match}"
    result["publication_status"] = status_feedback


    g_chapters, a_chapters = guess.get("chapters"), answer.get("chapters")
    if any(type(value) is not int or value < 0 for value in (g_chapters, a_chapters)):
        result["chapters"] = "Original chapter count unknown"
    elif g_chapters == a_chapters:
        result["chapters"] = "✔️"
    else:
        result["chapters"] = "🔽 Lower" if g_chapters > a_chapters else "🔼 Higher"
    return result
