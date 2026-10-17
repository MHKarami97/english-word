# 4000 Essential English Words – Data Extractor

A robust Python-based downloader for extracting vocabulary data, images, and audio files from the **4000 Essential English Words** learning platform.

This tool automatically downloads structured vocabulary data (`data.json`) along with all associated **media assets (images and pronunciation audio)** for every unit and book.

---

## Data Source

All data is extracted from:
https://www.essentialenglish.review

This repository provides tools to download the publicly available resources, and also tracks the downloaded data and generated Anki decks under `data/` and `dist/`. All intellectual property rights belong to the original publisher.

## Supported Edition

Currently supported:
✅ **4000 Essential English Words – First Edition (Old Books)**
✅ **4000 Essential English Words – Second Edition**

## Ready-to-Use Decks

Pre-built `.apkg` decks are published on the [Releases](../../releases) page — no need to run the scripts yourself.

### 4000 EEW (2nd Edition)

AnkiWeb Shared Decks **(easy to use)**:
[All Books](https://ankiweb.net/shared/info/1813442257)

Built on top of the shared **"4000 Essential English Words"** AnkiWeb deck ([ankiweb.net/shared/info/1104981491](https://ankiweb.net/shared/info/1104981491), based on the book by Paul Nation, Compass Publishing), with two additions:
- **Hint** — a contextual example sentence for each word, extracted from the official 2nd Edition reading passages
- **FaMeaning / FaExample** — Persian (Farsi) translations of the Meaning and Example fields, shown as a collapsible "فا" toggle

📥 Download: [Release v2.1.0](../../releases/tag/v2.1.0) — already studying the AnkiWeb version or v2.0.0? Import it over your deck; your review history is kept.

| Front | Back |
|---|---|
| ![2nd Edition – front](docs/2nd-edition-front.png) | ![2nd Edition – back](docs/2nd-edition-back.png) |

### 4000 EEW (Old Books / First Edition)

AnkiWeb Shared Decks **(easy to use)**:
[Book 1](https://ankiweb.net/shared/info/876489453)
[Book 2](https://ankiweb.net/shared/info/49468437)
[Book 3](https://ankiweb.net/shared/info/1348583674)
[Book 4](https://ankiweb.net/shared/info/648820475)
[Book 5](https://ankiweb.net/shared/info/893444455)
[Book 6](https://ankiweb.net/shared/info/70990553)

The original 6-book deck generated from `data/old-books/`, with contextual Hint sentences extracted from the reading passages.

📥 Download: [Release v1.1.0](../../releases/tag/v1.1.0) — already studying the AnkiWeb version or v1.0.0? Import it over your decks; your review history is kept.

| Front | Back |
|---|---|
| ![Old Books – front](docs/old-books-front.png) | ![Old Books – back](docs/old-books-back.png) |

## Features

- **Automated Extraction:** Downloads vocabulary metadata, images, and audio.
- **Robustness:** Built-in retry mechanisms for network failures.
- **Efficiency:** Streaming downloads to optimize memory usage and "skip existing" logic to prevent redundant downloads.
- **Organization:** Automatic creation of a structured `data/` directory for each book.
- **Proxy Support:** Configurable proxy settings for restricted network environments.
- **Anki Deck Generation:** Builds `.apkg` decks from the scraped data, with story-based Hint sentences and Persian (Farsi) translations.

## Project Structure

All scripts assume they are run from the repo root (e.g. `python scripts/scrape/download_old_books.py`).

```text
scripts/
  scrape/               # Downloaders for each edition
    download_2nd_edition.py
    download_old_books.py
  generate/             # Builds .apkg decks from scraped data
    anki_generator.py
  translate/             # Adds Hints / Persian translations to an existing deck
    add_hints_to_shared_deck.py
    translate_deck_dahl.py
    translate_deck_deepl.py
  compat/               # Keeps updates safe for people already studying the decks
    check_compat.py
  fix/                  # Fixes hints, Persian translations and typos in built decks
    content_fixes.py
    fix_deck.py
    compress_media.py   # Mono MP3 / WebP media for smaller downloads

data/                   # Raw scraped data (data.json, images/, audio/) per book
  2nd-edition/book{1..6}/
  old-books/book{1..6}/
  guid-baseline/        # Note GUIDs of the decks as published on AnkiWeb
    old-books.json
    2nd-edition.json
  corrections/          # Manual fixes (typos, translations) by note GUID
    old-books.json
    2nd-edition.json

dist/                   # Generated Anki decks (.apkg)
  old-books/
  shared-deck/

docs/                   # Screenshots referenced in this README
```

## Updating the Published Decks Safely

Many people already study these decks from AnkiWeb. Anki recognises a note by its **GUID**: if an updated deck keeps the same GUIDs, importing it only refreshes the card contents and users keep all their review history. If a GUID changes, Anki imports the note as a brand-new card — a duplicate with no history.

`data/guid-baseline/` records the GUIDs, notetypes and fields of the decks exactly as they were published:

| Baseline | AnkiWeb |
|---|---|
| `old-books.json` | [Book 1](https://ankiweb.net/shared/info/876489453), [Book 2](https://ankiweb.net/shared/info/49468437), [Book 3](https://ankiweb.net/shared/info/1348583674), [Book 4](https://ankiweb.net/shared/info/648820475), [Book 5](https://ankiweb.net/shared/info/893444455), [Book 6](https://ankiweb.net/shared/info/70990553) |
| `2nd-edition.json` | [2nd Edition [en-fa]](https://ankiweb.net/shared/info/1813442257) |

`anki_generator.py` reuses the baseline GUIDs, so fixing a definition, hint or translation never creates new notes. Before re-sharing any deck, run the check:

```bash
python scripts/compat/check_compat.py check --baseline data/guid-baseline/old-books.json dist/old-books/*.apkg
python scripts/compat/check_compat.py check --baseline data/guid-baseline/2nd-edition.json "dist/shared-deck/4000 EEW (2nd Edition).apkg"
```

Only upload to AnkiWeb when it prints `OK`. Add `--only-decks-present` when checking a single Old Book. After a deck is re-shared, record it as the new baseline:

```bash
python scripts/compat/check_compat.py snapshot --out data/guid-baseline/old-books.json dist/old-books/*.apkg
```

Rules the check enforces:
- **Never change** a notetype ID (`MODEL_ID`), its field list or field order, or remove/reorder card templates.
- **Never drop** a published note or give it a new GUID.
- **Safe:** editing field contents, CSS and card layout, renaming decks, adding new notes.

## Fixing Hints, Translations and Typos

`scripts/fix/fix_deck.py` cleans up a built deck in place of rebuilding it, keeping every GUID and media file:

- **Hints** are re-cut from the unit's story: complete sentences, balanced quotes, no stray spaces before punctuation, no story titles glued in front, and very short sentences get the sentence before them as extra context.
- **Persian** fields use Persian ی/ک and get the final punctuation of the English source.
- **Manual corrections** in `data/corrections/<edition>.json` fix typos and broken translations. Add new ones there (keyed by note GUID) rather than editing a deck by hand.

```bash
python scripts/fix/fix_deck.py --edition old-books --out-dir dist/fixed --report dist/fixed/changes-old-books.md dist/old-books/*.apkg
python scripts/fix/fix_deck.py --edition 2nd-edition --out-dir dist/fixed --report dist/fixed/changes-2nd-edition.md "dist/shared-deck/4000 EEW (2nd Edition).apkg"
```

Releases are built and checked on GitHub's servers by the **Release decks** workflow (`.github/workflows/release-decks.yml`, run it from the Actions tab; tick *publish* only after a dry run). `scripts/compat/verify_apkg.py` checks package integrity (CRC and media SHA-1).

The `--report` file lists every changed field for review. `anki_generator.py` applies the same rules, so a fresh Old Books build matches `fix_deck.py`'s output. Media files are verified too; a damaged one can be restored with `--repair-media-from` pointing at Anki's `collection.media` folder.

### Smaller downloads

`scripts/fix/compress_media.py` runs after `fix_deck.py` in the release workflow: MP3 audio becomes mono (48 kbps for the 2nd Edition, 32 kbps for the Old Books) and Old Books images become WebP. Files that are already compressed are never re-encoded, and every note that uses a changed file is marked newer so imports switch to the new files. Always build from the original sources (`dist/old-books/`, the v2.0.0 release) — running `fix_deck.py` on an already compressed Old Books deck would restore the original media from `data/`.
