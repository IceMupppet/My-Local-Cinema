# My Local Cinema

A lightweight, Netflix-style local web app for browsing and playing your personal library of **Movies**, **TV Shows**, **Standup**, and **Documentaries** — with posters/metadata from TMDB, “New” arrivals view, genre filters, archived badges, and one-click local playback (VLC or your default player).

> **Attribution:** This project uses the TMDB API but is not endorsed or certified by TMDB.

---

## Features

- **Home (“New”)** page  
  - Shows the **newest 16 Movies** and **newest 16 Standup** and **Documentary** items.  
  - **New Shows** are *condensed*: one card per show, listing the **last 5 added episodes** under the poster (with “…” if more were added).
  - Golden **NEW** badges appear here *and* on Movies/Shows pages for items flagged as new.
  - Header shows total size for **New Movies** and **New Shows** sections.

- **Movies / Standup / Documentary** pages  
  - Responsive poster grid, search, sort (Title/Year/Genre), **Genre filter**, archived filter.  
  - **Archived** items get a badge; the `0-ARCHIVED` folder itself is hidden from the grid.  
  - Detail page shows poster, backdrop gradient, overview, genres, certification, runtime, user score, **original filename + file size**, and a **Play** button (white/black style).

- **Shows** page  
  - Grid of shows (search, sort, genre filter).  
  - Show detail page locks poster size (no vertical stretching) and lists **seasons → episodes** with file sizes and per-episode **Play** buttons. NEW badge appears next to a newly added episode’s **Play** button.  
  - Episode titles are auto-filled from TMDB when missing in filenames.

- **Posters & metadata (TMDB)**  
  - Robust matching with normalization, year tolerance for movies, and **yearless search for Standup/Documentaries** (incl. colon‐title variant common in standup specials).  
  - Caches posters and metadata locally to speed up rebuilds.

- **Local playback**  
  - Uses `open -a VLC` when VLC is installed, otherwise `open` with your default player (macOS).  
  - Movies play from their **detail page** (no auto-play on card click).  
  - Shows play per episode from the show page.

- **Teal/gold polish**  
  - Branded “My Local Cinema” header (teal gradient), hover glow on cards, strong dividers, compact chip styles for metadata.

---

## Requirements

- **macOS** with Python **3.10+** (3.12 tested)
- Optional: **VLC** at `/Applications/VLC.app` for preferred playback
- **TMDB credentials** (API key or bearer token) for posters/metadata

---

## Installation

```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
# (Optional) create a venv
python3 -m venv .venv && source .venv/bin/activate
```

No third-party Python packages required (standard library only).

---

## Directory Layout Expectations

Each category points at a library root that contains folders (or files) named in your preferred scene-style format.

```
Movies/
  _cinema_site/        # generated site (auto-created)
  0-ARCHIVED/          # archived content (included, but folder hidden from grid)
  The.Matrix.1999.1080p.WEB-DL.x264-Group/
  Inception.2010.mkv
Shows/
  South.Park.S27E03.1080p.WEB.h264-ETHEL.mkv
  Its.Always.Sunny.in.Philadelphia.S17E02...
Standup/
  Andrew.Santino.Cheeseburger.2023.1080p...
Documentary/
  ZEF.The.Story.of.Die.Antwoord.2024...
```

**Video extensions scanned:** `.mkv .mp4 .mov .m4v .avi .wmv .ts .m2ts .webm`  
The generated site lives in `<Movies>/_cinema_site/`.

---

## Configuration

You can run with defaults or override via CLI flags:

- **Movies root (also site output location):** `/Users/icemuppet/OTHER/SCN/MOVIES`
- **Shows root:** `/Users/icemuppet/OTHER/SCN/SHOWS`
- **Standup root:** `/Users/icemuppet/OTHER/SCN/STANDUP`
- **Documentary root:** `/Users/icemuppet/OTHER/SCN/DOCUMENTARY`
- **Port:** `8000`

Set **one** TMDB credential:

```bash
# One of these is enough:
export TMDB_API_KEY="YOUR_TMDB_API_KEY"
# or:
export TMDB_BEARER_TOKEN="YOUR_LONG_BEARER_TOKEN"
```

(To persist across sessions, add the export line to your `~/.zshrc`.)

---

## Usage

### Build static pages only
```bash
python3 cinema.py
# open the generated site:
#   <Movies>/_cinema_site/index.html (Home/New)
#   <Movies>/_cinema_site/movies.html
#   <Movies>/_cinema_site/shows.html
#   <Movies>/_cinema_site/standup.html
#   <Movies>/_cinema_site/documentary.html
```

### Build and serve locally
```bash
python3 cinema.py --serve
# visit http://127.0.0.1:8000
```

### With custom roots / port
```bash
python3 cinema.py   --movies-root "/path/to/MOVIES"   --shows-root "/path/to/SHOWS"   --standup-root "/path/to/STANDUP"   --docs-root "/path/to/DOCUMENTARY"   --port 9000   --serve
```

### Quieter logs
```bash
python3 cinema.py --quiet --serve
```

---

## How “New” is determined

- **Movies/Standup/Docs:** newest **16** by file modification time of the main video.  
- **Shows:** newest **16 shows** by most recently modified episode; each card lists the **last 5 added episodes**.

“NEW” badges also appear on the Movies/Shows/Standup/Documentary pages for those items.

---

## Caching

Generated in `<Movies>/_cinema_site/`:

- `tmdb_movie_cache.json` — movie metadata (incl. Standup/Documentary)
- `tmdb_tv_cache.json` — show metadata
- `tmdb_tv_ep_cache.json` — per-episode titles
- `posters/` and `posters_tv/` — downloaded poster images
- `movies_meta.json`, `shows_meta.json`, `standup_meta.json`, `docs_meta.json` — rendered metadata
- `movies_index.json`, `standup_index.json`, `docs_index.json`, `episodes_index.json` — file lookups

**Refreshing:** delete any of the above to force re-query/rebuild.

---

## Matching & Metadata Rules

- **Movies:** title normalized; year sweep (year, ±1, ±2); then yearless fallback.  
- **Standup/Documentary:** **always yearless** queries; also tries a *colon* variant (e.g., “Andrew Santino: Cheeseburger”).  
- **TV Shows:** title normalization (drops trailing years like “(2022)”); picks best TMDB result; fills missing episode titles via TMDB per SxxEyy.

If a title still won’t match, check the console logs (disable `--quiet`) to see the attempted queries.

---

## Keyboard Shortcuts / Tips

- Click a **card** → opens the detail page (doesn’t auto-play).  
- Click **Play** on detail/episode rows to open in VLC (preferred) or default player.  
- Use the **search box** and **genre/archived filters** to narrow the grid.

---

## Troubleshooting

- **“NO TMDB CREDS; cannot search movie/TV”**  
  Re-export your `TMDB_API_KEY` **or** `TMDB_BEARER_TOKEN` in the same shell before running.

- **Posters missing for known titles**  
  - Clear caches:  
    `rm "<Movies>/_cinema_site/tmdb_movie_cache.json" "<Movies>/_cinema_site/tmdb_tv_cache.json" "<Movies>/_cinema_site/tmdb_tv_ep_cache.json" 2>/dev/null || true`  
  - Rebuild/serve and watch logs (no `--quiet`) to see the exact queries.

- **Nothing happens on Play**  
  Ensure VLC is installed at `/Applications/VLC.app`. Otherwise macOS `open` will use your default video player.

- **Show episodes duplicated**  
  The scanner dedupes by season/episode and keeps the **largest** file. If you still see dupes, check filenames for mismatched S/E tags.

---

## Optional Companion Scripts (Renamers)

If you also keep **renamers** in this repo:

- `rename_movies.py` — normalizes movie folder/file names to `Title.Year.Quality.Source.Codec-Group` and creates folders if only a file exists.
- `rename_tv.py` — normalizes shows to `Show.Name.SxxEyy.Episode.Title.Quality.Source.Codec-Group`; includes heuristics for sparse names (e.g., `Beavis and Butthead - 731 - Drinking Butt-ies.avi` → assumes S07E31, tags `HDTV`/`XviD` from `.avi`).

> These are optional; the web app works with whatever naming you already use.

---

## Roadmap Ideas

- Config file (`config.json`) for roots, “new” window size, theme
- “Play next” for shows (auto-advance)
- Watch progress + Recently Watched
- Keyboard navigation and quick filters
- Streaming to browser as an alternative to external player

---

## Contributing

Issues and PRs welcome! Please include:
- OS + Python version
- Example filenames/folders
- Relevant console logs (TMDB search lines)

---

## License

MIT — or your preferred license. (Update this section before publishing.)

---

## Acknowledgements

- Posters & metadata: **TMDB**  
- You — for building and curating a legendary local library. 🍿
