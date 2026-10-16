"""
Fix hints, Persian translations and typos in a built deck without touching
anything Anki uses to recognise notes (GUIDs, note/notetype/deck IDs, media).

    python scripts/fix/fix_deck.py --edition old-books --out-dir dist/fixed \
        dist/old-books/4000EEW_Old_Book_*.apkg
    python scripts/fix/fix_deck.py --edition 2nd-edition --out-dir dist/fixed \
        --repair-media-from "$APPDATA/Anki2/User 1/collection.media" \
        "dist/shared-deck/4000 EEW (2nd Edition).apkg"

For every note it
  1. applies the manual corrections in data/corrections/<edition>.json,
  2. re-cuts the Hint from the unit's story (content_fixes.repair_hint),
  3. normalises the Persian fields (2nd Edition only),
and gives every changed note a new modification time, so Anki's default
"update notes if newer" import option picks the changes up. Media files are
verified on the way (CRC, and SHA-1 for newer packages); a damaged one is
replaced from --repair-media-from if an identical original is found there.

Afterwards, check the result before sharing it:
    python scripts/compat/check_compat.py check --baseline data/guid-baseline/<edition>.json dist/fixed/*.apkg

Run from the repo root.
"""

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_fixes import normalize_persian, repair_hint

FIELD_SEP = "\x1f"

EDITIONS = {
    "old-books": {
        "notetype": "4000 EEW (Old Books) Model",
        "data_dir": "data/old-books",
        "book_re": re.compile(r"Book (\d+)$"),
        "persian": [],
    },
    "2nd-edition": {
        "notetype": "4000 EEW",
        "data_dir": "data/2nd-edition",
        "book_re": re.compile(r"(\d+)\.Book$"),
        "persian": [("Meaning", "FaMeaning"), ("Example", "FaExample")],
    },
}

WORDLIST_ITEM_RE = re.compile(r'<li img="([^"]*)" pro="([^"]*)" word="([^"]*)">(.*?)</li>', re.DOTALL)


# ---------------------------------------------------------------------------
# Stories
# ---------------------------------------------------------------------------

def _story_2nd_edition(reading_html: str) -> str:
    """The story part of a 2nd Edition unit: from its <h3> title up to the next exercise section."""
    m = re.search(r"<h3>", reading_html)
    if not m:
        return ""
    end = re.search(r'<p class="section-rotate">', reading_html[m.end():])
    return reading_html[m.start(): m.end() + end.start() if end else len(reading_html)]


def load_stories(edition: str, data_dir: Path) -> dict:
    """old-books: {(book, unit_tag): story_html}; 2nd-edition: {(book, word): story_html}."""
    stories = {}
    for path in sorted(data_dir.glob("book*/data.json")):
        book = int(re.search(r"(\d+)$", path.parent.name).group(1))
        data = json.loads(path.read_text(encoding="utf-8"))
        for unit in data["flashcard"]:
            if edition == "old-books":
                if "wordlist" in unit:
                    stories[(book, unit["en"].replace(" ", ""))] = unit["reading"][0].get("story", "")
            else:
                reading = unit.get("reading", "")
                for _img, _pron, word, _inner in WORDLIST_ITEM_RE.findall(reading):
                    stories.setdefault((book, word.strip().lower()), _story_2nd_edition(reading))
    return stories


def story_for(edition, stories, book, word, tags):
    if edition == "old-books":
        unit = next((t for t in tags.split() if re.fullmatch(r"Unit\d+", t)), None)
        return stories.get((book, unit), "")
    return stories.get((book, word.strip().lower()), "")


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------

def load_corrections(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["notes"]


def apply_corrections(guid: str, fields: dict, corrections: dict) -> set:
    """Apply the manual corrections of one note in place; return the names of the corrected fields."""
    corr = corrections.get(guid)
    if not corr:
        return set()
    if corr.get("word") and corr["word"] != fields.get("Word", "").strip():
        raise ValueError(f"Correction for {guid} is for '{corr['word']}', but the note is '{fields.get('Word')}'.")
    done = set()
    for name, value in corr.items():
        if name == "word":
            continue
        if name not in fields:
            raise ValueError(f"Correction for '{corr.get('word')}' ({guid}) names unknown field '{name}'.")
        if isinstance(value, str):
            fields[name] = value
        else:
            for old, new in value:
                if new in fields[name] and (old not in fields[name] or old in new):
                    continue    # already fixed (by an earlier run or upstream)
                if old not in fields[name]:
                    raise ValueError(f"'{old}' not found in {name} of '{corr.get('word')}' ({guid}).")
                fields[name] = fields[name].replace(old, new)
        done.add(name)
    return done


def fix_note_fields(edition, fields, guid, story_html, corrections):
    """Return the fixed copy of a note's {field: value} dict."""
    fields = dict(fields)
    manual = apply_corrections(guid, fields, corrections)
    if "Hint" in fields and "Hint" not in manual:
        fields["Hint"] = repair_hint(fields["Hint"], story_html, fields["Word"], fallback=fields.get("Example", ""))
    for en, fa in EDITIONS[edition]["persian"]:
        fields[fa] = normalize_persian(fields[fa], fields[en])
    return fields


# ---------------------------------------------------------------------------
# .apkg handling
# ---------------------------------------------------------------------------

def _unicase(a, b):
    la, lb = a.lower(), b.lower()
    return (la > lb) - (la < lb)


def _collection_member(names):
    for name in ("collection.anki21b", "collection.anki21", "collection.anki2"):
        if name in names:
            return name
    raise FileNotFoundError("No collection file in this .apkg")


def _notetype(conn, name):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "notetypes" in tables:
        row = conn.execute("SELECT id FROM notetypes WHERE name=?", (name,)).fetchone()
        if not row:
            raise ValueError(f"Notetype '{name}' not found")
        fields = [r[0] for r in conn.execute("SELECT name FROM fields WHERE ntid=? ORDER BY ord", (row[0],))]
        decks = {did: n.replace(FIELD_SEP, "::") for did, n in conn.execute("SELECT id, name FROM decks")}
        return row[0], fields, decks
    models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    for mid, m in models.items():
        if m["name"] == name:
            fields = [f["name"] for f in sorted(m["flds"], key=lambda f: f["ord"])]
            decks = {int(k): d["name"] for k, d in json.loads(conn.execute("SELECT decks FROM col").fetchone()[0]).items()}
            return int(mid), fields, decks
    raise ValueError(f"Notetype '{name}' not found")


def _read_media_index(zin) -> list:
    """Entries of an anki21b package's 'media' file: [{"name", "size", "sha1"}], one per numbered zip member."""
    import zstandard
    buf = zstandard.ZstdDecompressor().stream_reader(zin.read("media")).read()

    def varint(b, i):
        result = shift = 0
        while True:
            c = b[i]
            i += 1
            result |= (c & 0x7F) << shift
            shift += 7
            if c < 0x80:
                return result, i

    def fields(b):
        i = 0
        while i < len(b):
            key, i = varint(b, i)
            if key & 7 == 0:
                value, i = varint(b, i)
            else:   # length-delimited (the only other wire type used here)
                n, i = varint(b, i)
                value, i = b[i:i + n], i + n
            yield key >> 3, value

    entries = []
    for num, entry in fields(buf):
        if num == 1:
            e = dict(fields(entry))
            entries.append({"name": e.get(1, b"").decode(), "size": e.get(2), "sha1": e.get(3, b"").hex()})
    return entries


def _checked_media(zin, info, entry, repair_dir):
    """
    Bytes to write for one zstd-compressed media member, verified against the
    SHA-1 recorded in the package. A damaged file is replaced by an identical
    copy (same SHA-1) from repair_dir, e.g. Anki's collection.media folder.
    """
    import hashlib
    import zstandard
    with zin.open(info) as f:
        f._expected_crc = None      # verified by SHA-1 below instead
        raw = f.read()
    try:
        if hashlib.sha1(zstandard.ZstdDecompressor().stream_reader(raw).read()).hexdigest() == entry["sha1"]:
            return raw
    except zstandard.ZstdError:
        pass
    candidate = Path(repair_dir) / entry["name"] if repair_dir else None
    if candidate and candidate.exists():
        data = candidate.read_bytes()
        if hashlib.sha1(data).hexdigest() == entry["sha1"]:
            print(f"  repaired damaged media file {entry['name']} from {candidate}")
            return zstandard.ZstdCompressor().compress(data)
    raise ValueError(f"Media file {entry['name']} (member {info.filename}) is damaged. "
                     "Pass --repair-media-from with a folder holding the original (e.g. Anki's collection.media).")


def fix_apkg(edition, src: Path, dst: Path, stories, corrections, report, repair_dir=None):
    cfg = EDITIONS[edition]
    with zipfile.ZipFile(src) as zin, tempfile.TemporaryDirectory() as tmp:
        member = _collection_member(zin.namelist())
        raw = zin.read(member)
        if member.endswith("21b"):
            import zstandard
            raw = zstandard.ZstdDecompressor().stream_reader(raw).read()
        db = Path(tmp) / "collection.db"
        db.write_bytes(raw)

        conn = sqlite3.connect(db)
        conn.create_collation("unicase", _unicase)
        mid, names, decks = _notetype(conn, cfg["notetype"])
        note_deck = {}
        for nid, did in conn.execute("SELECT nid, did FROM cards ORDER BY ord DESC"):
            note_deck[nid] = decks.get(did, "")

        now, changed = int(time.time()), 0
        for nid, guid, flds, tags in conn.execute("SELECT id, guid, flds, tags FROM notes WHERE mid=?", (mid,)).fetchall():
            old = dict(zip(names, flds.split(FIELD_SEP)))
            m = cfg["book_re"].search(note_deck.get(nid, ""))
            book = int(m.group(1)) if m else None
            new = fix_note_fields(edition, old, guid, story_for(edition, stories, book, old["Word"], tags), corrections)
            if new == old:
                continue
            for name in names:
                if new[name] != old[name]:
                    report.append((src.name, guid, old["Word"], name, old[name], new[name]))
            conn.execute("UPDATE notes SET flds=?, mod=?, usn=-1 WHERE id=?",
                         (FIELD_SEP.join(new[n] for n in names), now, nid))
            changed += 1
        conn.commit()
        conn.close()

        data = db.read_bytes()
        if member.endswith("21b"):
            import zstandard
            data = zstandard.ZstdCompressor().compress(data)

        media_index = _read_media_index(zin) if member.endswith("21b") else None
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                if info.filename == member:
                    payload = data
                elif media_index is not None and info.filename.isdigit():
                    payload = _checked_media(zin, info, media_index[int(info.filename)], repair_dir)
                else:
                    payload = zin.read(info.filename)   # raises on a bad CRC
                zout.writestr(info, payload, compress_type=info.compress_type)
    print(f"{src.name}: {changed} note(s) changed -> {dst}")


def write_report(report, path: Path):
    """Markdown table of every changed field, for reviewing the fixes."""
    def cell(s):
        return s.replace("|", "\\|").replace("\n", " ")
    lines = ["| Deck | Word | Field | Before | After |", "|---|---|---|---|---|"]
    for deck, _guid, word, field, old, new in report:
        lines.append(f"| {cell(deck)} | {cell(word)} | {field} | {cell(old)} | {cell(new)} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {path} ({len(report)} changed fields)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--edition", required=True, choices=EDITIONS)
    parser.add_argument("--out-dir", required=True, help="Folder for the fixed .apkg files")
    parser.add_argument("--corrections", help="Default: data/corrections/<edition>.json")
    parser.add_argument("--report", help="Write a Markdown table of all changes")
    parser.add_argument("--repair-media-from", help="Folder with original media (e.g. Anki's collection.media) "
                                                    "used to replace damaged media files")
    parser.add_argument("apkg", nargs="+")
    args = parser.parse_args()

    stories = load_stories(args.edition, Path(EDITIONS[args.edition]["data_dir"]))
    corrections = load_corrections(Path(args.corrections or f"data/corrections/{args.edition}.json"))
    report = []
    for src in args.apkg:
        src = Path(src)
        dst = Path(args.out_dir) / src.name
        if dst.resolve() == src.resolve():
            sys.exit("--out-dir must not be the folder of the input decks.")
        fix_apkg(args.edition, src, dst, stories, corrections, report, args.repair_media_from)

    used = {guid for _deck, guid, *_ in report}
    unused = [c.get("word", g) for g, c in corrections.items() if g not in used]
    if unused:
        print(f"Note: corrections with no effect (already applied or note not in these decks): {unused}")
    if args.report:
        write_report(report, Path(args.report))


if __name__ == "__main__":
    main()
