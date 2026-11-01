import html
import re
import unicodedata


def words(text):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def story_hints(novel):
    page = (novel.source_metadata or {}).get("novelupdates_page") or {}
    aliases = [novel.title, page.get("source_title"), *(page.get("associated_names") or [])]
    names = [words(name) for name in aliases if isinstance(name, str) and words(name)]

    def safe(text):
        normalized = " " + words(text) + " "
        return not any(" " + name + " " in normalized for name in names)

    clues = []
    genres = [g for g in page.get("genres", []) if safe(g)]
    if genres:
        clue = "Genres include " + " and ".join(genres[:2]) + "."
        if safe(clue):
            clues.append(clue)

    # use only explicit tags. A short whitelist avoids adult and spoiler-heavy labels.
    allowed = ("Cultivation", "Time Travel", "Reincarnation", "Virtual Reality",
               "Academy", "Dungeons", "Magic", "Kingdom Building", "Alchemy",
               "Survival", "Transmigration", "Level System", "World Hopping",
               "Weak to Strong", "Political Intrigue", "Monsters", "Dragons")
    tags = set(page.get("tags") or [])
    themes = [tag.lower() for tag in allowed if tag in tags and safe(tag)]
    if themes:
        clue = "Story tags include " + " and ".join(themes[:2]) + "."
        if safe(clue):
            clues.append(clue)

    synopsis = html.unescape(page.get("synopsis") or novel.synopsis or "")
    for sentence in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", synopsis):
        sentence = " ".join(sentence.split())
        if (40 <= len(sentence) <= 220 and safe(sentence)
                and not re.search(r'https?://|www\.|[<>]|(?:translator|synopsis|spoiler|volume \d|chapter \d)', sentence, re.I)
                and re.search(r'[.!?。！？][”"\']?$', sentence)):
            clues.append("From the synopsis: “" + sentence + "”")
            break
    return [clue for clue in clues if safe(clue)]
