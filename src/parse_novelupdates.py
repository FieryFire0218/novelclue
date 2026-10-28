import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


LANGUAGES = {"chinese": "zh", "korean": "ko", "japanese": "ja"}


def text(node):
    return " ".join(node.stripped_strings) if node else ""


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def integer_count(value):
    value = value.strip()
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", value):
        raise ValueError(f"Invalid count: {value!r}")
    return int(value.replace(",", ""))


def parse_html(html, source_file):
    soup = BeautifulSoup(html, "html.parser")
    title = text(soup.select_one(".seriestitlenu"))
    canonical = soup.select_one('link[rel="canonical"]')
    url = canonical.get("href", "").strip() if canonical else ""
    parts = urlsplit(url)

    if not title or not (
        parts.scheme == "https"
        and parts.netloc in {"www.novelupdates.com", "novelupdates.com"}
        and re.fullmatch(r"/series/[^/]+/?", parts.path)
        and not parts.query
        and not parts.fragment
    ):
        raise ValueError(
            f"{source_file}: missing series title or valid canonical URL. "
            "The file may be a blocked page or its structure may have changed."
        )

    warnings = []
    # generic schema.org inLanguage says English in these files. Use the original-language field displayed in the series sidebar instead.
    language_label = text(soup.select_one("#showlang"))
    language = LANGUAGES.get(language_label.casefold())
    if language is None:
        warnings.append(f"Missing or unsupported language: {language_label!r}")

    genres = unique(text(node) for node in soup.select("#seriesgenre a.genre"))
    if not genres:
        warnings.append("No genres extracted; do not overwrite existing genres.")

    tags_node = soup.select_one("#showtags")
    tags = (
        unique(text(node) for node in tags_node.select("a.genre"))
        if tags_node is not None
        else None
    )

    associated = soup.select_one("#editassociated")
    if associated:
        for br in associated.find_all("br"):
            br.replace_with("\n")
    aliases = unique(
        line.strip()
        for line in (associated.get_text() if associated else "").splitlines()
    )

    description = soup.select_one("#editdescription")
    if description:
        for unwanted in description.select("script, style, .editmsg"):
            unwanted.decompose()
        for br in description.find_all("br"):
            br.replace_with("\n")
        for paragraph in description.find_all("p"):
            paragraph.insert_before("\n")
            paragraph.insert_after("\n")
    synopsis = "\n\n".join(
        " ".join(line.split())
        for line in (description.get_text() if description else "").splitlines()
        if line.strip()
    ) or None
    if synopsis is None:
        warnings.append("No synopsis extracted.")

    votes = None
    vote_match = re.search(
        r"([\d,]+)\s+votes?\b", text(soup.select_one(".uvotes")), re.I
    )
    if vote_match:
        votes = integer_count(vote_match.group(1))
    else:
        warnings.append("Rating count unavailable; retained as null, not zero.")

    # read the explicitly displayed 0–5 NovelUpdates rating.
    rating_text = text(soup.select_one(".uvotes"))
    rating_match = re.search(
        r"\(\s*(\d+(?:\.\d+)?)\s*/\s*5(?:\.0+)?\s*,",
        rating_text,
    )

    average_rating = (
        float(rating_match.group(1)) if rating_match else None
    )
    if average_rating is not None and not 0 <= average_rating <= 5:
        average_rating = None

    # preserve line boundaries and wording. Do not sum chapter numbers.
    status_node = soup.select_one("#editstatus")
    chapter_status = (
        status_node.get_text("\n", strip=True) if status_node else None
    ) or None

    reading_node = soup.select_one(".rlist")
    reading_count = integer_count(text(reading_node)) if text(reading_node) else None
    if reading_count is None:
        warnings.append("Reading-list count unavailable; retained as null.")

    return {
        "source": "novelupdates",
        "source_file": Path(source_file).name,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "novelupdates_url": url,
        "source_title": title,
        "associated_names": aliases,
        "authors": unique(text(node) for node in soup.select("#showauthors a")),
        "original_language": language,
        "genres": genres,
        "tags": tags,
        "synopsis": synopsis,
        "novelupdates_rating_count": votes,
        "novelupdates_reading_list_count": reading_count,
        "novelupdates_rating_raw": average_rating,
        "original_chapter_status_raw": chapter_status,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="HTML files or folders")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing preview")
    args = parser.parse_args()

    try:
        paths = []
        for item in args.inputs:
            if item.is_dir():
                paths.extend(sorted(
                    p for p in item.iterdir()
                    if p.is_file() and p.suffix.lower() in {".html", ".htm"}
                ))
            else:
                paths.append(item)
        paths = list(dict.fromkeys(p.resolve() for p in paths))
        if not paths:
            raise ValueError("No .html or .htm files found.")
        if args.output.resolve() in paths:
            raise ValueError("Output must not overwrite an input HTML file.")
        if args.output.exists() and not args.overwrite:
            raise ValueError("Output exists. Use --overwrite to replace the preview.")

        # Parse the entire batch before writing output. Errors leave the
        # previous preview intact. No database imports or network requests.
        records = [parse_html(p.read_bytes(), p.name) for p in paths]
        urls = [record["novelupdates_url"] for record in records]
        if len(urls) != len(set(urls)):
            raise ValueError("Duplicate series URLs in inputs; provide one copy per series.")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")

        for record in records:
            print(
                f"{record['source_title']} | {record['original_language']} | "
                f"{len(record['genres'])} genres | "
                f"{record['novelupdates_rating_count']} ratings | "
                f"{record['novelupdates_reading_list_count']} reading lists"
            )
            for warning in record["warnings"]:
                print(f"  WARNING: {warning}")
        print(f"Saved {len(records)} records to {args.output}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
