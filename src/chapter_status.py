import re
import unicodedata

VERSION = "chapters-v1"
N = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
STATUSES = {"complete": "completed", "completed": "completed", "ongoing": "ongoing",
            "hiatus": "hiatus", "dropped": "dropped", "cancelled": "cancelled", "canceled": "cancelled"}
STATUS_RE = r"\b(?:completed|complete|ongoing|hiatus|dropped|cancelled|canceled)\b"


def number(value):
    result = int(value.replace(",", ""))
    if not 0 <= result <= 2147483647:
        raise ValueError("Chapter count outside supported range")
    return result


def _clean(line):
    line = re.sub(r"\((?:" + STATUS_RE + r")\)", "", line)
    line = re.sub(r"\(released[^)]*\)", "", line)
    line = re.sub(r"\s*[-–—]\s*" + STATUS_RE + r"\s*$", "", line)
    return line.strip(" \t-–—:()⊱•*")


def parse_chapter_status(raw):
    out = {"original_chapters_total": None, "original_chapters_main": None,
           "original_chapters_extra": None, "publication_status": "unknown",
           "main_publication_status": "unknown", "chapter_status_raw": raw,
           "chapter_count_method": "unresolved", "chapter_parser_version": VERSION,
           "chapter_notes": []}
    if not isinstance(raw, str) or not raw.strip():
        out["chapter_notes"].append("No original chapter status supplied.")
        return out
    content = unicodedata.normalize("NFKC", raw).casefold()
    # repair only a wrapped release-date annotation / plus continuation.
    content = re.sub(r"\n\s*(?=\(released|\+)", " ", content)
    all_status = {STATUSES[s] for s in re.findall(STATUS_RE, content)}
    if len(all_status) == 1:
        out["publication_status"] = next(iter(all_status))
    elif len(all_status) > 1:
        out["chapter_notes"].append("Different sections report different publication statuses.")

    main, extras, headers, explicit, parts = [], [], [], [], {}
    main_status = set()
    invalid = False
    uncounted = False
    notes = out["chapter_notes"]
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        line = _clean(raw_line)
        if "main story" in line:
            main_status.update(STATUSES[s] for s in re.findall(STATUS_RE, raw_line))
        total_match = re.fullmatch(rf"(?:({N})\s+(?:total|overall)\s+chapters?|(?:total|overall)\s+chapters?\s*:?\s*({N}))", line)
        if total_match:
            explicit.append(number(total_match[1] or total_match[2]))
            continue

        # explicitly separate main chapters + one or more extras/bonus chapters.
        # bare 'side stories' are not assumed to be one chapter each.
        expr = re.fullmatch(rf"(?:main story\s*[-:]?\s*)?({N})\s+(?:wn\s+)?chapters?\s*((?:\+\s*{N}\s+(?:extras?|extra chapters?|bonus chapters?|side story chapters?)\s*)+)", line)
        if expr:
            main.append(number(expr[1]))
            extras.append(sum(number(v) for v in re.findall(rf"\+\s*({N})", expr[2])))
            continue
        partial_main = re.match(rf"({N})\s+(?:wn\s+)?chapters?\s*\+", line)
        if partial_main:
            # preserve a clear main-story count even if the remaining units (e.g. '3 side stories') cannot be converted to chapter counts.
            main.append(number(partial_main[1]))
            invalid = True
            uncounted = True
            notes.append("Extra material has unsupported or ambiguous units: " + raw_line.strip())
            continue

        main_match = re.fullmatch(rf"main story\s*[-:]?\s*(?:({N})\s+chapters?|chapters?\s*({N}))", line)
        if main_match:
            main.append(number(main_match[1] or main_match[2]))
            continue
        extra_match = re.fullmatch(rf"(?:(?:extras?|side stor(?:y|ies)|bonus)\s*[-:]?\s*(?:({N})\s+chapters?|chapters?\s*({N}))|({N})\s+(?:extras?|extra chapters?|bonus chapters?|side story chapters?))", line)
        if extra_match:
            extras.append(number(next(v for v in extra_match.groups() if v is not None)))
            continue

        # a header may state volumes and chapters, in either order.
        chapter_atom = rf"({N})\s+(?:wn\s+)?chapters?"
        volume_atom = rf"{N}\s+volumes?"
        header = re.fullmatch(rf"(?:{volume_atom}\s*/\s*)?{chapter_atom}(?:\s*/\s*{volume_atom})?", line)
        if header:
            headers.append(number(header[1]))
            continue
        part = re.fullmatch(rf"(?:part\s*({N})|({N})\s*season)\s*:\s*(?:{volume_atom}\s*/\s*)?{chapter_atom}(?:\s*/\s*{volume_atom})?", line)
        if part:
            key = ("part" if part[1] else "season", number(part[1] or part[2]))
            value = number(part[3])
            if key in parts and parts[key] != value:
                invalid = True
            parts[key] = value
            continue
        if re.search(r"\b(?:extras?|side stor(?:y|ies)|bonus|prologue|epilogue)\b", line):
            uncounted = True
        if re.search(r"\d.*chapters?|chapters?.*\d", line):
            # numeric chapter text exists but doesn't match a supported grammar.
            invalid = True
            notes.append("Unsupported chapter expression: " + raw_line.strip())

    def unique(values, label):
        nonlocal invalid
        if len(set(values)) > 1:
            invalid = True
            notes.append("Conflicting or non-disjoint " + label + " counts.")
            return None
        return values[0] if values else None

    m = unique(main, "main-story")
    e = unique(extras, "extra")
    h = unique(headers, "header")
    total = unique(explicit, "explicit total")
    if m is None and h is not None and e is not None and not main:
        # a separate extra line after an unlabeled chapter line is additive.
        m, h = h, None
    out["original_chapters_main"], out["original_chapters_extra"] = m, e
    if len(main_status) == 1:
        out["main_publication_status"] = next(iter(main_status))
    elif m is not None and out["publication_status"] == "completed":
        out["main_publication_status"] = "completed"
    if uncounted:
        notes.append("Some side material has no explicit chapter count.")
    if total is None:
        total = h
    elif h is not None and h != total and h != m:
        invalid = True
        notes.append("Header and explicit total disagree.")
    if total is not None and m is not None and e is not None:
        if total < m + e or (not uncounted and total != m + e):
            invalid = True
            notes.append("Reported total disagrees with the breakdown.")
    if total is not None and parts:
        if sum(parts.values()) != total:
            invalid = True
            notes.append("Part/season breakdown disagrees with total.")
    if not invalid and total is not None:
        out["original_chapters_total"] = total
        out["chapter_count_method"] = "reported"
    elif not invalid and not uncounted and m is not None and e is not None:
        if m + e <= 2147483647:
            out["original_chapters_total"] = m + e
            out["chapter_count_method"] = "calculated"
    if out["original_chapters_total"] is None:
        notes.append("No reliable total; known component counts are retained separately.")
    return out
