from compare import _normalize_rating_5, _genre_map
from chapter_status import parse_chapter_status

GAME_VERSION = "novelupdates-v2"


def original_chapters(value):
    return parse_chapter_status(value)["original_chapters_total"]


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
    for record in (page, dataset):
        if rating is None:
            rating = _normalize_rating_5(record.get("novelupdates_rating_raw"))

    # the latest retained status text is one coherent observation. If its total is ambiguous, do not silently substitute an older dataset count/status.
    page_raw = page.get("original_chapter_status_raw")
    raw = page_raw if isinstance(page_raw, str) and page_raw.strip() else dataset.get("original_chapter_status_raw")
    chapter_info = parse_chapter_status(raw)

    authors = first_list("authors")
    genres = list(_genre_map(first_list("genres")).values())
    if not genres:
        genres = list(_genre_map(novel.genres).values())
    return {
        "game_metadata_version": GAME_VERSION,
        # keep the established title/URL so identity and autocomplete stay stable.
        "title": novel.title,
        "url": novel.novelupdates_url or novel.url,
        "author": authors[0] if authors else novel.author,
        "author_aliases": authors,
        "author_identity_unverified": bool(authors),
        "genres": genres,
        "rating": rating,
        "chapters": chapter_info["original_chapters_total"],
        **chapter_info,
    }


def snapshot_data(snapshot):
    data = dict(snapshot)
    data.pop("translator", None)
    version = data.get("game_metadata_version")
    if version != GAME_VERSION:
        # v1 ratings are already NU scores. Older snapshots use WW percentages.
        if version != "novelupdates-v1":
            data["rating"] = None
        # do not compare a pre-breakdown count with the new total semantics.
        data["chapters"] = None
        data.update(parse_chapter_status(None))
    return data
