# Known issues and findings

Everything noticed while working on the decks, so it can be handled later. Add new findings here as soon as they are found (date, what, where, impact, how to fix), and move them to **Resolved** with the fixing release or PR.

## Open

### Raw 2nd Edition data: mislabeled, large images
- **Found:** 2026-10-17
- **Where:** 43 files in `data/2nd-edition/book*/images/` have a `.jpg` name but are PNG (42) or GIF (1, `restaurant.jpg`), 150–960 KB each (e.g. `carrot.jpg`, `Environment-Over-Convenience.jpg`).
- **Impact:** none on the published decks (the 2nd Edition deck uses the shared deck's own images); only repository size and confusion.
- **Fix (optional):** rename to the real extension or convert to JPEG if this data is ever used to build a deck.

### Old Books: more OCR typos are likely
- **Found:** 2026-10-17
- **Where:** definitions, examples and hints in Old Books 1–6. The author's own edits revealed ~25 merged/split words that automatic checks missed (`o f`, `Asa`, `fora`, `Ifyou`, `howto`, `mayorthought`, `a period often years`, `lamina dire`), now fixed in `data/corrections/old-books.json`.
- **Fix:** a systematic scan (dictionary-based split/merge detection over all English fields and the story text), reviewed by a person; keep fixes minimal and faithful to the book.

### Story text in `data/old-books/` still has OCR typos
- **Found:** 2026-10-17
- **Where:** e.g. `Frenhoferwas`, `herto`, `mayorthought`, `lamina dire` in the stories of `data.json`.
- **Impact:** the affected hints are fixed through `data/corrections/old-books.json`, but the source text is unchanged, so a new hint cut from these sentences would bring the typo back.
- **Fix:** together with the OCR scan above.

### GUID baselines describe the previous AnkiWeb versions
- **Found:** 2026-10-17
- **Where:** `data/guid-baseline/*.json`.
- **Impact:** none for compatibility (GUIDs, note types and fields are unchanged); `check_compat.py` just reports many notes as "updated".
- **Fix:** after the re-shared decks are public on AnkiWeb, download them and re-snapshot the baselines (prepared as a separate task).

### 2nd Edition on AnkiWeb hidden for copyright review
- **Found:** 2026-10-17
- **Where:** https://ankiweb.net/shared/info/1813442257 shows "missing or currently unavailable" after the re-share on 2026-10-17 ~00:48; AnkiWeb announced a 24-hour review.
- **Fix:** check it is back after ~2026-10-18 01:00 with its downloads and ratings.

### Local PC is unreliable for building packages
- **Found:** 2026-10-16
- **Where:** the author's PC: a blue screen, and the same unchanged file read with three different SHA-256 values on one day.
- **Impact:** packages built locally can be silently corrupted.
- **Fix:** build releases only with the **Release decks** workflow; run Windows Memory Diagnostic / MemTest86 and a disk check (`chkdsk`, SMART).

### Unusual media formats in the 2nd Edition deck
- **Found:** 2026-10-17
- **Where:** 72 `.wav`, 5 `.ogg` and 1 `.svg` file among the 2nd Edition media (from the original shared deck).
- **Fix (check):** confirm they play/display on AnkiMobile (iOS) and AnkiDroid; convert to MP3/PNG if not.

## Fixed, waiting for the next release

### Old Book 5: the "biography" image was empty
- **Found:** 2026-10-17. `data/old-books/book5/images/28063.jpg` (note `biography`, GUID `f..]!T6qT%`) was 38,738 bytes of zeros since the first dataset commit, so the card had no picture in every published Old Book 5 (AnkiWeb, GitHub v1.0.0–v1.2.0).
- **Fixed:** 2026-10-17 — restored from the author's Anki profile (`collection.media/28063-30103528147b49a8298c486287c1353b73ecfffd.jpg`, SHA-1 verified; a 300×300 JPEG). The next build picks it up through `fix_deck.py`'s media update (the note is marked newer) and converts it to WebP.
- **Ships with:** the next Old Books release (re-share Book 5 on AnkiWeb).

### 2nd Edition: one oversized image
- **Found:** 2026-10-17. `Brill_windmill_April_2017.jpg` (3832×2899 px, 5.0 MB, ≈9% of all 2nd Edition image data) on the note `mill` (GUID `fbb=[HIzxN`).
- **Fixed:** 2026-10-17 — `compress_media.py --max-image-side` (workflow input `max_image_side`, default 700 px) scales such images down, keeping aspect ratio and format. Tested: the windmill becomes 28 KB and the 2nd Edition package 217.2 → 212.3 MB. The 2nd Edition standard is 390×260 px; nine wide images (up to 650×260) share the standard height and are left as they are.
- **Ships with:** the next 2nd Edition release (`release_second_edition`).

## Notes (not bugs)

- Seven notes on AnkiWeb keep the author's own later edits and differ slightly from GitHub v2.1.0/v1.1.0: the translations of `worth`, `defer` and `helmet`, cosmetic HTML in `baggage` and `crumble`, and the audio file name of `texture`. GUIDs are identical, so this does not affect anyone's review history.
- AnkiWeb allows only two anonymous downloads; larger checks need a logged-in browser session.
- Running `fix_deck.py` on an already compressed Old Books deck would restore the original media from `data/`; always build from the original sources.
- About 200 2nd Edition images are only 100–199 px wide; they cannot be improved without a better source.

## Resolved

- **2026-10-16 — Hints, translations and typos** (PR #2, #3, releases v2.1.0 / v1.1.0).
- **2026-10-16 — Damaged media read in the local 2nd Edition package** turned out to be read errors on the local PC, not a damaged file; the GitHub/AnkiWeb copies are intact.
- **2026-10-17 — Old Books download size** reduced by ~42% (mono 32 kbps audio, WebP images), release v1.2.0 (PR #6, #7, #8, #9).
- **2026-10-17 — Corrected Book 4 media** (`26936`, `27065`, `27146` audio, `27117` image) included since v1.1.0.
