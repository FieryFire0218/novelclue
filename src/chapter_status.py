import re
import unicodedata

VERSION = "chapters-v6"
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


def _parse_legacy(raw):
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
            # preserve a clear main-story count even if the remaining units
            # (e.g. '3 side stories') cannot be converted to chapter counts.
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


def _parse_v3(raw):
    out = _parse_v2(raw)
    if not isinstance(raw, str) or out['original_chapters_total'] is not None:
        return out
    content = unicodedata.normalize('NFKC', raw).casefold()
    # a labeled heading can wrap before its explicitly counted chapter line.
    content = re.sub(r'(main story|side story)\s*:\s*\n\s*', r'\1: ', content)
    # a reported total in parentheses disambiguates separately labeled extras.
    inline = re.fullmatch(rf'\s*({N})\s+chapters?((?:\s*\+\s*{N}\s+(?:new |little weibo )?extras?)+)\s*\(({N})\s+({STATUS_RE})\)\s*', content)
    if inline:
        main = number(inline[1])
        extra = sum(number(n) for n in re.findall(rf'\+\s*({N})', inline[2]))
        if main + extra == number(inline[3]):
            out.update(original_chapters_total=main+extra, original_chapters_main=main,
                       original_chapters_extra=extra, publication_status=STATUSES[inline[4]],
                       main_publication_status=STATUSES[inline[4]], chapter_count_method='reported', chapter_notes=[])
        return out
    labels = r'(?:main story|main|side stories|side story|bonus story|prologue|epilogue|afterwords?|extras?)'
    components = {}
    statuses = {}
    total = None
    header_status = None
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        # only this supported parenthetical is normalized, not arbitrary text.
        line = _clean(re.sub(r'\(total\s+('+STATUS_RE+r')\)', r'(\1)', raw_line))
        head = re.fullmatch(rf'({N})\s+chapters?', line)
        if head:
            if total is not None:
                return out
            total = number(head[1])
            status = {STATUSES[v] for v in re.findall(STATUS_RE, raw_line)}
            header_status = next(iter(status)) if len(status)==1 else None
            continue
        prefix = re.fullmatch(rf'({labels})\s*:\s*(?:{N}\s+volumes?\s*/\s*)?({N})\s+(?:side story\s+)?chapters?', line)
        suffix = re.fullmatch(rf'(?:{N}\s+volumes?\s*/\s*)?({N})\s+chapters?\s*\(({labels})\)', line)
        # _clean strips trailing parentheses; restore label parsing explicitly.
        if not suffix:
            suffix = re.fullmatch(rf'(?:{N}\s+volumes?\s*/\s*)?({N})\s+chapters?\s*\(({labels})', line)
        if prefix:
            label, count = prefix[1], number(prefix[2])
        elif suffix:
            label, count = suffix[2], number(suffix[1])
        else:
            return out
        label = {'main':'main story','side stories':'side story','afterwords':'afterword','extras':'extra'}.get(label,label)
        if label in components:
            return out
        components[label] = count
        statuses[label] = {STATUSES[v] for v in re.findall(STATUS_RE, raw_line)}
    if 'main story' not in components or len(components)<2:
        return out
    calculated = sum(components.values())
    if calculated > 2147483647 or (total is not None and total != calculated):
        out['chapter_notes'].append('Reported total disagrees with labeled chapter components.')
        return out
    main = components['main story']
    main_status = statuses['main story']
    out.update(original_chapters_total=calculated, original_chapters_main=main,
               original_chapters_extra=calculated-main, chapter_count_method='reported' if total is not None else 'calculated',
               main_publication_status=next(iter(main_status)) if len(main_status)==1 else 'unknown', chapter_notes=[])
    if header_status:
        out['publication_status'] = header_status
    return out


def _parse_v2(raw):
    out = _parse_legacy(raw)
    if out['original_chapters_total'] is not None:
        return out
    if not isinstance(raw, str):
        return out
    lines = [line.strip() for line in unicodedata.normalize('NFKC', raw).casefold().splitlines() if line.strip()]
    # a colon introduces a breakdown of the headline total, not additions to it.
    header = re.fullmatch(rf'({N})\s+chapters?\s*\(({STATUS_RE})\)\s*:', lines[0]) if lines else None
    if not header or len(lines) < 2:
        return out
    components = []
    keys = set()
    main_count = extra_count = 0
    main_statuses = set()
    afterword = False
    kind = None
    for raw_line in lines[1:]:
        line = _clean(raw_line)
        statuses = {STATUSES[s] for s in re.findall(STATUS_RE, raw_line)}
        part = re.fullmatch(rf'part\s+({N})(?:\s+"[^"]+")?\s*:\s*({N})\s+chapters?(?:\s*\+\s*({N})\s+extra chapters?)?', line)
        item = re.fullmatch(rf'({N})\s+(main story chapters?|extra chapters?|side story chapters?|afterwords?)', line)
        if part:
            if kind == 'items':
                return out
            kind = 'parts'
            key = ('part', number(part[1]))
            main = number(part[2])
            extra = number(part[3]) if part[3] else 0
            main_statuses.update(statuses)
        elif item:
            if kind == 'parts':
                return out
            kind = 'items'
            key = item[2].rstrip('s')
            is_main = key == 'main story chapter'
            main = number(item[1]) if is_main else 0
            extra = 0 if is_main else number(item[1])
            if is_main:
                main_statuses.update(statuses)
            afterword |= key == 'afterword'
        else:
            return out
        if key in keys:
            return out
        keys.add(key)
        main_count += main
        extra_count += extra
        components.append(main + extra)
    total = number(header[1])
    if sum(components) != total:
        out['original_chapters_total'] = None
        out['chapter_count_method'] = 'unresolved'
        out['chapter_notes'].append('Headline total disagrees with the counted breakdown.')
        return out
    if kind == 'items' and 'main story chapter' not in keys:
        return out
    out.update(original_chapters_total=total,
               original_chapters_main=main_count,
               original_chapters_extra=extra_count,
               publication_status=STATUSES[header[2]],
               main_publication_status=(next(iter(main_statuses)) if len(main_statuses) == 1 else 'unknown'),
               chapter_count_method='reported', chapter_notes=[])
    if afterword:
        out['chapter_notes'].append('Reported total includes the explicitly counted afterword; included in extra count.')
    return out


def _parse_v4(raw):
    out = _parse_v3(raw)
    notes = out['chapter_notes']
    # only fall back for uncounted extras, not inconsistent reported totals.
    if (out['original_chapters_total'] is None
            and out['original_chapters_main'] is not None
            and 'Some side material has no explicit chapter count.' in notes
            and not any('conflict' in note.lower() or 'disagree' in note.lower() for note in notes)):
        out['original_chapters_total'] = out['original_chapters_main']
        out['chapter_count_method'] = 'main_only'
        out['chapter_notes'] = [note for note in notes if not note.startswith('No reliable total;')]
        out['chapter_notes'].append('Using known main-story chapters as the game count; uncounted extras are excluded.')
    return out


def _normalize_v5(raw):
    value = unicodedata.normalize('NFKC', raw).casefold().replace('compeleted','completed')
    value = re.sub(r'\b(?:on hiatus|indefinite hiatus|hiatus indefinitely)\b','hiatus',value)
    value = re.sub(r'\(\s*(complete[d]?|ongoing|hiatus|dropped)\s*\)',r'(\1)',value)
    value = re.sub(r'\bside-stor(?:y|ies)\b|\bsidestory\b','side story',value)
    value = re.sub(r'\bside stories chapters\b','side story chapters',value)
    value = re.sub(r'\bs(\d+)\s*:',r'season \1:',value)
    value = re.sub(r'\bextra-story\b','extra',value)
    value = re.sub(r'\bchapters?\s*:\s*('+N+r')\s+chapters?',r'\1 chapters',value)
    # normalize wrapped status/quantity expressions, keeping the status explicit.
    lines=[]
    for line in value.splitlines():
        line=line.strip(' \t•⊱—–-;.')
        line=re.sub(r'\bchapters?\s*:?\s*('+N+r')\b',r'\1 chapters',line)
        line=re.sub(r'\[('+STATUS_RE+r')\]',r'(\1)',line)
        if not line:continue
        # translation counts describe a different unit/split than original chapters.
        if re.search(r'translat|english version|licensed english',line):
            if not re.search(r'\bchapters?\b',line) or re.search(r'(?:translat|english version)',line):
                continue
        m=re.fullmatch(r'('+STATUS_RE+r')\s*[, :]?\s*[\[(](.*)[\])]',line)
        if m:line=m[2]+' ('+m[1]+')'
        line=re.sub(r'^('+STATUS_RE+r')\s*[, :]?\s+(?=\d)',r'(\1) ',line)
        line=re.sub(r'\(('+N+r'\s+chapters?)\)',r'\1',line)
        if 'chapter' in line:
            line=re.sub(r'\b'+N+r'\s+(?:web\s+)?(?:volumes?v?|books?)\s*[/,:|—–-]*\s*','',line)
            line=re.sub(r'\bvolumes?\s+'+N+r'\s*[/|]\s*','',line)
            line=re.sub(r'\s*[-/]\s*'+N+r'\s+parts?','',line)
            line=re.sub(r'\(\d+\s+arcs?,\s*('+STATUS_RE+r')\)',r'(\1)',line)
            line=re.sub(r'\(including prologue and epilogue\)','',line)
            line=re.sub(r'\s*/+\s*(?=\()', ' ',line)
            line=re.sub(r'\(('+STATUS_RE+r')\)\s*\(\1\)',r'(\1)',line)
            line=line.strip(' /:;.,')
        elif re.fullmatch(N+r'\s+(?:web\s+)?(?:volumes?|books?)\s*(?:\('+STATUS_RE+r'\))?',line):
            volume_status=re.findall(STATUS_RE,line)
            if volume_status:lines.append(volume_status[0])
            continue
        line=re.sub(r'^wn:\s*','',line)
        if re.fullmatch(r'ln:\s*'+N+r'\s+volumes?\s*\('+STATUS_RE+r'\)',line):continue
        line=re.sub(r'(?<=\S)\s+('+STATUS_RE+r')$',r' (\1)',line)
        lines.append(line)
    return '\n'.join(lines)


def _expanded_breakdown(text):
    """Accept only fully recognized, reconciled chapter components."""
    counts=[];header=None;header_status=None;main=None;extras=0;seen=set();parts=[]
    label_pattern=r'(?:main(?: story)?|side stor(?:y|ies)(?:\s*(?:\[part\.\d+\]|#?\d+))?|extra[s]?|bonus(?: story)?|special(?: side story| story)?|gaiden|epilogue|prologue|afterwords?|after story|spin[ -]?off|if(?: side stor(?:y|ies))?|dlc|season pass|abduction|part\s+\d+(?:\s+"[^"]+")?|season\s+\d+(?: epilogue)?|volume\s+\d+(?:\.\d+)?(?:\s*\(if side story\))?)'
    overall_statuses=set();main_statuses=set()
    for raw_line in text.splitlines():
        if re.fullmatch(STATUS_RE,raw_line.strip(' ()')):
            overall_statuses.add(STATUSES[raw_line.strip(' ()')]);continue
        statuses={STATUSES[s] for s in re.findall(STATUS_RE,raw_line)}
        line=re.sub(r'\('+STATUS_RE+r'\)','',raw_line)
        line=re.sub(r'\b'+STATUS_RE+r'\b\)?\s*$','',line).strip(' :;.,-')
        line=re.sub(r'\((?:paid chapters|\d+\s*-\s*\d+|\d+|\d+ episodes)\)','',line).strip()
        line=re.sub(r'\(?r-?\d+\)?','',line).strip(' -')
        line=re.sub(r'\s+',' ',line)
        line=re.sub(r'\bau chapters\b','chapters',line)
        head=re.fullmatch(r'(?:total(?: chapters?)?\s*:?\s*)?('+N+r')\s+(?:total\s+)?chapters?',line)
        if head:
            if header is not None:return None
            header=number(head[1]);header_status=next(iter(statuses)) if len(statuses)==1 else None;continue
        prefix=re.fullmatch(r'('+label_pattern+r')\s*[-:]?\s*('+N+r')\s+(?:side story\s+)?chapters?',line)
        suffix=re.fullmatch(r'('+N+r')\s+(?:('+label_pattern+r')\s+chapters?|chapters?\s*[-,(]?\s*('+label_pattern+r')\)?)',line)
        if prefix:label,n=prefix[1],number(prefix[2])
        elif suffix:label,n=suffix[2] or suffix[3],number(suffix[1])
        else:return None
        label=re.sub(r'stories','story',label)
        if label in seen:return None
        seen.add(label);counts.append(n)
        if label in ('main','main story'):
            if main is not None:return None
            main=n;main_statuses=statuses
        elif label.startswith('part '):parts.append(n)
        else:extras+=n
    if not counts:return None
    total=sum(counts)
    # parts nested under a stated main total are checked, never counted twice.
    if main is not None and parts:
        if sum(parts)!=main:return None
        total-=sum(parts)
    if total>2147483647 or (header is not None and header!=total):return None
    if header is None and main is None:
        # only a homogeneous numbered partition is safely additive without a total.
        if not (all(re.fullmatch(r'(?:part|season|volume)\s+\d+',k) for k in seen) and len(seen)>1):return None
    status=header_status or (next(iter(overall_statuses)) if len(overall_statuses)==1 else None)
    return dict(original_chapters_total=total,original_chapters_main=main,
                original_chapters_extra=(total-main if main is not None else None),
                chapter_count_method='reported' if header is not None else 'calculated',
                _status=status,_main_status=next(iter(main_statuses)) if len(main_statuses)==1 else None)


def _parse_v5(raw):
    out=_parse_v4(raw)
    if not isinstance(raw,str) or not raw.strip():return out
    normalized=_normalize_v5(raw)
    candidate=_parse_v4(normalized)
    # normalization must not erase an entire source expression or invent units.
    if (out['original_chapters_total'] is None and candidate['original_chapters_total'] is not None
            and candidate['chapter_count_method'] != 'main_only'
            and not any(re.search(r'\d', line) and 'chapter' not in line and not re.fullmatch(STATUS_RE,line.strip(' ()')) for line in normalized.splitlines())):
        out.update(candidate)
        out['chapter_notes'].append('Parsed normalized punctuation, labels, or volume/translation annotations.')
    expanded=_expanded_breakdown(normalized)
    if expanded and (out['original_chapters_total'] is None or out['chapter_count_method']=='main_only' or out['publication_status']=='unknown'):
        status=expanded.pop('_status');main_status=expanded.pop('_main_status')
        out.update(expanded);out['chapter_notes']=[]
        if status:out['publication_status']=status
        if main_status:out['main_publication_status']=main_status
    if out['original_chapters_total'] is None:
        # uncounted framing material does not prevent a main-only game count.
        stripped=re.sub(r'^(?:prologue|preface)\s*\+\s*','',normalized)
        if stripped!=normalized and '\n' not in normalized:
            base=_parse_v4(stripped)
            if base['original_chapters_main'] is None:base['original_chapters_main']=base['original_chapters_total']
            if base['original_chapters_main'] is not None:
                out.update(base);out['original_chapters_total']=base['original_chapters_main'];out['chapter_count_method']='main_only'
                out['chapter_notes'].append('Uncounted prologue/preface excluded; using known main chapters.')
    if out['publication_status']=='unknown' and candidate['publication_status']!='unknown':
        out['publication_status']=candidate['publication_status']
    out['chapter_status_raw']=raw
    return out


def parse_chapter_status(raw):
    """Additional exact single-line counts; status remains independently parsed."""
    out = _parse_v5(raw)
    if out['original_chapters_total'] is not None or not isinstance(raw, str):
        return out
    text = unicodedata.normalize('NFKC', raw).casefold().strip()
    # only recognized, nonnumeric status annotations may be removed here.
    annotation = (r'(?:' + STATUS_RE + r'|finished|discontinued|cancelled/banned|'
                  r'on hold/dropped|hiatus/abandoned|completed/discontinued|'
                  r'discontinued/indefinite hiatus|banned in china|'
                  r"discontinued due to author's passing|main story end|\?+)")
    text = re.sub(r'\(\s*' + annotation + r'\s*\)', '', text).strip()
    simple = re.fullmatch(r'(' + N + r')\s*(?:chapters?(?:/episodes)?)?', text)
    additive = re.fullmatch(r'(' + N + r')\s*(?:chapters?)?\s*\+\s*(' + N +
                            r')\s*(?:(extra[s]?|bonus|side stor(?:y|ies))\s*)?(?:chapters?)?', text)
    if simple:
        total = number(simple[1]); method = 'reported'
    elif additive:
        main, extra = number(additive[1]), number(additive[2])
        total = main + extra; method = 'calculated'
        if additive[3]:
            out['original_chapters_main'] = main
            out['original_chapters_extra'] = extra
    else:
        return out
    if not 0 < total <= 2147483647:
        return out
    out['original_chapters_total'] = total
    out['chapter_count_method'] = method
    out['chapter_notes'] = ['Exact count parsed independently of publication status; no status inferred.']
    return out
