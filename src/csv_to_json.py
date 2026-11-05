import csv
import json
import re
from typing import Optional

def _first_number_5scale(s: str) -> Optional[float]:
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        num = float(m.group(0))
    except (TypeError, ValueError):
        return None

    s_lower = s.lower()
    if "%" in s_lower:
        val = num / 20.0
    elif "/10" in s_lower or (5.0 < num <= 10.0):
        val = num / 2.0
    elif "/5" in s_lower or num <= 5.0:
        val = num
    else:
        val = num / 20.0 if num > 10.0 else num

    return round(max(0.0, min(5.0, val)), 2)

def _parse_int(s: str) -> Optional[int]:
    if not s:
        return None
    # extract first integer in string
    m = re.search(r"\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None

def csv_to_json(csv_file, json_file):
    novels = []
    
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            novel = {
                "title": (row.get("novel_titles") or "").strip(),
                "url": row.get("url") or "",
                "rating": _first_number_5scale(row.get("review_ratings", "")), # float 0–5 or None
                "chapters": _parse_int(row.get("num_chapters", "")), # int or None
                "author": (row.get("author") or "").strip(),
                "translator": (row.get("translator") or "").strip(),
                "genres": [g.strip() for g in (row.get("genres") or "").split(";") if g.strip()],
            }
            novels.append(novel)
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(novels, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    csv_to_json("data/complete_data.csv", "data/novels.json")
