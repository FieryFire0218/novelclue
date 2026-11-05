import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
from fetch_novelupdates import atomic_write
from preview_novelupdates_import import normalize_url


SEARCHES = {
    "zh": ("nu-chinese-candidates.htm", "https://www.novelupdates.com/series-finder/?sf=1&org=495&rct=1000&mrct=min&sort=sdate&order=desc"),
    "ko": ("nu-korean-candidates.htm", "https://www.novelupdates.com/series-finder/?sf=1&org=497&rct=1000&mrct=min&sort=sdate&order=desc"),
}


def search_parameters(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.novelupdates.com" or parts.path != "/series-finder/":
        raise ValueError("Unexpected Series Finder URL.")
    values = parse_qs(parts.query)
    if any(len(v) != 1 for v in values.values()):
        raise ValueError("Duplicate search parameters.")
    return {k: v[0] for k, v in values.items()}


def parse_listing(html, source_url, language):
    params = search_parameters(source_url)
    if params.get("org") != {"zh": "495", "ko": "497"}[language]:
        raise ValueError("Language and search URL disagree.")
    if params.get("mrct") != "min" or not params.get("rct", "").isdigit():
        raise ValueError("Expected a minimum-reader filter.")
    minimum = int(params["rct"])
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".search_main_box_nu")
    if not cards:
        raise ValueError("No result cards found; page may be blocked, empty, or changed.")

    pagination = soup.select_one(".digg_pagination")
    current = pagination.select_one(".current") if pagination else None
    page = int(params.get("pg", "1"))
    if current and current.get_text(strip=True) != str(page):
        raise ValueError("Displayed page number differs from the requested page.")

    candidates = []
    seen = set()
    for card in cards:
        title_link = card.select_one(".search_title a[href]")
        reader_icon = card.select_one('.search_stats [title="Readers"]')
        language_node = card.select_one(".search_ratings .orgcn, .search_ratings .orgkr")
        if not title_link or not reader_icon or not language_node:
            raise ValueError("Result card is missing a title, readers, or language.")
        if language_node.get_text(strip=True) != {"zh": "CN", "ko": "KR"}[language]:
            raise ValueError("A result card has the wrong language; filters may not have applied.")
        match = re.search(r"([\d,]+)\s+Readers\b", reader_icon.parent.get_text(" ", strip=True))
        if not match:
            raise ValueError("Could not parse the card's reader count.")
        readers = int(match.group(1).replace(",", ""))
        if readers < minimum:
            raise ValueError("A result is below the reader minimum; check the search filters.")
        url = normalize_url(urljoin(source_url, title_link["href"]))
        if url in seen:
            raise ValueError("Repeated series within a result page.")
        seen.add(url)
        # limit genre extraction to genre links, excluding the Completed badge.
        genres = [a.get_text(" ", strip=True) for a in card.select(".search_genre a[href]")
                  if urlsplit(a["href"]).path.startswith("/genre/")]
        candidates.append({
            "novelupdates_url": url,
            "source_title": title_link.get_text(" ", strip=True),
            "original_language": language,
            "listing_readers": readers,
            "listing_genres": genres,
            "discovered_from": source_url,
        })

    next_link = pagination.select_one("a.next_page[href]") if pagination else None
    next_url = urljoin(source_url, next_link["href"]) if next_link else None
    if next_url:
        next_params = search_parameters(next_url)
        if int(next_params.get("pg", "1")) != page + 1:
            raise ValueError("Next-page link does not advance by one page.")
        if {k:v for k,v in params.items() if k != "pg"} != {k:v for k,v in next_params.items() if k != "pg"}:
            raise ValueError("Next-page link changes search filters.")
    return candidates, next_url


def merge_candidates(target, records):
    for record in records:
        url = record["novelupdates_url"]
        if url in target and target[url]["original_language"] != record["original_language"]:
            raise ValueError("One series appeared under conflicting languages.")
        target.setdefault(url, record)


def browser_discovery(args):
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = None
    candidates = {}
    requested = False
    try:
        for language, (_, start_url) in SEARCHES.items():
            url = start_url
            for page in range(1, args.max_pages + 1):
                cache_file = args.cache / (hashlib.sha256(url.encode()).hexdigest() + ".html")
                if cache_file.exists() and not args.refresh:
                    records, next_url = parse_listing(cache_file.read_bytes(), url, language)
                    print(f"CACHED {language} page {page}: {len(records)} candidates", flush=True)
                else:
                    if driver is None:
                        options = webdriver.FirefoxOptions() if args.browser == "firefox" else webdriver.ChromeOptions()
                        options.page_load_strategy = "eager"
                        driver = webdriver.Firefox(options=options) if args.browser == "firefox" else webdriver.Chrome(options=options)
                        driver.set_page_load_timeout(45)
                    if requested:
                        time.sleep(5)
                    requested = True
                    print(f"FETCHING {language} page {page}: {url}", flush=True)
                    driver.get(url)
                    WebDriverWait(driver, 90).until(
                        lambda d: d.find_elements(By.CSS_SELECTOR, ".search_main_box_nu .search_title a"),
                        message="Results did not load. Complete visible verification if prompted.",
                    )
                    html = driver.page_source
                    records, next_url = parse_listing(html, url, language)
                    atomic_write(cache_file, html)
                    print(f"SAVED {language} page {page}: {len(records)} candidates", flush=True)
                merge_candidates(candidates, records)
                if not next_url:
                    break
                if page == args.max_pages:
                    print(f"Stopped {language} at the requested page limit; more pages exist.")
                url = next_url
    except (TimeoutException, WebDriverException) as error:
        try:
            title = driver.title if driver else "(browser unavailable)"
        except WebDriverException:
            title = "(unavailable)"
        raise ValueError(f"Browser collection failed: {type(error).__name__}; title={title!r}. "
                         "No new candidate JSON written; validated pages remain cached.") from error
    finally:
        if driver:
            try:
                driver.quit()
            except WebDriverException:
                pass
    return list(candidates.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-dir", type=Path, help="Read the two saved first pages without a browser")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=2, help="Maximum pages PER language; default 2")
    parser.add_argument("--cache", type=Path, default=Path("data/nu_finder_cache"))
    parser.add_argument("--browser", choices=("firefox", "chrome"), default="firefox")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.max_pages < 1:
            raise ValueError("--max-pages must be positive.")
        if args.output.suffix.lower() != ".json":
            raise ValueError("Output must have a .json extension.")
        if args.output.exists() and not args.overwrite:
            raise ValueError("Output exists; use --overwrite to replace it.")
        if args.saved_dir:
            combined = {}
            for language, (filename, url) in SEARCHES.items():
                records, _ = parse_listing((args.saved_dir / filename).read_bytes(), url, language)
                merge_candidates(combined, records)
                print(f"PARSED {language}: {len(records)} candidates")
            records = list(combined.values())
        else:
            records = browser_discovery(args)
        atomic_write(args.output, json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(f"Saved {len(records)} unique candidates to {args.output}")
        print("Discovery only. No novel detail pages fetched; no database changes made.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
