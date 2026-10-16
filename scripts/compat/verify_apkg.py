"""
Check that .apkg packages are intact before they are published:
every zip member passes its CRC-32 check, and in newer (anki21b) packages
every media file matches the SHA-1 recorded in the package's media index.

    python scripts/compat/verify_apkg.py dist/fixed/*.apkg

Exits with status 1 if any package is damaged. Run from the repo root.
"""

import hashlib
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fix"))
from fix_deck import _read_media_index


def verify(path: Path) -> list:
    problems = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            try:
                with z.open(info) as f:
                    while f.read(1 << 20):
                        pass
            except zipfile.BadZipFile as e:
                problems.append(f"{info.filename}: {e}")
        if "collection.anki21b" in z.namelist():
            import zstandard
            for i, entry in enumerate(_read_media_index(z)):
                data = zstandard.ZstdDecompressor().stream_reader(z.read(str(i))).read()
                if hashlib.sha1(data).hexdigest() != entry["sha1"]:
                    problems.append(f"media {entry['name']}: SHA-1 mismatch")
    return problems


def main():
    failed = False
    for arg in sys.argv[1:]:
        problems = verify(Path(arg))
        print(f"{'OK  ' if not problems else 'BAD '} {arg}")
        for p in problems:
            print(f"     {p}")
        failed |= bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
