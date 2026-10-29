import argparse
import hashlib
import json
import os
import re

from bs4 import BeautifulSoup
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone

from page_provenance import read_cache, write_cache

from parse_novelupdates import parse_html
from page_provenance import normalize_series_url as normalize_url


def load_urls(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not data:
        raise ValueError("Input must be a nonempty JSON array.")
    urls = []
    for item in data:
        value = item.get("novelupdates_url") if isinstance(item, dict) else item
        if not isinstance(value, str):
            raise ValueError("Each input needs a NovelUpdates URL.")
        url = normalize_url(value)
        if url not in urls:
            urls.append(url)
    return urls


def cache_path(directory, url):
    return directory / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html")


def validate_page(html, url, filename, fetched_at=None):
    record = parse_html(html, filename, fetched_at=fetched_at)
    if normalize_url(record["novelupdates_url"]) != url:
        raise ValueError("Page canonical URL differs from the requested series.")
    if record["warnings"]:
        raise ValueError("Incomplete page: " + "; ".join(record["warnings"]))
    return record


def validate_id_page(html, source_id, filename, fetched_at=None):
    """Require the page's own ID; a successful redirect alone is not identity."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select("input#mypostid")
    if len(nodes) != 1:
        raise ValueError("Expected exactly one page source-ID marker.")
    value = nodes[0].get("value", "")
    if not re.fullmatch(r"[1-9]\d*", value) or int(value) != source_id:
        raise ValueError("Page source ID differs from requested source ID.")
    canonicals = soup.select('link[rel="canonical"]')
    if len(canonicals) != 1:
        raise ValueError("Expected exactly one canonical series URL.")
    canonical = normalize_url(canonicals[0].get("href"))
    record = validate_page(html, canonical, filename, fetched_at)
    record["source_novel_id"] = source_id
    return record


def validate_target(html, target, filename, fetched_at=None):
    if type(target) is int:
        return validate_id_page(html, target, filename, fetched_at)
    return validate_page(html, target, filename, fetched_at)


def lookup_url(target):
    if type(target) is int:
        if target <= 0:
            raise ValueError("Source IDs must be positive integers.")
        return f"https://www.novelupdates.com/?p={target}"
    return normalize_url(target)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(urls, cache, browser, refresh=False):
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = None
    records = []
    requested = False
    try:
        for target in urls:
            url = lookup_url(target)
            path = cache_path(cache, url)
            if path.exists() and not refresh:
                html, fetched_at, observed_url = read_cache(path)
                record = validate_target(html, target, path.name, fetched_at=fetched_at)
                if observed_url and normalize_url(observed_url) != record["novelupdates_url"]:
                    raise ValueError("Cache URL metadata differs from validated page URL.")
                records.append(record)
                print(f"CACHED: {record['source_title']}", flush=True)
                continue

            if driver is None:
                if browser == "firefox":
                    options = webdriver.FirefoxOptions()
                    options.page_load_strategy = "eager"
                    driver = webdriver.Firefox(options=options)
                else:
                    options = webdriver.ChromeOptions()
                    options.page_load_strategy = "eager"
                    driver = webdriver.Chrome(options=options)
                driver.set_page_load_timeout(45)

            if requested:
                time.sleep(5)  
            requested = True
            print(f"FETCHING: {url}", flush=True)
            try:
                driver.get(url)

                def series_ready(current):
                    title = current.title.casefold()
                    if any(marker in title for marker in (
                        "just a moment", "access denied", "attention required",
                        "verify you are human", "security verification",
                    )):
                        return False
                    return (
                        current.find_elements(By.CSS_SELECTOR, ".seriestitlenu")
                        and current.find_elements(By.CSS_SELECTOR, "#editdescription")
                        and current.find_elements(By.CSS_SELECTOR, ".rlist")
                    )

                WebDriverWait(driver, 60).until(
                    series_ready,
                    message=(
                        "The series page did not become available within "
                        "60 seconds. Verification may still be blocking it."
                    ),
                )
                html = driver.page_source
                fetched_at = datetime.now(timezone.utc).isoformat()
                record = validate_target(html, target, path.name, fetched_at=fetched_at)
            except (TimeoutException, WebDriverException, ValueError) as error:
                try:
                    page_title = driver.title
                    current_url = driver.current_url
                except WebDriverException:
                    page_title = "(unavailable)"
                    current_url = "(unavailable)"

                reason = str(error).strip() or type(error).__name__

                raise ValueError(
                    f"Collection stopped at {url}\n"
                    f"Reason: {reason}\n"
                    f"Browser title: {page_title}\n"
                    f"Browser URL: {current_url}\n"
                    "No new preview was written. "
                    "Previously validated pages remain cached."
                ) from error

            write_cache(path, html, record["novelupdates_url"], fetched_at)
            records.append(record)
            print(f"SAVED: {record['source_title']}", flush=True)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="Existing URL-list JSON input")
    parser.add_argument("--ids", nargs="+", type=int,
                        help="Small ID lookup test (1–5 unique positive IDs); no input JSON")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/nu_cache"))
    parser.add_argument("--browser", choices=("firefox", "chrome"), default="firefox")
    parser.add_argument("--refresh", action="store_true", help="Fetch again instead of using cached pages")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output JSON")
    args = parser.parse_args()
    try:
        if (args.input is None) == (args.ids is None):
            raise ValueError("Provide either an input JSON file or --ids, not both.")
        if args.ids is not None and (
            len(args.ids) > 5 or any(i <= 0 for i in args.ids)
            or len(set(args.ids)) != len(args.ids)
        ):
            raise ValueError("ID test requires 1–5 unique positive IDs.")
        if args.input is not None and args.input.resolve() == args.output.resolve():
            raise ValueError("Use different input and output files.")
        if args.output.exists() and not args.overwrite:
            raise ValueError("Output exists; use --overwrite to replace it.")
        urls = args.ids if args.ids is not None else load_urls(args.input)
        records = collect(urls, args.cache, args.browser, args.refresh)
        atomic_write(args.output, json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(f"Saved {len(records)} records to {args.output}")
        print("No database changes were made.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
