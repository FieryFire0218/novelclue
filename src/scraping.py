from bs4 import BeautifulSoup
import json
import time
import csv
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from concurrent.futures import ProcessPoolExecutor, as_completed

start_url = "https://www.wuxiaworld.com/novels"

def create_webdriver():
    # try Chrome first
    try:
        copts = ChromeOptions()
        copts.add_argument("--headless=new")
        copts.add_argument("--disable-gpu")
        copts.add_argument("--no-sandbox")
        copts.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=copts)
        return driver
    except WebDriverException as e:
        print(f"[WARN] Chrome launch failed: {e}. Falling back to Firefox...")
    # fallback to Firefox
    fopts = FirefoxOptions()
    fopts.add_argument("--headless")
    fopts.add_argument("--disable-gpu")
    try:
        driver = webdriver.Firefox(options=fopts)
        return driver
    except WebDriverException as e:
        raise RuntimeError(
            "No browser could be launched. Ensure Chrome or Firefox is installed and drivers are available."
        ) from e

def scraper(url):
    driver = create_webdriver()
    try:
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            print(f"Timed out waiting for page to load: {url}")
            return None

        soup = BeautifulSoup(driver.page_source, "html.parser")

        # titles
        novel_titles = []
        for h1 in soup.find_all("h1", class_="font-set-b24 text-gray-t1 line-clamp-2 sm2:font-set-b32"):
            novel_titles.append(h1.text.strip())

        # review ratings
        review_ratings = []
        script_tags = soup.select("script[type='application/ld+json'][data-rh='true']")
        for script_tag in script_tags:
            json_data = json.loads(script_tag.text)
            rating_value = json_data.get('aggregateRating', {}).get('ratingValue')
            if rating_value is not None:
                review_ratings.append(rating_value)

        # number of chapters
        chapters_div = soup.find("div", class_="font-set-sb14 text-gray-750 break-word line-clamp-2 sm2:font-set-sb16 dark:text-gray-300 sm2:text-gray-800")
        num_chapters = None
        if chapters_div:
            text = chapters_div.get_text(strip=True)
            if "Chapters" in text:
                num_chapters = text.split()[0]

        # author
        author = None
        author_label = soup.find("div", string="Author:")
        if author_label:
            author_div = author_label.find_next_sibling("div", class_="font-set-sb15 break-word line-clamp-1 sm2:font-set-sb15")
            if author_div:
                author = author_div.get_text(strip=True)

        # translator
        translator = None
        translator_label = soup.find("div", string="Translator:")
        if translator_label:
            translator_div = translator_label.find_next_sibling("div", class_="font-set-sb15 break-word line-clamp-1 sm2:font-set-sb15")
            if translator_div:
                translator = translator_div.get_text(strip=True)

        # genres
        genres = []
        genre_links = soup.find_all("a", class_="MuiTypography-root MuiTypography-inherit MuiLink-root MuiLink-underlineNone ww-1uhr7d7")
        for link in genre_links:
            genre = link.get_text(strip=True)
            if genre:
                genres.append(genre)

        print(f"Scraped: {url} | Title: {novel_titles[0] if novel_titles else 'N/A'}")
        return {
            "url": url, 
            "novel_titles": "; ".join(novel_titles),
            "review_ratings": "; ".join(str(r) for r in review_ratings),
            "num_chapters": num_chapters,
            "author": author,
            "translator": translator,
            "genres": "; ".join(genres)
        }
    finally:
        driver.quit()
        

def get_novel_urls(start_url):
    print("Loading main page and extracting novel URLs...")
    driver = create_webdriver()
    try:
        driver.get(start_url)
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        #scroll to load all content
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        soup = BeautifulSoup(driver.page_source, "html.parser")
        novel_urls = set()
        for link in soup.find_all("a"):
            href = link.get("href")
            if href and href.startswith("/novel/") and href != "/novel/" and len(href.split("/")) == 3:
                novel_url = "https://www.wuxiaworld.com" + href
                novel_urls.add(novel_url)
        print(f"Found {len(novel_urls)} novel URLs.")
        return list(novel_urls)
    finally:
        driver.quit()

def parallel_scrape(novel_urls, max_workers=4):
    scraped_novels = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(scraper, url): url for url in novel_urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result = future.result()
                if result:
                    scraped_novels.append(result)
            except Exception as e:
                print(f"Error scraping {url}: {e}")
    return scraped_novels


if __name__ == "__main__":
    novel_urls = get_novel_urls(start_url)
    print(f"Total novels to scrape: {len(novel_urls)}")
    scraped_novels = parallel_scrape(novel_urls, max_workers=4)
    print(f"Total novels scraped: {len(scraped_novels)}")

    # Write to CSV
    fieldnames = ["url", "novel_titles", "review_ratings", "num_chapters", "author", "translator", "genres"]
    out_path = Path(__file__).resolve().parent.parent / "data" / "complete_data.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for novel in scraped_novels:
            writer.writerow(novel)

    print("Data saved to complete_data.csv")

#result = requests.get(start_url) 
#result.encoding = "utf-8"
#doc = BeautifulSoup(result.text, "html.parser")

#print(doc.prettify().encode("utf-8"))

#with open("prettified_main.html", "w", encoding="utf-8") as file:
#    file.write(doc.prettify())