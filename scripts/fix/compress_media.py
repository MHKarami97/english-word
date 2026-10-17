"""
Shrink the media inside built decks without touching anything Anki uses to
recognise notes (GUIDs, note/notetype/deck IDs, fields).

    python scripts/fix/compress_media.py --audio-kbps 48 --out-dir out/final out/fixed/4000.EEW.2nd.Edition.apkg
    python scripts/fix/compress_media.py --audio-kbps 32 --webp 85 --out-dir out/final out/fixed/4000EEW_Old_Book_*.apkg

- MP3 audio is re-encoded to mono at the given bitrate (same sample rate);
  files that are already mono at or below that bitrate are left alone, so a
  second run never re-encodes (and degrades) them again.
- With --webp, JPEG/PNG images become WebP files (name.jpg -> name.webp) and
  the notes' <img src="..."> references are updated.
- A file is only replaced when the result is at least 10% smaller.
- Every note that uses a changed file gets a new modification time, so
  Anki's "update notes if newer" import switches it to the new files.

--samples-dir writes a few before/after pairs for listening/viewing.
Needs ffmpeg (audio) and Pillow (images). Run from the repo root.
"""

import argparse
import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FIELD_SEP = "\x1f"
MIN_SAVING = 0.10

_BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],   # MPEG-1 layer III
             2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}       # MPEG-2/2.5 layer III


# ---------------------------------------------------------------------------
# Small protobuf helpers for the anki21b "media" index
# (MediaEntries { repeated MediaEntry entries = 1 }, MediaEntry { name = 1; size = 2; sha1 = 3; ... })
# ---------------------------------------------------------------------------

def _varint(b, i):
    result = shift = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, i


def _fields(b):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        if key & 7 == 0:
            value, i = _varint(b, i)
        else:
            n, i = _varint(b, i)
            value, i = b[i:i + n], i + n
        yield key >> 3, key & 7, value


def _enc_varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _enc_field(num, wire, value):
    if wire == 0:
        return _enc_varint(num << 3) + _enc_varint(value)
    return _enc_varint((num << 3) | 2) + _enc_varint(len(value)) + value


def read_media_index(raw: bytes) -> list:
    """List of entries, each a list of (field, wire, value) kept in order."""
    return [list(_fields(entry)) for num, _w, entry in _fields(raw) if num == 1]


def write_media_index(entries) -> bytes:
    out = b""
    for entry in entries:
        body = b"".join(_enc_field(n, w, v) for n, w, v in entry)
        out += _enc_field(1, 2, body)
    return out


def _set(entry, num, wire, value):
    for k, (n, w, _v) in enumerate(entry):
        if n == num:
            entry[k] = (n, w, value)
            return
    entry.append((num, wire, value))


# ---------------------------------------------------------------------------
# Media conversion
# ---------------------------------------------------------------------------

def mp3_params(data: bytes):
    """(bitrate_kbps, sample_rate, channels) of the first MP3 frame, or None."""
    i = 0
    if data[:3] == b"ID3" and len(data) > 10:
        i = 10 + ((data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9])
    while i < len(data) - 4:
        if data[i] == 0xFF and data[i + 1] & 0xE0 == 0xE0:
            ver = (data[i + 1] >> 3) & 3
            bitrate = _BITRATES[1 if ver == 3 else 2][(data[i + 2] >> 4) & 15]
            sr_index = (data[i + 2] >> 2) & 3
            rates = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}.get(ver)
            if rates and sr_index < 3 and bitrate:
                channels = 1 if (data[i + 3] >> 6) == 3 else 2
                return bitrate, rates[sr_index], channels
        i += 1
    return None


def compress_mp3(data: bytes, kbps: int):
    params = mp3_params(data)
    if not params:
        return None
    bitrate, sample_rate, channels = params
    if channels == 1 and bitrate <= kbps:
        return None                       # already compressed: never re-encode
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.mp3", Path(tmp) / "out.mp3"
        src.write_bytes(data)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map_metadata", "-1",
                        "-ac", "1", "-ar", str(sample_rate), "-codec:a", "libmp3lame", "-b:a", f"{kbps}k",
                        str(dst)], check=True)
        out = dst.read_bytes()
    return out if len(out) <= len(data) * (1 - MIN_SAVING) else None


def compress_image(data: bytes, quality: int):
    from PIL import Image
    image = Image.open(io.BytesIO(data))
    if image.format == "WEBP":
        return None
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "transparency" in image.info or image.mode in ("LA", "P") else "RGB")
    buf = io.BytesIO()
    image.save(buf, "WEBP", quality=quality, method=6)
    out = buf.getvalue()
    return out if len(out) <= len(data) * (1 - MIN_SAVING) else None


# ---------------------------------------------------------------------------
# .apkg handling
# ---------------------------------------------------------------------------

def _collection_member(names):
    for name in ("collection.anki21b", "collection.anki21", "collection.anki2"):
        if name in names:
            return name
    raise FileNotFoundError("No collection file in this .apkg")


def compress_apkg(src: Path, dst: Path, kbps, webp_quality, samples_dir, samples, workers):
    import zstandard
    with zipfile.ZipFile(src) as zin, tempfile.TemporaryDirectory() as tmp:
        names = zin.namelist()
        new_format = "collection.anki21b" in names
        if new_format:
            index = read_media_index(zstandard.ZstdDecompressor().stream_reader(zin.read("media")).read())
            media = {str(i): dict((n, v) for n, _w, v in e)[1].decode() for i, e in enumerate(index)}
            read = lambda m: zstandard.ZstdDecompressor().stream_reader(zin.read(m)).read()
        else:
            media = json.loads(zin.read("media")) if "media" in names else {}
            read = zin.read

        def convert(item):
            member, name = item
            ext = name.rsplit(".", 1)[-1].lower()
            data = read(member)
            if kbps and ext == "mp3":
                out = compress_mp3(data, kbps)
                return member, name, data, out, name
            if webp_quality and ext in ("jpg", "jpeg", "png"):
                out = compress_image(data, webp_quality)
                return member, name, data, out, name.rsplit(".", 1)[0] + ".webp"
            return member, name, data, None, name

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(convert, media.items()))

        changes = {m: (old, new, out) for m, old, _data, out, new in results if out is not None}
        renamed = {old: new for old, new, _out in changes.values() if old != new}
        taken = set(media.values())
        for old, new in renamed.items():
            if new in taken:
                raise ValueError(f"Cannot rename {old} to {new}: a file with that name already exists")
        before = sum(len(d) for _m, _n, d, _o, _nn in results)
        after = before - sum(len(d) - len(o) for _m, _n, d, o, _nn in results if o is not None)

        # Samples: a few changed files of each kind, spread across the deck.
        if samples_dir and samples:
            samples_dir.mkdir(parents=True, exist_ok=True)
            for kind in ("mp3", "img"):
                picked = [r for r in results if r[3] is not None and (r[1].lower().endswith(".mp3") == (kind == "mp3"))]
                for _m, old, data, out, new in picked[::max(1, len(picked) // samples)][:samples]:
                    stem = f"{src.stem}__{old.rsplit('.', 1)[0]}"
                    (samples_dir / f"{stem}__before.{old.rsplit('.', 1)[-1]}").write_bytes(data)
                    (samples_dir / f"{stem}__after.{new.rsplit('.', 1)[-1]}").write_bytes(out)

        # Notes: point at renamed files and mark every note using a changed file as newer.
        member = _collection_member(names)
        raw = zin.read(member)
        if member.endswith("21b"):
            raw = zstandard.ZstdDecompressor().stream_reader(raw).read()
        db = Path(tmp) / "collection.db"
        db.write_bytes(raw)
        conn = sqlite3.connect(db)
        conn.create_collation("unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
        changed_names = [old for old, _new, _out in changes.values()]
        pattern = re.compile("|".join(re.escape(n) for n in sorted(changed_names, key=len, reverse=True))) if changed_names else None
        now, touched = int(time.time()), 0
        for nid, flds in conn.execute("SELECT id, flds FROM notes").fetchall():
            if not pattern or not pattern.search(flds):
                continue
            new_flds = flds
            for old, new in renamed.items():
                new_flds = re.sub(rf'(src\s*=\s*["\']?){re.escape(old)}(?=["\'\s>])', rf"\g<1>{new}", new_flds)
            conn.execute("UPDATE notes SET flds=?, mod=?, usn=-1 WHERE id=?", (new_flds, now, nid))
            touched += 1
        conn.commit()
        conn.close()
        collection = db.read_bytes()
        if member.endswith("21b"):
            collection = zstandard.ZstdCompressor().compress(collection)

        # Media index.
        if new_format:
            for m, (old, new, out) in changes.items():
                entry = index[int(m)]
                _set(entry, 1, 2, new.encode())
                _set(entry, 2, 0, len(out))
                _set(entry, 3, 2, hashlib.sha1(out).digest())
            media_index = zstandard.ZstdCompressor().compress(write_media_index(index))
        else:
            for m, (old, new, _out) in changes.items():
                media[m] = new
            media_index = json.dumps(media).encode()

        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                if info.filename == member:
                    payload = collection
                elif info.filename == "media":
                    payload = media_index
                elif info.filename in changes:
                    out = changes[info.filename][2]
                    payload = zstandard.ZstdCompressor().compress(out) if new_format else out
                else:
                    payload = zin.read(info.filename)
                zout.writestr(info, payload, compress_type=info.compress_type)

    print(f"{src.name}: {len(changes)} media file(s) compressed ({len(renamed)} renamed), "
          f"{touched} note(s) marked newer, media {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB, "
          f"package {src.stat().st_size / 1e6:.1f} MB -> {dst.stat().st_size / 1e6:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--audio-kbps", type=int, help="Re-encode MP3 to mono at this bitrate")
    parser.add_argument("--webp", type=int, metavar="QUALITY", help="Convert JPEG/PNG images to WebP at this quality")
    parser.add_argument("--samples-dir", help="Write before/after examples here")
    parser.add_argument("--samples", type=int, default=3, help="Examples per kind and deck (default 3)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("apkg", nargs="+")
    args = parser.parse_args()
    if args.audio_kbps and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required for --audio-kbps")
    for src in map(Path, args.apkg):
        dst = Path(args.out_dir) / src.name
        if dst.resolve() == src.resolve():
            sys.exit("--out-dir must not be the folder of the input decks.")
        compress_apkg(src, dst, args.audio_kbps, args.webp,
                      Path(args.samples_dir) if args.samples_dir else None, args.samples, args.workers)


if __name__ == "__main__":
    main()
