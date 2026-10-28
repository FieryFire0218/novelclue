import re
from compare import _normalize_rating_5, _genre_map

GAME_VERSION = "novelupdates-v1"


def original_chapters(value):
    # only a simple, explicitly labelled total is safe to parse. Do not sum volumes, side stories, ranges, or open-ended descriptions.
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+|\d{1,3}(?:,\d{3})+)\s+chapters?\s*", value, re.I)
    if not match:
        return None
    count = int(match.group(1).replace(",", ""))
    return count if count <= 2147483647 else None


def nonempty_strings(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(v.strip() for v in value if isinstance(v, str) and v.strip()))


def game_data(novel):
    metadata = novel.source_metadata if isinstance(novel.source_metadata, dict) else {}
    dataset = metadata.get("record") or {}
    page = metadata.get("novelupdates_page") or {}
    # only recognized retained sources may supply NU-specific measurements.
    if not isinstance(dataset, dict) or dataset.get("source") not in {"shaido987/novel-dataset", "novelupdates"}:
        dataset = {}
    if not isinstance(page, dict) or page.get("source") != "novelupdates":
        page = {}

    def first_list(field):
        return nonempty_strings(page.get(field)) or nonempty_strings(dataset.get(field))

    rating = None
    chapters = None
    for record in (page, dataset):
        if rating is None:
            rating = _normalize_rating_5(record.get("novelupdates_rating_raw"))
        if chapters is None:
            chapters = original_chapters(record.get("original_chapter_status_raw"))

    authors = first_list("authors")
    genres = list(_genre_map(first_list("genres")).values())
    if not genres:
        genres = list(_genre_map(novel.genres).values())
    return {
        "game_metadata_version": GAME_VERSION,
        "title": novel.title,
        "url": novel.novelupdates_url or novel.url,
        "author": authors[0] if authors else novel.author,
        "author_aliases": authors,
        "author_identity_unverified": bool(authors),
        "genres": genres,
        "rating": rating,
        "chapters": chapters,
    }


def snapshot_data(snapshot):
    data = dict(snapshot)
    data.pop("translator", None)
    if data.get("game_metadata_version") != GAME_VERSION:
        # legacy snapshots contain WW percentages and translated chapter totals. Preserve their answer identity, but never relabel those measurements.
        data["rating"] = None
        data["chapters"] = None
    return data
