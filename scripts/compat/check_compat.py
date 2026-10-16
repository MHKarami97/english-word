"""
Protect the review history of people who already use our shared decks.

Anki matches an imported note to an existing one by its GUID. As long as a
new build keeps the same GUIDs, the same notetype IDs and the same field and
template lists, re-importing it only updates the note contents -- users keep
their cards, intervals and review history. If a GUID changes, Anki treats the
note as brand new: the user gets a duplicate card with no history.

This script records what was published (a "baseline") and checks every new
build against it before it is uploaded to AnkiWeb.

    # 1. Record the decks exactly as they were published (done once per upload)
    python scripts/compat/check_compat.py snapshot \
        --out data/guid-baseline/old-books.json dist/old-books/*.apkg

    # 2. Before re-sharing a new build, check it against the baseline
    python scripts/compat/check_compat.py check \
        --baseline data/guid-baseline/old-books.json dist/old-books/*.apkg

`check` exits with status 1 if the build would hurt existing users.

Run from the repo root.
"""

import argparse
import datetime
import hashlib
import html
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

FIELD_SEP = "\x1f"


def normalize_key(text: str) -> str:
    """Plain-text form of a note's first field, used to recognise the same word across builds."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def load_guid_map(baseline_path) -> dict:
    """Return {(deck, key): guid} for every note in a baseline file."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    return {(n["deck"], n["key"]): n["guid"] for n in baseline["notes"]}


# ---------------------------------------------------------------------------
# Reading .apkg files
# ---------------------------------------------------------------------------

def _open_collection(apkg: Path, tmp_dir: str) -> sqlite3.Connection:
    with zipfile.ZipFile(apkg) as z:
        names = z.namelist()
        if "collection.anki21b" in names:
            try:
                import zstandard
            except ImportError:
                sys.exit("The 'zstandard' package is required for this deck: pip install zstandard")
            with z.open("collection.anki21b") as f:
                data = zstandard.ZstdDecompressor().stream_reader(f).read()
        elif "collection.anki21" in names:
            data = z.read("collection.anki21")
        else:
            data = z.read("collection.anki2")
    db_path = Path(tmp_dir) / (hashlib.sha1(str(apkg).encode()).hexdigest() + ".db")
    db_path.write_bytes(data)
    return sqlite3.connect(db_path)


def _tables(conn) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _read_notetypes(conn) -> dict:
    if "notetypes" in _tables(conn):
        result = {}
        for ntid, name in conn.execute("SELECT id, name FROM notetypes"):
            fields = [r[0] for r in conn.execute("SELECT name FROM fields WHERE ntid=? ORDER BY ord", (ntid,))]
            templates = [r[0] for r in conn.execute("SELECT name FROM templates WHERE ntid=? ORDER BY ord", (ntid,))]
            result[str(ntid)] = {"name": name, "fields": fields, "templates": templates}
        return result
    models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    return {
        str(mid): {
            "name": m["name"],
            "fields": [f["name"] for f in sorted(m["flds"], key=lambda f: f["ord"])],
            "templates": [t["name"] for t in sorted(m["tmpls"], key=lambda t: t["ord"])],
        }
        for mid, m in models.items()
    }


def _read_decks(conn) -> dict:
    if "decks" in _tables(conn):
        return {did: name.replace(FIELD_SEP, "::") for did, name in conn.execute("SELECT id, name FROM decks")}
    decks = json.loads(conn.execute("SELECT decks FROM col").fetchone()[0])
    return {int(did): d["name"] for did, d in decks.items()}


def read_apkg(apkg: Path, tmp_dir: str):
    """Return (notetypes, notes) for one .apkg; notes are dicts like the baseline entries."""
    conn = _open_collection(apkg, tmp_dir)
    try:
        notetypes = _read_notetypes(conn)
        decks = _read_decks(conn)
        # A note's deck is the deck of its first card.
        note_deck = {}
        for nid, did in conn.execute("SELECT nid, did FROM cards ORDER BY ord DESC"):
            note_deck[nid] = decks.get(did, str(did))
        notes = []
        for nid, guid, mid, mod, flds in conn.execute("SELECT id, guid, mid, mod, flds FROM notes"):
            notes.append({
                "guid": guid,
                "notetype": str(mid),
                "deck": note_deck.get(nid, ""),
                "key": normalize_key(flds.split(FIELD_SEP)[0]),
                "mod": mod,
                "fields_sha1": hashlib.sha1(flds.encode("utf-8")).hexdigest(),
            })
        return notetypes, notes
    finally:
        conn.close()


def read_build(apkgs):
    notetypes, notes = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        for apkg in apkgs:
            nts, ns = read_apkg(Path(apkg), tmp)
            notetypes.update(nts)
            notes.extend(ns)
    return notetypes, notes


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def cmd_snapshot(args):
    notetypes, notes = read_build(args.apkg)
    used = sorted({n["notetype"] for n in notes})
    seen_guids = set()
    for n in notes:
        if n["guid"] in seen_guids:
            sys.exit(f"Duplicate GUID {n['guid']} in the input decks; refusing to write a baseline.")
        seen_guids.add(n["guid"])
    baseline = {
        "description": args.description or "",
        "created": datetime.date.today().isoformat(),
        "sources": [Path(p).as_posix() for p in args.apkg],
        "notetypes": {mid: notetypes[mid] for mid in used},
        "notes": sorted(notes, key=lambda n: (n["deck"], n["key"], n["guid"])),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {out}: {len(notes)} notes, {len(used)} notetype(s), "
          f"{len({n['deck'] for n in notes})} deck(s).")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def cmd_check(args):
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    notetypes, notes = read_build(args.apkg)
    errors, warnings = [], []

    # Notetypes: same IDs, same fields, templates only appended.
    for mid, old in baseline["notetypes"].items():
        new = notetypes.get(mid)
        if new is None:
            errors.append(f"Notetype '{old['name']}' ({mid}) is missing. Keep its ID unchanged.")
            continue
        if new["fields"] != old["fields"]:
            errors.append(
                f"Fields of notetype '{old['name']}' ({mid}) changed:\n"
                f"      published: {old['fields']}\n"
                f"      new build: {new['fields']}\n"
                "    Users would have to tick 'Merge notetypes' when importing, or their notes are not updated."
            )
        if new["templates"][:len(old["templates"])] != old["templates"]:
            errors.append(
                f"Card templates of notetype '{old['name']}' ({mid}) were removed or reordered:\n"
                f"      published: {old['templates']}\n"
                f"      new build: {new['templates']}\n"
                "    This deletes or swaps existing cards together with their review history."
            )
        elif len(new["templates"]) > len(old["templates"]):
            warnings.append(
                f"Notetype '{old['name']}' gains template(s) {new['templates'][len(old['templates']):]}: "
                "every existing note gets new cards for users who update."
            )
        if new["name"] != old["name"]:
            warnings.append(f"Notetype {mid} was renamed '{old['name']}' -> '{new['name']}'.")

    # Notes.
    new_by_guid = {}
    for n in notes:
        if n["guid"] in new_by_guid:
            errors.append(f"GUID {n['guid']} appears twice in the new build.")
        new_by_guid[n["guid"]] = n

    old_notes = baseline["notes"]
    if args.only_decks_present:
        build_decks = {n["deck"] for n in notes}
        skipped = sorted({n["deck"] for n in old_notes} - build_decks)
        if skipped:
            print(f"Skipping baseline decks not in this build: {skipped}")
        old_notes = [n for n in old_notes if n["deck"] in build_decks]

    old_guids = {n["guid"] for n in baseline["notes"]}

    missing, changed, unchanged, not_newer, moved = [], [], 0, [], set()
    for old in old_notes:
        new = new_by_guid.get(old["guid"])
        if new is None:
            missing.append(old)
            continue
        if new["notetype"] != old["notetype"]:
            errors.append(f"Note '{old['key']}' ({old['guid']}) moved from notetype {old['notetype']} to {new['notetype']}.")
        if new["key"] != old["key"]:
            warnings.append(f"Note {old['guid']}: first field changed '{old['key']}' -> '{new['key']}'.")
        if new["deck"] != old["deck"]:
            moved.add((old["deck"], new["deck"]))
        if new["fields_sha1"] == old["fields_sha1"]:
            unchanged += 1
        else:
            changed.append(new)
            if new["mod"] <= old["mod"]:
                not_newer.append(new)

    for old_deck, new_deck in sorted(moved):
        # Harmless for existing users: Anki matches notes by GUID and leaves their cards where they are.
        warnings.append(f"Deck renamed '{old_deck}' -> '{new_deck}' (existing users' cards stay in their current deck).")

    if missing:
        # Is the same word present under a different GUID? Then users would get duplicates.
        missing_by_key = {(o["notetype"], o["key"]): o for o in missing}
        regenerated = [n for n in notes if n["guid"] not in old_guids
                       and (n["notetype"], n["key"]) in missing_by_key]
        sample = ", ".join(f"'{o['key']}'" for o in missing[:10])
        errors.append(
            f"{len(missing)} published note(s) are missing from the new build (e.g. {sample}).\n"
            f"    {len(regenerated)} of them reappear with a NEW GUID -- users would get duplicate cards\n"
            "    without their review history. Reuse the GUIDs from the baseline."
            + ("" if args.only_decks_present else
               "\n    (Checking only some of the published decks? Pass --only-decks-present.)")
        )

    added = [n for n in notes if n["guid"] not in old_guids]
    if not_newer:
        warnings.append(
            f"{len(not_newer)} changed note(s) are not newer than the published version, so Anki's default "
            "'Update notes: if newer' import option will skip them."
        )

    print(f"Baseline: {args.baseline} ({len(baseline['notes'])} notes)")
    print(f"New build: {len(notes)} notes -> unchanged {unchanged}, updated {len(changed)}, "
          f"new {len(added)}, missing {len(missing)}")
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print("\nNOT SAFE to share: importing this build would hurt existing users' progress.")
        return 1
    print("\nOK: existing users can import this build without losing their review history.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("snapshot", help="Record the notes/GUIDs of published decks")
    p.add_argument("--out", required=True, help="Baseline JSON to write")
    p.add_argument("--description", help="Free text stored in the baseline (e.g. AnkiWeb links)")
    p.add_argument("apkg", nargs="+")

    p = sub.add_parser("check", help="Check a new build against a baseline")
    p.add_argument("--baseline", required=True)
    p.add_argument("--only-decks-present", action="store_true",
                   help="Only check baseline decks that appear in the given files")
    p.add_argument("apkg", nargs="+")

    args = parser.parse_args()
    if args.command == "snapshot":
        cmd_snapshot(args)
        return 0
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
