"""
Text clean-up rules shared by fix_deck.py and anki_generator.py.

Hints
-----
The original hints were picked by spaCy from text produced by
BeautifulSoup.get_text(" "), which put spaces around every <strong> tag
("alcohol , especially") and split dialogue in the middle of quotations
("she pleaded. \"", "It will be a fun adventure!\""). repair_hint() finds
the old hint again in the story and re-cuts the sentence around it with a
quote-aware sentence splitter, so the result is a complete sentence with
balanced quotes and normal spacing. If the old hint cannot be located, it is
only tidied up (spacing and quotes), never dropped.

Persian
-------
normalize_persian() replaces Arabic Yeh/Kaf with the Persian letters, fixes
stray non-Persian punctuation and adds the final full stop/question mark when
the English source has one.
"""

import html
import re

NOT_FOUND = "Context not found."

# Tags that only style text inside a sentence; every other tag ends a paragraph.
INLINE_TAGS = r"(?:strong|b|i|em|u|span|a|font|sup|sub)"
INLINE_TAG_RE = re.compile(rf"</?{INLINE_TAGS}\b[^>]*>", re.I)
ANY_TAG_RE = re.compile(r"<[^>]+>")

ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "mt", "vs", "etc", "no", "a.m", "p.m", "u.s"}

# Past forms the prefix rule in word_in_text() cannot see.
IRREGULAR_FORMS = {
    "shake": ["shook", "shaken"], "lay": ["laid"], "hang": ["hung"], "tear": ["tore", "torn"],
    "hide": ["hid", "hidden"], "lie": ["lay", "lain", "lying"], "bite": ["bit", "bitten"],
    "seek": ["sought"], "bind": ["bound"], "creep": ["crept"], "dig": ["dug"], "feed": ["fed"],
    "flee": ["fled"], "freeze": ["froze", "frozen"], "grind": ["ground"], "lead": ["led"],
    "lend": ["lent"], "ride": ["rode", "ridden"], "rise": ["rose", "risen"], "seize": ["seized"],
    "shoot": ["shot"], "sink": ["sank", "sunk"], "slide": ["slid"], "spin": ["spun"],
    "steal": ["stole", "stolen"], "sting": ["stung"], "strike": ["struck"], "swear": ["swore", "sworn"],
    "sweep": ["swept"], "swing": ["swung"], "weep": ["wept"], "wind": ["wound"], "bear": ["bore", "born", "borne"],
    "fight": ["fought"], "catch": ["caught"], "teach": ["taught"], "think": ["thought"], "buy": ["bought"],
    "bring": ["brought"], "fly": ["flew", "flown"], "draw": ["drew", "drawn"], "grow": ["grew", "grown"],
    "throw": ["threw", "thrown"], "blow": ["blew", "blown"], "wear": ["wore", "worn"], "fall": ["fell", "fallen"],
    "feel": ["felt"], "keep": ["kept"], "leave": ["left"], "lose": ["lost"], "mean": ["meant"],
    "meet": ["met"], "sell": ["sold"], "tell": ["told"], "sleep": ["slept"], "spend": ["spent"],
    "stand": ["stood"], "understand": ["understood"], "win": ["won"], "forget": ["forgot", "forgotten"],
    "forgive": ["forgave", "forgiven"], "choose": ["chose", "chosen"], "break": ["broke", "broken"],
    "speak": ["spoke", "spoken"], "wake": ["woke", "woken"], "drive": ["drove", "driven"],
    "write": ["wrote", "written"], "begin": ["began", "begun"], "drink": ["drank", "drunk"],
    "ring": ["rang", "rung"], "sing": ["sang", "sung"], "swim": ["swam", "swum"], "run": ["ran"],
    "become": ["became"], "come": ["came"], "eat": ["ate", "eaten"], "give": ["gave", "given"],
    "go": ["went", "gone"], "know": ["knew", "known"], "see": ["saw", "seen"], "take": ["took", "taken"],
    "find": ["found"], "hold": ["held"], "build": ["built"], "send": ["sent"], "pay": ["paid"],
    "say": ["said"], "make": ["made"], "hear": ["heard"], "sit": ["sat"], "get": ["got", "gotten"],
    "dive": ["dove"], "arise": ["arose", "arisen"], "awake": ["awoke"], "stick": ["stuck"],
    "strive": ["strove", "striven"], "tread": ["trod", "trodden"], "undergo": ["underwent", "undergone"],
    "withdraw": ["withdrew", "withdrawn"], "overcome": ["overcame"], "mislead": ["misled"],
    "foresee": ["foresaw", "foreseen"], "forbid": ["forbade", "forbidden"], "overtake": ["overtook"],
    "uphold": ["upheld"], "withstand": ["withstood"], "mistake": ["mistook", "mistaken"],
}


# ---------------------------------------------------------------------------
# Generic text helpers
# ---------------------------------------------------------------------------

def normalize_quotes(text: str) -> str:
    return (text.replace("“", '"').replace("”", '"').replace("„", '"')
                .replace("‘", "'").replace("’", "'").replace(" ", " "))


def tidy_spacing(text: str) -> str:
    """Collapse whitespace and remove spaces before punctuation (not before opening quotes)."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def fix_quote_spacing(text: str) -> str:
    """With balanced quotes, glue each quote to the text it encloses: `" Hi ,"` -> `"Hi,"`."""
    if text.count('"') % 2:
        return text
    out, opening = [], True
    for part in re.split(r'(")', text):
        if part == '"':
            if opening:
                out.append('"')
            else:
                if out:
                    out[-1] = out[-1].rstrip()
                out.append('"')
            opening = not opening
        else:
            if out and out[-1] == '"' and not opening:
                part = part.lstrip()
            out.append(part)
    return "".join(out)


def story_paragraphs(story_html: str) -> list:
    """Plain-text paragraphs of a story; inline tags vanish without adding spaces."""
    text = INLINE_TAG_RE.sub("", story_html)
    text = ANY_TAG_RE.sub("\n", text)
    text = normalize_quotes(html.unescape(text))
    return [p for p in (tidy_spacing(line) for line in text.split("\n")) if p]


# ---------------------------------------------------------------------------
# Quote-aware sentence splitting
# ---------------------------------------------------------------------------

# End of a sentence: ". Next", '." Next', '. "Next' -- and '!""Next' where the source lost the space.
_BOUNDARY_RE = re.compile(r'[.!?]+["\')]*(?=\s+(?:["\'(]\s?)?[A-Z0-9])|[.!?]+"(?="[A-Z])')


SPEECH_VERBS = {
    "said", "asked", "cried", "shouted", "claimed", "pleaded", "replied", "answered", "whispered",
    "yelled", "screamed", "exclaimed", "added", "explained", "insisted", "suggested", "warned",
    "laughed", "called", "continued", "begged", "demanded", "muttered", "told", "thought",
    "wondered", "sighed", "responded", "announced", "declared", "agreed", "admitted", "complained",
    "remarked", "shrieked", "groaned", "boasted", "bragged", "promised", "joked", "gasped", "says",
}


def split_sentences(paragraph: str) -> list:
    """Return [(start, end)] spans of the sentences of a paragraph."""
    spans, start = [], 0
    for m in _BOUNDARY_RE.finditer(paragraph):
        if paragraph[m.start()] == ".":
            tokens = paragraph[start:m.start()].split()
            token = tokens[-1].lstrip("\"'(") if tokens else ""
            if token.lower().rstrip(".") in ABBREVIATIONS or (len(token) == 1 and token.isupper()):
                continue
        spans.append((start, m.end()))
        start = m.end()
        while start < len(paragraph) and paragraph[start] == " ":
            start += 1
    if start < len(paragraph):
        spans.append((start, len(paragraph)))

    # Re-attach a dialogue tag to the quotation in front of it:
    # ["Help me!"] [Pelias claimed.]  ->  ["Help me!" Pelias claimed.]
    merged, was_merged = [], False
    for s, e in spans:
        piece = paragraph[s:e]
        words = re.findall(r"[a-z]+", piece.lower())
        if (merged and not was_merged and paragraph[merged[-1][1] - 1] == '"' and '"' not in piece
                and len(words) <= 6 and SPEECH_VERBS.intersection(words) and e - merged[-1][0] <= 300):
            merged[-1] = (merged[-1][0], e)
            was_merged = True
        else:
            merged.append((s, e))
            was_merged = False
    return merged


def balance_quotes(paragraph: str, start: int, end: int) -> str:
    """Sentence text with quotes opened/closed where the sentence starts or ends inside a quotation."""
    text = paragraph[start:end].strip()
    if paragraph[:start].count('"') % 2 == 1 and not text.startswith('"'):
        text = '"' + text
    if text.count('"') % 2:
        # Reading from an "outside" state, an odd count leaves the last quotation open.
        # Close it before a trailing dialogue tag (the source lost that quote):
        # '"No respect at all, they said.'  ->  '"No respect at all," they said.'
        tag = re.match(rf'^(.*\S),(\s+(?:[A-Za-z]+\s+){{0,3}}(?:{"|".join(SPEECH_VERBS)})[.!?])$', text)
        if tag:
            text = tag.group(1) + ',"' + tag.group(2)
        else:
            text += '"'
    return text


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------

def _skeleton(text: str):
    """Lower-case letters/digits only, plus a map from skeleton index to text index."""
    chars, index = [], []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            index.append(i)
    return "".join(chars), index


def word_forms(word: str) -> list:
    w = word.lower().strip()
    forms = [w] + IRREGULAR_FORMS.get(w, [])
    if len(w) > 1 and w.endswith("y") and w[-2] not in "aeiou":
        forms.append(w[:-1] + "i")
    if w.endswith("e"):
        forms.append(w[:-1])
    return forms


def word_in_text(word: str, text: str) -> bool:
    """True if a token of text is the word, a regular inflection of it, or a known irregular form."""
    forms = word_forms(word)
    if " " in word.strip():
        return word.lower().strip() in text.lower()
    for tok in re.findall(r"[A-Za-z]+", text.lower()):
        for f in forms:
            if tok == f or (tok.startswith(f) and len(tok) - len(f) <= 4 and len(f) >= 3):
                return True
    return False


def _locate(paragraphs, hint):
    """Find the hint in the story: (paragraph, start, end) or None."""
    words = re.findall(r"[A-Za-z0-9']+", hint)
    skeletons = [(p, *_skeleton(p)) for p in paragraphs]
    # Try the whole hint, then drop more and more words from the front (merged
    # titles) and/or the back (text that ran into the next paragraph).
    for dropped in range(0, max(1, len(words) - 2)):
        for drop_front in range(0, dropped + 1):
            part = words[drop_front:len(words) - (dropped - drop_front)]
            if len(part) < 3 and len(words) >= 3:
                continue
            target, _ = _skeleton(" ".join(part))
            if not target:
                continue
            for p, skel, index in skeletons:
                pos = skel.find(target)
                if pos >= 0:
                    return p, index[pos], index[pos + len(target) - 1] + 1
    return None


def html_to_text(fragment: str) -> str:
    text = INLINE_TAG_RE.sub("", fragment)
    text = ANY_TAG_RE.sub(" ", text)
    return tidy_spacing(normalize_quotes(html.unescape(text)))


def tidy_hint(hint: str) -> str:
    """Fix spacing and dangling quotes of a hint without looking at the story."""
    h = html_to_text(hint)
    h = re.sub(r'\s+"$', "", h)          # opening quote of the next sentence
    h = re.sub(r'^"\s+(?=[A-Z])', '"', h)
    if h.count('"') % 2:
        h = h + '"' if h.startswith('"') else '"' + h
    h = fix_quote_spacing(h)
    if h and h[0].islower():
        h = h[0].upper() + h[1:]
    return h


def _cut_hint(p, sentences, i):
    """Hint text for sentence i of paragraph p."""
    start, end = sentences[i]
    # A very short sentence ("She was amazed.") gives little context: add the one before it.
    if len(p[start:end].split()) < 5:
        if i > 0 and end - sentences[i - 1][0] <= 250:
            start = sentences[i - 1][0]
        elif i + 1 < len(sentences) and sentences[i + 1][1] - start <= 250:
            end = sentences[i + 1][1]
    return fix_quote_spacing(balance_quotes(p, start, end))


def find_hint(paragraphs, word):
    """First story sentence that uses the word (for notes without a hint)."""
    for p in paragraphs:
        sentences = split_sentences(p)
        for i, (s, e) in enumerate(sentences):
            if word_in_text(word, p[s:e]):
                return _cut_hint(p, sentences, i)
    return None


def repair_hint(hint: str, story_html: str, word: str, fallback: str = "") -> str:
    """
    Return a cleaned hint (see module docstring). Falls back to tidy_hint().
    fallback (e.g. the note's own example) is used when the story never uses the word.
    """
    paragraphs = story_paragraphs(story_html) if story_html else []
    if not hint.strip() or hint.strip() == NOT_FOUND:
        return find_hint(paragraphs, word) or (html_to_text(fallback) if fallback else hint)

    found = _locate(paragraphs, html_to_text(hint))
    if not found:
        return tidy_hint(hint)
    p, m_start, m_end = found
    sentences = split_sentences(p)
    hits = [i for i, (s, e) in enumerate(sentences) if s < m_end and e > m_start]
    if not hits:
        return tidy_hint(hint)
    i = next((i for i in hits if word_in_text(word, p[slice(*sentences[i])])), hits[0])
    new = _cut_hint(p, sentences, i)
    if not word_in_text(word, new) and word_in_text(word, html_to_text(hint)):
        return tidy_hint(hint)
    return new


# ---------------------------------------------------------------------------
# Persian
# ---------------------------------------------------------------------------

def normalize_persian(fa: str, en: str = "") -> str:
    """Normalise a Persian translation; en is the English source (for end punctuation)."""
    if not fa.strip():
        return fa
    out = fa.replace("ي", "ی").replace("ك", "ک")   # ي -> ی, ك -> ک
    out = out.replace("।", ".")                                      # Devanagari danda
    out = re.sub(r"[ \t]+", " ", out).strip()
    out = re.sub(r"\s+([.,!?؟،؛:])", r"\1", out)
    out = re.sub(r"(?<=[؀-ۿ])\?", "؟", out)
    en_plain = ANY_TAG_RE.sub("", en).strip()
    body = ANY_TAG_RE.sub("", out).strip()
    if en_plain and body and not re.search(r"[.!?؟»\"')]$", body):
        if en_plain.endswith("?"):
            out += "؟"
        elif en_plain.endswith("!"):
            out += "!"
        elif en_plain.endswith("."):
            out += "."
    return out
