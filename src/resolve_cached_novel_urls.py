import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def normalize_url(value):
    if not isinstance(value, str):
        return None

    parts = urlsplit(value.strip())
    if (
        parts.scheme not in {"http", "https"}
        or parts.netloc not in {
            "www.novelupdates.com", "novelupdates.com"
        }
        or not re.fullmatch(r"/series/[^/]+/?", parts.path)
        or parts.query
        or parts.fragment
    ):
        return None

    return (
        "https://www.novelupdates.com"
        + parts.path.rstrip("/")
        + "/"
    )


def extract_links(path):
    soup = BeautifulSoup(path.read_bytes(), "html.parser")

    source_id = soup.select_one("input#mypostid")
    canonical = soup.select_one('link[rel="canonical"]')

    if source_id and canonical and soup.select_one(".seriestitlenu"):
        value = source_id.get("value", "")
        url = normalize_url(canonical.get("href"))
        if re.fullmatch(r"[1-9]\d*", value) and url:
            yield int(value), url

    for title in soup.select(".search_main_box_nu .search_title"):
        marker = title.select_one('span[id^="sid"]')
        link = title.select_one("a[href]")
        if marker is None or link is None:
            continue

        match = re.fullmatch(r"sid([1-9]\d*)", marker.get("id", ""))
        url = normalize_url(link.get("href"))
        if match and url:
            yield int(match.group(1)), url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preview", type=Path)
    parser.add_argument("--cache", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.output.resolve() == args.preview.resolve():
            raise ValueError("Output must differ from the input preview.")
        if args.output.exists():
            raise ValueError("Output exists; choose a new filename.")

        preview = json.loads(
            args.preview.read_text(encoding="utf-8-sig")
        )
        if preview.get("report_type") != "external_dataset_import_preview":
            raise ValueError("Expected the dataset import preview.")

        paths = set()
        for directory in args.cache:
            if not directory.is_dir():
                raise ValueError(f"Cache directory not found: {directory}")
            paths.update(
                path.resolve()
                for path in directory.rglob("*")
                if path.is_file()
                and path.suffix.lower() in {".html", ".htm"}
            )

        if args.output.resolve() in paths:
            raise ValueError("Output must not overwrite cached HTML.")

        evidence = defaultdict(lambda: defaultdict(set))

        for path in sorted(paths):
            for source_id, url in extract_links(path):
                evidence[source_id][url].add(str(path))

        url_ids = defaultdict(set)
        for source_id, urls in evidence.items():
            for url in urls:
                url_ids[url].add(source_id)

        results = []
        counts = Counter({"resolved": 0, "unresolved": 0, "conflict": 0})
        by_match = defaultdict(Counter)
        seen = set()

        for item in preview["results"]:
            source_id = item["source_novel_id"]
            if type(source_id) is not int or source_id <= 0:
                raise ValueError("Invalid source novel ID.")
            if source_id in seen:
                raise ValueError(f"Duplicate source ID: {source_id}")
            seen.add(source_id)

            observations = evidence.get(source_id, {})
            urls = sorted(observations)

            if not urls:
                status = "unresolved"
            elif len(urls) > 1 or any(
                len(url_ids[url]) > 1 for url in urls
            ):
                status = "conflict"
            else:
                status = "resolved"

            counts[status] += 1
            by_match[item["status"]][status] += 1

            results.append({
                "source_novel_id": source_id,
                "source_title": item["source_title"],
                "import_match_status": item["status"],
                "url_status": status,
                "novelupdates_url": (
                    urls[0] if status == "resolved" else None
                ),
                "observations": [
                    {
                        "url": url,
                        "cache_files": sorted(observations[url]),
                        "observed_source_ids": sorted(url_ids[url]),
                    }
                    for url in urls
                ],
            })

        output = {
            "report_type": "cached_novel_url_resolution",
            "input_preview": str(args.preview),
            "source_provenance": preview.get("source_provenance"),
            "cache_files_scanned": len(paths),
            "summary": dict(counts),
            "results": results,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(output, file, ensure_ascii=False, indent=2)
            file.write("\n")

        print(f"Cached HTML files scanned: {len(paths)}")
        print(f"Unique source IDs found: {len(evidence)}")
        for status, count in counts.items():
            print(f"{status}: {count}")

        print("\nBy import matching status:")
        for match_status, statuses in sorted(by_match.items()):
            print(f"  {match_status}: {dict(statuses)}")

        print(f"\nSaved: {args.output}")
        print("No network requests or database changes.")

    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()