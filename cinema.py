#!/usr/bin/env python3
"""
My Local Cinema — Movies + Shows + Standup + Documentary
- "New" home (condensed shows, plus Standup & Documentary)
- Genre filters
- TMDB metadata (Movies + TV) with robust matching + verbose logging
- Local playback via VLC (or default player)
"""

import os, re, json, time, argparse, urllib.parse, urllib.request, urllib.error, subprocess, shutil, math
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial

# ====== DEFAULT ROOTS ======
DEFAULT_MOVIES_ROOT  = "/Users/icemuppet/OTHER/SCN/MOVIES"
DEFAULT_SHOWS_ROOT   = "/Users/icemuppet/OTHER/SCN/SHOWS"
DEFAULT_STANDUP_ROOT = "/Users/icemuppet/OTHER/SCN/STANDUP"
DEFAULT_DOCS_ROOT    = "/Users/icemuppet/OTHER/SCN/DOCUMENTARY"

# ====== CONFIG ======
OUTPUT_DIR_NAME   = "_cinema_site"
ARCHIVED_DIR_NAME = "0-ARCHIVED"
EXCLUDED_DIRS     = {OUTPUT_DIR_NAME}
PREFER_VLC        = True
CACHE_POSTERS     = True
VIDEO_EXTS        = {".mkv",".mp4",".mov",".m4v",".avi",".wmv",".ts",".m2ts",".webm"}

# Logging
LOG_TMDB = True
def log(*args):
    if LOG_TMDB:
        print("[TMDB]", *args)

# TMDB creds (use one or both)
TMDB_BEARER_TOKEN = os.getenv("TMDB_BEARER_TOKEN", "").strip()
TMDB_API_KEY      = os.getenv("TMDB_API_KEY", "").strip()

# TMDB endpoints
TMDB_SEARCH_MOVIE = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_URL    = "https://api.themoviedb.org/3/movie/{id}"
TMDB_SEARCH_TV    = "https://api.themoviedb.org/3/search/tv"
TMDB_TV_URL       = "https://api.themoviedb.org/3/tv/{id}"
TMDB_TV_EP_URL    = "https://api.themoviedb.org/3/tv/{id}/season/{s}/episode/{e}"
TMDB_IMG_BASE     = "https://image.tmdb.org/t/p"
POSTER_SIZE       = "w342"
BACKDROP_SIZE     = "w1280"

# ====== UTIL ======
def _tmdb_url(base, params):
    params = dict(params)
    params.setdefault("language", "en-US")
    if TMDB_BEARER_TOKEN:
        return base + "?" + urllib.parse.urlencode(params)
    elif TMDB_API_KEY:
        params["api_key"] = TMDB_API_KEY
        return base + "?" + urllib.parse.urlencode(params)
    else:
        return base + "?" + urllib.parse.urlencode(params)  # still build, but will 401

def _tmdb_open(url):
    try:
        if TMDB_BEARER_TOKEN:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TMDB_BEARER_TOKEN}"})
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "ignore")
        except Exception: pass
        log("HTTPError", e.code, url, body[:200])
        return None
    except Exception as e:
        log("OPEN ERROR", url, repr(e))
        return None

def html_text(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def html_attr(s: str) -> str:
    return html_text(s)

def safe_size(path: str) -> int:
    try: return os.path.getsize(path)
    except Exception: return 0

def safe_mtime(path: str) -> float:
    try: return os.path.getmtime(path)
    except Exception: return 0.0

def folder_size(root: str, exclude_names: set[str] | None = None) -> int:
    if not root or not os.path.isdir(root): return 0
    exclude_names = exclude_names or set()
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_names and not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."): continue
            fp = os.path.join(dirpath, fname)
            if os.path.islink(fp): continue
            total += safe_size(fp)
    return total

def format_size_lower(nbytes: int) -> str:
    units = [("tb", 1024**4), ("gb", 1024**3), ("mb", 1024**2), ("kb", 1024)]
    for name, base in units:
        if nbytes >= base:
            val = nbytes / base
            return f"{int(round(val))}{name}" if val >= 10 else f"{val:.1f}{name}"
    return "0b"

# ====== MOVIE-LIKE DISCOVERY (Movies/Standup/Documentary) ======
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")

def parse_title_year_from_folder(name: str):
    s = name.replace(".", " ")
    s = re.sub(r"[()\[\]{}_+]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = YEAR_RE.search(s)
    if not m: return (s, None)
    year = int(m.group(1))
    title = s[:m.start()].strip()
    title = re.sub(r"\s+", " ", title)
    return (title, year)

def find_video_in_folder(folder_path: str):
    best, best_size = None, -1
    try:
        for root, _, files in os.walk(folder_path):
            for f in files:
                _, ext = os.path.splitext(f)
                if ext.lower() in VIDEO_EXTS:
                    fp = os.path.join(root, f)
                    size = safe_size(fp)
                    if size > best_size:
                        best, best_size = fp, size
            break  # only top level
    except Exception:
        pass
    return best

def discover_video_pool(root: str, base_dir: str, archived: bool, start_id: int, skip_archived_folder_in_root=False, id_prefix="m"):
    items, i = [], start_id
    if not os.path.isdir(base_dir): return items, i
    for entry in sorted(os.listdir(base_dir)):
        if entry.startswith(".") or entry in EXCLUDED_DIRS: continue
        if skip_archived_folder_in_root and entry == ARCHIVED_DIR_NAME: continue
        p = os.path.join(base_dir, entry)
        if os.path.isdir(p):
            title, year = parse_title_year_from_folder(entry)
            vid = find_video_in_folder(p)
            rel = os.path.relpath(vid, root) if vid else ""
            items.append({"id": f"{id_prefix}{i}", "title": title, "year": year, "abs_path": vid or "", "rel_path": rel,
                          "source": entry, "archived": archived, "mtime": safe_mtime(vid or "")})
            i += 1
        elif os.path.isfile(p):
            base, ext = os.path.splitext(entry)
            if ext.lower() not in VIDEO_EXTS: continue
            title, year = parse_title_year_from_folder(base)
            rel = os.path.relpath(p, root)
            items.append({"id": f"{id_prefix}{i}", "title": title, "year": year, "abs_path": p, "rel_path": rel,
                          "source": entry, "archived": archived, "mtime": safe_mtime(p)})
            i += 1
    return items, i

def discover_category(root: str, id_prefix="m"):
    # Skip showing the ARCHIVED folder itself while still indexing its contents
    items, next_id = discover_video_pool(root, root, archived=False, start_id=1, skip_archived_folder_in_root=True, id_prefix=id_prefix)
    arch_dir = os.path.join(root, ARCHIVED_DIR_NAME)
    arch_items, _ = discover_video_pool(root, arch_dir, archived=True, start_id=next_id, id_prefix=id_prefix)
    return items + arch_items

# ====== SHOWS DISCOVERY ======
SxxEyy_RE = re.compile(r"\b[Ss]\s*(\d{1,2})\s*[.\-_ ]*[Ee]\s*(\d{1,2})\b")
QUALITY_SET = {"2160P","1080P","720P","480P"}

def clean_name(s: str) -> str:
    s = s.replace("_"," ").replace(".", " ")
    s = re.sub(r"[()\[\]{}]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_show_from_string(text: str):
    s = clean_name(text)
    m = SxxEyy_RE.search(s)
    if not m: return None
    season = int(m.group(1)); episode = int(m.group(2))
    show_name = s[:m.start()].strip()
    tail = s[m.end():].strip()
    tokens = [t for t in re.split(r"\s+", tail) if t]
    ep_title_tokens = []
    for t in tokens:
        if t.upper() in QUALITY_SET:
            break
        ep_title_tokens.append(t)
    ep_title = " ".join(ep_title_tokens).strip()
    return {"show": show_name, "season": season, "episode": episode, "ep_title": ep_title}

def _add_or_update_episode(meta_for_show: dict, season: int, epnum: int, title: str, file_path: str):
    season_key = str(season)
    meta_for_show["seasons"].setdefault(season_key, [])
    lst = meta_for_show["seasons"][season_key]
    size = safe_size(file_path)
    mtime = safe_mtime(file_path)
    for item in lst:
        if item["e"] == epnum:
            if size > item.get("size", 0):
                item["file"] = file_path
                item["size"] = size
                item["mtime"] = mtime
            if not item.get("title") and title:
                item["title"] = title
            return
    lst.append({"eid": None, "s": season, "e": epnum, "title": title, "file": file_path, "size": size, "mtime": mtime})

def discover_shows(shows_root: str):
    shows_meta = {}
    shows_map = {}
    show_id_seq = 1
    if not os.path.isdir(shows_root):
        return [], {}, {}

    def handle_file(fp, fname):
        nonlocal show_id_seq
        if not (os.path.isfile(fp) and os.path.splitext(fname)[1].lower() in VIDEO_EXTS):
            return
        parsed = parse_show_from_string(fname)
        if not parsed: return
        show_title = parsed["show"]
        key = show_title.lower()
        if key not in shows_map:
            sid = f"tv{show_id_seq}"
            show_id_seq += 1
            shows_map[key] = sid
            shows_meta[sid] = {
                "title": show_title, "poster_url": "", "overview": "",
                "genres": [], "vote": None, "first_year": None, "cast": [],
                "backdrop_url": "", "tagline": "", "tv_id": None,
                "seasons": {}
            }
        sid = shows_map[key]
        _add_or_update_episode(shows_meta[sid], parsed["season"], parsed["episode"], parsed["ep_title"], fp)

    for entry in sorted(os.listdir(shows_root)):
        if entry.startswith(".") or entry in EXCLUDED_DIRS: continue
        p = os.path.join(shows_root, entry)
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                handle_file(os.path.join(p, f), f)
        elif os.path.isfile(p):
            handle_file(p, entry)

    # sort episodes and assign EIDs; build index
    episodes_index = {}
    for sid, meta in shows_meta.items():
        for skey, eps in meta["seasons"].items():
            eps.sort(key=lambda x: x["e"])
            for item in eps:
                eid = f"{sid}_S{int(skey):02d}E{item['e']:02d}"
                item["eid"] = eid
                episodes_index[eid] = item["file"]

    # card list
    shows_list = []
    for key, sid in shows_map.items():
        shows_list.append({
            "id": sid,
            "title": shows_meta[sid]["title"],
            "poster_url": "",
            "overview": "",
            "first_year": None,
            "show_href": f"/show?id={urllib.parse.quote(sid)}"
        })
    return shows_list, shows_meta, episodes_index

# ====== TMDB HELPERS ======
def minutes_to_hm(m):
    if not m: return None
    h = m // 60; mm = m % 60
    return f"{h}h {mm}m" if h else f"{mm}m"

def load_cache(path): 
    if os.path.isfile(path):
        try:
            with open(path,"r",encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return {}

def save_cache(path, obj):
    try:
        with open(path,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)
    except Exception: pass

def download_file(url: str, dest_path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with urllib.request.urlopen(url, timeout=20) as r, open(dest_path,"wb") as out:
            shutil.copyfileobj(r, out)
        return True
    except Exception as e:
        log("POSTER DOWNLOAD FAIL", url, repr(e))
        return False

# ---------- Matching / scoring ----------
def _norm_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # harmless article drop for better matches
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return t

def _token_set(t: str) -> set:
    return set(_norm_title(t).split())

def _year_score(query_year, cand_year):
    try:
        if not query_year or not cand_year: return 0.0
        diff = abs(int(query_year) - int(cand_year))
        if diff == 0: return 0.25
        if diff <= 1: return 0.18
        if diff == 2: return 0.1
        return -0.1
    except Exception:
        return 0.0

def _sim_score(qtitle: str, ctitle: str, qyear: int|None, cyear: int|None, has_poster: bool):
    qs, cs = _token_set(qtitle), _token_set(ctitle)
    inter = len(qs & cs)
    union = max(1, len(qs | cs))
    jacc = inter / union
    y = _year_score(qyear, cyear)
    poster_bonus = 0.05 if has_poster else 0.0
    # bonus if one is colon-variant of the other (standup specials)
    colon_bonus = 0.08 if _norm_title(qtitle).replace(":", "") in _norm_title(ctitle).replace(":", "") or \
                           _norm_title(ctitle).replace(":", "") in _norm_title(qtitle).replace(":", "") else 0.0
    return jacc + y + poster_bonus + colon_bonus

# ====== MOVIE ENRICHMENT (Movies/Standup/Documentary) ======
def tmdb_search_movie(title: str, year: int | None):
    if not (TMDB_BEARER_TOKEN or TMDB_API_KEY):
        log("NO TMDB CREDS; cannot search movie:", title, year)
        return None
    params = {"query": title, "include_adult": "false", "page": 1}
    if year: params["year"] = str(year)
    url = _tmdb_url(TMDB_SEARCH_MOVIE, params)
    log("SEARCH MOVIE", {"title": title, "year": year, "url": url})
    return _tmdb_open(url)

def tmdb_movie_details(mid: int):
    if not (TMDB_BEARER_TOKEN or TMDB_API_KEY): return None
    url = _tmdb_url(TMDB_MOVIE_URL.format(id=mid), {"append_to_response":"credits,release_dates"})
    log("DETAIL MOVIE", mid)
    return _tmdb_open(url)

def extract_cert_from_movie_release_dates(release_dates):
    try:
        for entry in release_dates.get("results", []):
            if entry.get("iso_3166_1") == "US":
                for rel in entry.get("release_dates", []):
                    cert = (rel.get("certification") or "").strip()
                    if cert: return cert
    except Exception: pass
    return None

def _pick_best_movie(result_json, query_title, query_year):
    if not result_json: return None
    results = result_json.get("results") or []
    log("MOVIE RESULTS", len(results))
    best, best_score = None, -1
    for r in results[:10]:
        cand_title = r.get("title") or r.get("original_title") or ""
        release_date = r.get("release_date") or ""
        cyear = int(release_date[:4]) if release_date[:4].isdigit() else None
        poster = bool(r.get("poster_path"))
        sc = _sim_score(query_title, cand_title, query_year, cyear, poster)
        log("  cand:", cand_title, cyear, "score:", f"{sc:.3f}", "poster:", poster)
        if sc > best_score:
            best_score = sc
            best = r
    if best:
        log("PICKED MOVIE:", best.get("title"), best.get("id"), f"score={best_score:.3f}")
    return best

def enrich_movies(items, site_dir: str):
    cache_path = os.path.join(site_dir, "tmdb_movie_cache.json")
    cache = load_cache(cache_path)
    enriched = []
    for item in items:
        key = f"{item['title']}|{item['year']}"
        c = cache.get(key, {}) or {}
        poster_url = c.get("poster_url","")
        overview   = c.get("overview","")
        movie_id   = c.get("movie_id")
        genres     = c.get("genres")
        runtime    = c.get("runtime")
        vote       = c.get("vote")
        cert       = c.get("certification")
        cast       = c.get("cast")
        backdrop   = c.get("backdrop_url","")
        tagline    = c.get("tagline","")

        need_details = not (genres and runtime is not None and vote is not None and cert is not None and cast)
        
        def try_search_variants(title, year, force_yearless=False):
            """
            Movies: try (year, year±1..±2) then yearless.
            Standup/Docs (force_yearless=True): ALWAYS yearless searches and strip any year tokens from the text.
            Also try a colon variant (common for stand-up specials).
            Returns (best_result_dict, used_title) or (None, None).
            """
            # Base title (strip any standalone year tokens when forcing yearless)
            t_base = title
            if force_yearless:
                t_base = re.sub(r"\b(19\d{2}|20\d{2})\b", "", t_base)
                t_base = re.sub(r"\s+", " ", t_base).strip()

            # Build text variants (never append a year to the query string itself)
            variants = [
                t_base,
                re.sub(r"[._]+", " ", t_base),
                re.sub(r"[^\w\s:]", " ", t_base).strip(),  # keep ':' if present
            ]

            # ADD COLON VARIANT **ONLY** FOR STANDUP/DOCS
            if force_yearless and ":" not in t_base:
                words = re.sub(r"\s+", " ", t_base).split()
                if len(words) >= 2:
                    if len(words) == 2:
                        variants.append(f"{words[0]}: {words[1]}")
                    else:
                        variants.append(f"{words[0]} {words[1]}: {' '.join(words[2:])}")


            seen = set()
            def attempt(qtitle, y):
                key = (qtitle or "").lower() + "|" + str(y)
                if not qtitle or key in seen:
                    return None
                seen.add(key)
                # Force yearless for standup/docs
                use_year = None if force_yearless else y
                data = tmdb_search_movie(qtitle, use_year)
                if data and (data.get("results") or []):
                    best = _pick_best_movie(data, qtitle, use_year)
                    if best:
                        return (best, qtitle)
                return None

            # Standup/Docs: ONLY yearless attempts
            if force_yearless:
                for t in variants:
                    res = attempt(t, None)
                    if res: return res
                # extra fallback: remove colon and collapse spaces
                t0 = re.sub(":", " ", variants[0]); t0 = re.sub(r"\s+"," ", t0).strip()
                return attempt(t0, None) or (None, None)

            # Movies: year sweep, then yearless
            year_sweep = [year, year-1, year+1, year-2, year+2] if year else []
            for y in year_sweep:
                for t in variants:
                    res = attempt(t, y)
                    if res: return res
            for t in variants:
                res = attempt(t, None)
                if res: return res
            t0 = re.sub(":", " ", variants[0]); t0 = re.sub(r"\s+"," ", t0).strip()
            return attempt(t0, None) or (None, None)



        if not movie_id or need_details or not poster_url or not overview:
            best, used_title = try_search_variants(item["title"], item["year"])
            if best:
                movie_id = best.get("id") or movie_id
                pp = best.get("poster_path"); poster_url = f"{TMDB_IMG_BASE}/{POSTER_SIZE}{pp}" if pp else poster_url
                overview = (best.get("overview") or overview or "").strip()
            else:
                log("NO MOVIE MATCH", item["title"], item["year"])

        if movie_id and (need_details or not backdrop or not tagline):
            det = tmdb_movie_details(movie_id)
            if det:
                genres  = genres or [g.get("name") for g in (det.get("genres") or []) if g.get("name")]
                runtime = det.get("runtime") if runtime is None else runtime
                vote    = det.get("vote_average") if vote is None else vote
                tagline = (det.get("tagline") or tagline or "").strip()
                bp = det.get("backdrop_path"); backdrop = f"{TMDB_IMG_BASE}/{BACKDROP_SIZE}{bp}" if bp and not backdrop else backdrop
                cert = cert or extract_cert_from_movie_release_dates(det.get("release_dates") or {})
                if not cast:
                    cast = [c.get("name") for c in (det.get("credits", {}).get("cast", []) or []) if c.get("name")]
                    cast = cast[:5] if cast else []
            else:
                log("NO MOVIE DETAILS", movie_id)

        cache[key] = {"movie_id": movie_id, "poster_url": poster_url, "overview": overview,
                      "genres": genres or [], "runtime": runtime, "vote": vote, "certification": cert,
                      "cast": cast or [], "backdrop_url": backdrop or "", "tagline": tagline or ""}
        save_cache(cache_path, cache)

        local_poster = ""
        if CACHE_POSTERS and poster_url:
            posters_dir = os.path.join(site_dir, "posters")
            basename = os.path.basename(urllib.parse.urlparse(poster_url).path)
            local = os.path.join(posters_dir, basename or f"{item['id']}.jpg")
            if not os.path.isfile(local):
                if download_file(poster_url, local): local_poster = "posters/" + os.path.basename(local)
            else:
                local_poster = "posters/" + os.path.basename(local)

        e = dict(item)
        e["poster_url"] = local_poster if local_poster else poster_url
        e["overview"]   = cache[key]["overview"]
        e["genres"]     = cache[key]["genres"]
        e["runtime"]    = cache[key]["runtime"]
        e["vote"]       = cache[key]["vote"]
        e["certification"] = cache[key]["certification"]
        e["cast"]       = cache[key]["cast"]
        e["backdrop_url"] = cache[key]["backdrop_url"]
        e["tagline"]    = cache[key]["tagline"]
        enriched.append(e)
        time.sleep(0.12)
    return enriched

# ====== TV ENRICHMENT ======
def normalize_title_for_search(t: str) -> str:
    t = t.replace(".", " ").replace("_", " ")
    t = re.sub(r"\s*\(\d{4}\)\s*$","", t)
    t = re.sub(r"\b(19\d{2}|20\d{2})\b\s*$","", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+"," ", t).strip()
    return t

def strip_trailing_year(title: str) -> str:
    t = re.sub(r"[.\s]*\b(19\d{2}|20\d{2})\b\s*$", "", title).strip()
    return t

def tmdb_search_tv(title: str):
    if not (TMDB_BEARER_TOKEN or TMDB_API_KEY):
        log("NO TMDB CREDS; cannot search tv:", title)
        return None
    params = {"query": title, "include_adult": "false", "page": 1}
    url = _tmdb_url(TMDB_SEARCH_TV, params)
    log("SEARCH TV", {"title": title, "url": url})
    return _tmdb_open(url)

def tmdb_tv_details(tvid: int):
    if not (TMDB_BEARER_TOKEN or TMDB_API_KEY): return None
    url = _tmdb_url(TMDB_TV_URL.format(id=tvid), {"append_to_response":"credits"})
    log("DETAIL TV", tvid)
    return _tmdb_open(url)

def tmdb_tv_episode_details(tvid: int, season: int, episode: int):
    if not (TMDB_BEARER_TOKEN or TMDB_API_KEY): return None
    url = _tmdb_url(TMDB_TV_EP_URL.format(id=tvid, s=season, e=episode), {})
    log("DETAIL EP", tvid, season, episode)
    return _tmdb_open(url)

def first_air_year_from(date_str: str | None):
    if not date_str: return None
    try: return int(date_str.split("-")[0])
    except Exception: return None

def _pick_best_tv(result_json, query_title):
    if not result_json: return None
    results = result_json.get("results") or []
    log("TV RESULTS", len(results))
    best, best_score = None, -1
    for r in results[:10]:
        cand_title = r.get("name") or r.get("original_name") or ""
        first_air = r.get("first_air_date") or ""
        cyear = int(first_air[:4]) if first_air[:4].isdigit() else None
        poster = bool(r.get("poster_path"))
        sc = _sim_score(query_title, cand_title, None, cyear, poster)
        log("  cand:", cand_title, cyear, "score:", f"{sc:.3f}", "poster:", poster)
        if sc > best_score:
            best_score = sc
            best = r
    if best:
        log("PICKED TV:", best.get("name"), best.get("id"), f"score={best_score:.3f}")
    return best

def enrich_shows(shows_list, shows_meta, site_dir: str):
    cache_path = os.path.join(site_dir, "tmdb_tv_cache.json")
    cache = load_cache(cache_path)

    for show in shows_list:
        title = show["title"]
        key = title.lower()
        c = cache.get(key, {}) or {}
        poster_url = c.get("poster_url","")
        overview   = c.get("overview","")
        tv_id      = c.get("tv_id")
        genres     = c.get("genres")
        vote       = c.get("vote")
        first_year = c.get("first_year")
        cast       = c.get("cast")
        backdrop   = c.get("backdrop_url","")
        tagline    = c.get("tagline","")

        need_details = not (genres and vote is not None and first_year is not None and cast)

        def try_tv_variants(title_in):
            variants = [
                title_in,
                strip_trailing_year(title_in),
                normalize_title_for_search(title_in),
                normalize_title_for_search(strip_trailing_year(title_in)),
            ]
            seen=set()
            for t in variants:
                t=t.strip()
                if not t or t.lower() in seen: continue
                seen.add(t.lower())
                data = tmdb_search_tv(t)
                if data and (data.get("results") or []):
                    best = _pick_best_tv(data, t)
                    if best:
                        return (best, t)
            return (None, None)

        if not tv_id or need_details or not poster_url or not overview:
            best, used_title = try_tv_variants(title)
            if best:
                tv_id = best.get("id") or tv_id
                pp = best.get("poster_path");  poster_url = f"{TMDB_IMG_BASE}/{POSTER_SIZE}{pp}" if pp else poster_url
                overview = (best.get("overview") or overview or "").strip()
                first_year = first_air_year_from(best.get("first_air_date"))
            else:
                log("NO TV MATCH", title)

        if tv_id and (need_details or not backdrop or not tagline):
            det = tmdb_tv_details(tv_id)
            if det:
                genres  = genres or [g.get("name") for g in (det.get("genres") or []) if g.get("name")]
                vote    = det.get("vote_average") if vote is None else vote
                tagline = (det.get("tagline") or tagline or "").strip()
                bp = det.get("backdrop_path"); backdrop = f"{TMDB_IMG_BASE}/{BACKDROP_SIZE}{bp}" if bp and not backdrop else backdrop
                if not first_year:
                    first_year = first_air_year_from(det.get("first_air_date"))
                if not cast:
                    cast = [c.get("name") for c in (det.get("credits", {}).get("cast", []) or []) if c.get("name")]
                    cast = cast[:5] if cast else []
            else:
                log("NO TV DETAILS", tv_id)

        cache[key] = {"tv_id": tv_id, "poster_url": poster_url, "overview": overview, "genres": genres or [],
                      "vote": vote, "first_year": first_year, "cast": cast or [],
                      "backdrop_url": backdrop or "", "tagline": tagline or ""}
        save_cache(cache_path, cache)

        local_poster = ""
        if CACHE_POSTERS and poster_url:
            posters_dir = os.path.join(site_dir, "posters_tv")
            basename = os.path.basename(urllib.parse.urlparse(poster_url).path)
            local = os.path.join(posters_dir, basename or f"{show['id']}.jpg")
            if not os.path.isfile(local):
                if download_file(poster_url, local): local_poster = "posters_tv/" + os.path.basename(local)
            else:
                local_poster = "posters_tv/" + os.path.basename(local)

        show["poster_url"] = local_poster if local_poster else poster_url
        show["overview"]   = cache[key]["overview"]
        show["first_year"] = cache[key]["first_year"]

        sid = show["id"]
        shows_meta[sid].update({
            "poster_url": show["poster_url"],
            "overview":   cache[key]["overview"],
            "genres":     cache[key]["genres"],
            "vote":       cache[key]["vote"],
            "first_year": cache[key]["first_year"],
            "cast":       cache[key]["cast"],
            "backdrop_url": cache[key]["backdrop_url"],
            "tagline":    cache[key]["tagline"],
            "tv_id":      cache[key]["tv_id"]
        })
        time.sleep(0.12)

    return shows_list, shows_meta

def fill_episode_titles_from_tmdb(shows_meta: dict, site_dir: str):
    cache_path = os.path.join(site_dir, "tmdb_tv_ep_cache.json")
    cache = load_cache(cache_path)
    for sid, meta in shows_meta.items():
        tv_id = meta.get("tv_id")
        if not tv_id:
            continue
        for skey, eps in meta.get("seasons", {}).items():
            season = int(skey)
            for ep in eps:
                if ep.get("title"): continue
                epnum = int(ep["e"])
                ckey = f"{tv_id}|{season}|{epnum}"
                name = cache.get(ckey)
                if not name:
                    det = tmdb_tv_episode_details(tv_id, season, epnum)
                    name = (det or {}).get("name") or ""
                    cache[ckey] = name
                    save_cache(cache_path, cache)
                    time.sleep(0.10)
                if name:
                    ep["title"] = name
    return shows_meta

# ====== SHARED CSS/HEADER ======
HEADER_TOP = """
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700;900&display=swap" rel="stylesheet">
<style>
  :root { --bg:#111; --fg:#eee; --muted:#bbb; --card:#1b1b1b; --card2:#222; --teal:#14b8a6; --gold:#f59e0b; }
  * { box-sizing:border-box; }
  html, body { margin:0; padding:0; background:var(--bg); color:var(--fg); font-family:'Roboto', -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  header { position:sticky; top:0; z-index:10; background:linear-gradient(180deg, rgba(0,0,0,.85), rgba(0,0,0,.6)); padding:16px 20px; backdrop-filter: blur(6px); }
  .topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; }
  h1.brand, a.brand {
    margin:0; font-size:30px; letter-spacing:.6px; line-height:1;
    background: linear-gradient(90deg, #22d3ee, #14b8a6);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
    text-shadow: 0 2px 18px rgba(20,184,166,.25);
    font-weight:900; text-decoration:none;
  }
  .tabs { display:flex; gap:10px; margin-left: 14px; }
  .tab { display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border-radius:10px;
         background: rgba(255,255,255,.06); color:#d4d4d4; text-decoration:none; border:1px solid #333;
         font-weight:700; letter-spacing:.2px; }
  .tab.active { background: rgba(20,184,166,.18); color:#fff; border-color: rgba(20,184,166,.5); box-shadow: 0 0 0 2px rgba(20,184,166,.25); }
  .tab.gold { background: rgba(245,158,11,.12); border-color: rgba(245,158,11,.35); color:#fcd34d; }
  .tab.gold.active { background: rgba(245,158,11,.24); color:#fff; border-color: rgba(245,158,11,.55); box-shadow: 0 0 0 2px rgba(245,158,11,.35); }
  .rightstats { color:#9aa3ab; font-size:12px; letter-spacing:.3px; }
  .rightstats .size { color:#6b7280; opacity:.85; }
  .controls { display:flex; gap:12px; margin-top:10px; flex-wrap:wrap; align-items:center; }
  input[type="search"] { background:var(--card2); color:var(--fg); border:1px solid #333; padding:10px 12px; border-radius:10px; min-width:240px; }
  select { background:var(--card2); color:var(--fg); border:1px solid #333; padding:10px 12px; border-radius:10px; }
  main { padding: 18px 20px 60px; }
  .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap:14px; }
  a.card { text-decoration:none; color:inherit; display:flex; flex-direction:column; background: var(--card); border-radius: 14px; overflow: hidden; box-shadow: 0 4px 18px rgba(0,0,0,.35); transition: transform .15s ease, box-shadow .15s ease; position:relative; }
  a.card:hover {
    transform: translateY(-2px);
    box-shadow:
      0 10px 26px rgba(0,0,0,.5),
      0 0 0 3px rgba(20,184,166,.85),
      0 18px 48px rgba(20,184,166,.45),
      0 0 30px rgba(20,184,166,.36);
  }
  .poster-wrap { width:100%; aspect-ratio: 2/3; background:#0f0f0f; display:flex; align-items:center; justify-content:center; }
  .poster { width:100%; height:100%; object-fit:cover; display:block; }
  .meta { padding:10px 10px 12px; display:flex; flex-direction:column; gap:6px; }
  .title { font-weight:700; font-size:14px; line-height:1.25; }
  .sub { font-size:12px; color:var(--muted); }
  .overview { font-size:12px; color:var(--muted); white-space:pre-wrap; }
  .empty { color:#999; text-align:center; padding:40px 0; }
  footer { color:#666; text-align:center; padding:16px; font-size:12px; }
  .badge { display:inline-block; padding:2px 6px; border-radius:6px; font-size:10px; background:#1f3e74; color:#b9d6ff; margin-left:8px; vertical-align:middle; }
  .badge-new { background: linear-gradient(180deg, #f59e0b, #d97706); color:#111; border:1px solid rgba(245,158,11,.45); box-shadow: 0 6px 22px rgba(245,158,11,.15), 0 0 0 2px rgba(245,158,11,.15) inset; }
  .section-title { margin:18px 2px 10px; font-size:30px; font-weight:900; letter-spacing:.3px; color:#fcd34d;
                   text-shadow: 0 0 18px rgba(245,158,11,.4), 0 4px 24px rgba(20,184,166,.25); }
  .divider.strong { height:3px; margin:28px 0 18px;
                    background: linear-gradient(90deg, rgba(34,211,238,.6), rgba(20,184,166,.6), rgba(245,158,11,.45));
                    box-shadow: 0 2px 18px rgba(20,184,166,.3), 0 0 22px rgba(245,158,11,.25); border-radius:2px; }

  .locked-poster { width:280px; height:420px; background:#0f0f0f; border-radius:14px; overflow:hidden; box-shadow: 0 6px 24px rgba(0,0,0,.45); align-self:start; }
  .locked-poster img { width:100%; height:100%; object-fit:cover; display:block; image-rendering:auto; }

  /* New page condensed shows list */
  ul.ep-list { list-style:none; padding:0; margin:8px 0 0; font-size:12px; color:#cbd5e1; }
  ul.ep-list li { padding:2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  ul.ep-list li.more { color:#9aa3ab; letter-spacing:.5px; }
</style>
"""

# ====== TEMPLATES ======
def header_nav(active: str):
    def tab(href, text, key, gold=False):
        cls = "tab gold active" if gold and active==key else "tab gold" if gold else "tab active" if active==key else "tab"
        return f'<a class="{cls}" href="{href}">{text}</a>'
    return f"""
    <div style="display:flex; align-items:center; gap:12px;">
      <a class="brand" href="/">My Local Cinema</a>
      <nav class="tabs">
        {tab("/", "New", "new", gold=True)}
        {tab("/movies", "Movies", "movies")}
        {tab("/shows", "Shows", "shows")}
        {tab("/standup", "Standup", "standup")}
        {tab("/documentary", "Documentary", "docs")}
      </nav>
    </div>
    """

HOME_TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>My Local Cinema — New</title>""" + HEADER_TOP + """
</head>
<body>
<header>
  <div class="topbar">
    """ + header_nav("new") + """
    <div class="rightstats">New Movies Size <b>__NEW_MOV_SIZE__</b> • New Shows Size <b>__NEW_EPS_SIZE__</b></div>
  </div>
</header>
<main>
  <div class="section-title">New Movies</div>
  <div id="gridMovies" class="grid"></div>

  <div class="divider strong"></div>
  <div class="section-title">New Shows</div>
  <div id="gridShows" class="grid"></div>

  <div class="divider strong"></div>
  <div class="section-title">New Standup</div>
  <div id="gridStandup" class="grid"></div>

  <div class="divider strong"></div>
  <div class="section-title">New Documentary</div>
  <div id="gridDocs" class="grid"></div>

  <div id="empty" class="empty" style="display:none;">Nothing new yet.</div>
</main>
<footer>Built locally. Posters & metadata courtesy of TMDB.</footer>
<script>
  const NEW_MOVIES = __NEW_MOVIES_JSON__;
  const NEW_SHOWS  = __NEW_SHOWS_JSON__;
  const NEW_STAND  = __NEW_STAND_JSON__;
  const NEW_DOCS   = __NEW_DOCS_JSON__;
  function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function mkMovieCard(m){
    const poster=m.poster_url?m.poster_url:'';
    const href = m.href || m.movie_href || '#';
    return `
      <a class="card" href="${href}">
        <div class="poster-wrap">${poster?`<img class="poster" src="${poster}" alt="Poster of ${escapeHtml(m.title)}">`:`<div class="poster" style="display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No Poster</div>`}</div>
        <div class="meta">
          <div class="title">${escapeHtml(m.title)} <span class="badge badge-new">NEW</span></div>
          <div class="sub">${m.year||''}</div>
          <div class="overview">${escapeHtml(m.overview||'')}</div>
        </div>
      </a>`;
  }
  function mkShowCard(s){
    const poster=s.poster_url? s.poster_url:'';
    const href = s.show_href || '#';
    const eps  = Array.isArray(s.latest)? s.latest : [];
    const more = s.has_more ? '<li class="more">…</li>' : '';
    const list = eps.map(e => `<li>${escapeHtml(e.label)}</li>`).join('') + more;
    return `
      <a class="card" href="${href}">
        <div class="poster-wrap">${poster?`<img class="poster" src="${poster}" alt="Poster of ${escapeHtml(s.show_title)}">`:`<div class="poster" style="display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No Poster</div>`}</div>
        <div class="meta">
          <div class="title">${escapeHtml(s.show_title)} <span class="badge badge-new">NEW</span></div>
          <div class="sub">${s.first_year||''}</div>
          <ul class="ep-list">${list}</ul>
        </div>
      </a>`;
  }
  function render(){
    const gm=document.getElementById('gridMovies'),
          gs=document.getElementById('gridShows'),
          gst=document.getElementById('gridStandup'),
          gd=document.getElementById('gridDocs'),
          empty=document.getElementById('empty');
    gm.innerHTML=''; gs.innerHTML=''; gst.innerHTML=''; gd.innerHTML='';
    NEW_MOVIES.forEach(m=>gm.insertAdjacentHTML('beforeend', mkMovieCard(m)));
    NEW_SHOWS.forEach(s=>gs.insertAdjacentHTML('beforeend', mkShowCard(s)));
    NEW_STAND.forEach(m=>gst.insertAdjacentHTML('beforeend', mkMovieCard(m)));
    NEW_DOCS.forEach(m=>gd.insertAdjacentHTML('beforeend', mkMovieCard(m)));
    empty.style.display = (NEW_MOVIES.length || NEW_SHOWS.length || NEW_STAND.length || NEW_DOCS.length) ? 'none' : 'block';
  }
  render();
</script>
</body></html>
"""

def build_index_template(page_key: str, title: str):
    top = f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>My Local Cinema — {title}</title>{HEADER_TOP}</head><body>
<header><div class="topbar">{header_nav(page_key)}
  <div class="rightstats">__RIGHTSTATS__</div>
</div>__CONTROLS__</header><main>
  <div id="grid" class="grid"></div><div id="empty" class="empty" style="display:none;">No matches.</div>
</main><footer>Built locally. Posters & metadata courtesy of TMDB.</footer>"""
    if page_key == "shows":
        controls = """
  <div class="controls">
    <input id="q" type="search" placeholder="Search shows…"/>
    <select id="sort"><option value="title">Sort by Title</option><option value="year">Sort by First Air Year</option><option value="genre">Sort by Genre</option></select>
    <label for="genre">Genre:</label><select id="genre"><option value="all">All</option></select>
  </div>"""
        right = "Shows <b>__SHOWS_COUNT__</b> • Episodes <b>__EPISODES_COUNT__</b> <span class='size'>(__SHOWS_SIZE__)</span>"
    else:
        controls = """
  <div class="controls">
    <input id="q" type="search" placeholder="Search…"/>
    <select id="sort"><option value="title">Sort by Title</option><option value="year">Sort by Year</option><option value="genre">Sort by Genre</option></select>
    <label for="genre">Genre:</label><select id="genre"><option value="all">All</option></select>
    <label for="arch">Archived:</label><select id="arch"><option value="all">All</option><option value="active">Hide Archived</option><option value="archived">Only Archived</option></select>
  </div>"""
        right = "Active <b>__ACTIVE_COUNT__</b> <span class='size'>(__ACTIVE_SIZE__)</span> • Archived <b>__ARCH_COUNT__</b> <span class='size'>(__ARCH_SIZE__)</span> • Total <b>__TOTAL_COUNT__</b> <span class='size'>(__TOTAL_SIZE__)</span>"
    return top.replace("__CONTROLS__", controls).replace("__RIGHTSTATS__", right) + """
<script>
  const DATA = __JSON__;
  function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function mkCard(m){
    const poster=m.poster_url?m.poster_url:'';
    const href = m.href || '#';
    const badges = (m.archived?'<span class="badge">ARCHIVED</span>':'') + (m.is_new?'<span class="badge badge-new">NEW</span>':'');
    const sub = (m.year||'') + ((m.genres&&m.genres.length)?' • '+escapeHtml(m.genres.join(', ')):'');
    return `
      <a class="card${m.archived?' archived':''}" href="${href}">
        <div class="poster-wrap">${poster?`<img class="poster" src="${poster}" alt="Poster of ${escapeHtml(m.title)}">`:`<div class="poster" style="display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No Poster</div>`}</div>
        <div class="meta">
          <div class="title">${escapeHtml(m.title)} ${badges}</div>
          <div class="sub">${sub}</div>
          <div class="overview">${escapeHtml(m.overview||'')}</div>
        </div>
      </a>`;
  }
  const GENRES = Array.from(new Set(DATA.flatMap(m => Array.isArray(m.genres) ? m.genres : []))).sort((a,b)=>a.localeCompare(b));
  const gsel = document.getElementById('genre'); if (gsel){ GENRES.forEach(g=>{const o=document.createElement('option');o.value=g;o.textContent=g;gsel.appendChild(o);}); }
  let state={q:'',sort:'title',genre:'all',arch:'all'};
  function render(){
    const grid=document.getElementById('grid'), empty=document.getElementById('empty'); grid.innerHTML='';
    let list=DATA.slice();
    const q=state.q.trim().toLowerCase();
    if(q){ list=list.filter(m=>(m.title||'').toLowerCase().includes(q) || String(m.year||'').includes(q)); }
    if(gsel && state.genre!=='all'){ list=list.filter(m=>(m.genres||[]).includes(state.genre)); }
    if(document.getElementById('arch')){
      if(state.arch==='active') list=list.filter(m=>!m.archived);
      if(state.arch==='archived') list=list.filter(m=>m.archived);
    }
    if(state.sort==='year'){ list.sort((a,b)=>(b.year||0)-(a.year||0) || a.title.localeCompare(b.title)); }
    else if(state.sort==='genre'){ const g0=m=>((m.genres||[])[0]||'').toLowerCase(); list.sort((a,b)=>{const A=g0(a),B=g0(b); return A===B? a.title.localeCompare(b.title):(A<B?-1:1);}); }
    else { list.sort((a,b)=>a.title.localeCompare(b.title)); }
    list.forEach(m=>grid.insertAdjacentHTML('beforeend', mkCard(m)));
    empty.style.display=list.length?'none':'block';
  }
  const qi=document.getElementById('q'); if(qi) qi.addEventListener('input',e=>{state.q=e.target.value;render();});
  const si=document.getElementById('sort'); if(si) si.addEventListener('change',e=>{state.sort=e.target.value;render();});
  const ai=document.getElementById('arch'); if(ai) ai.addEventListener('change',e=>{state.arch=e.target.value;render();});
  if(gsel) gsel.addEventListener('change',e=>{state.genre=e.target.value;render();});
  render();
</script>
</body></html>
"""

def detail_template(active_tab_key: str):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<title>Details — __TITLE__</title>{HEADER_TOP}
<style>
  body {{
    min-height:100vh;
    background:
      linear-gradient(180deg, rgba(0,0,0,.75) 0%, rgba(0,0,0,.85) 40%, rgba(0,0,0,.95) 100%),
      url('__BACKDROP__') center / cover fixed no-repeat, #000;
  }}
  main {{ padding:26px 20px 30px; max-width:1040px; margin:0 auto; }}
  .wrap {{ display:grid; grid-template-columns: 280px 1fr; gap:22px; align-items:start; }}
  h1 {{ margin:0 0 6px; font-size:32px; line-height:1.15; }}
  .sub {{ color:var(--muted); margin-bottom:14px; font-size:14px; }}
  .badge {{ display:inline-block; padding:2px 6px; border-radius:6px; font-size:10px; background:#1f3e74; color:#b9d6ff; margin-left:8px; vertical-align:middle; }}
  .meta-row {{ display:flex; flex-wrap:wrap; gap:12px 18px; margin:8px 0 16px; font-size:14px; color:#ddd;}}
  .chip {{ background:rgba(255,255,255,.08); border:1px solid #444; padding:6px 10px; border-radius:999px; }}
  .section {{ margin-top:16px; }}
  .label {{ font-size:12px; color:#aaa; margin-bottom:6px; }}
  .cast {{ display:flex; flex-wrap:wrap; gap:8px; font-size:13px; color:#ddd; }}
  .actions {{ margin-top:14px; display:flex; gap:10px; }}
  .btn {{ display:inline-flex; align-items:center; gap:8px; padding:10px 14px; background:#fff; color:#000; text-decoration:none; border-radius:10px; font-weight:700; border:1px solid #ddd; }}
  .icon {{ width:16px; height:16px; display:inline-block; }}
  .fileinfo {{ margin-top:10px; background: rgba(20,184,166,.08); border:1px solid rgba(20,184,166,.35);
              border-radius:12px; padding:10px 12px; box-shadow: 0 0 0 2px rgba(20,184,166,.15), 0 16px 36px rgba(20,184,166,.20);
              display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .fileinfo .fn {{ font-weight:700; }}
  .fileinfo .fs {{ color:#9aa3ab; }}
</style>
</head><body>
<header><div class="topbar">{header_nav(active_tab_key)}<div></div></div></header>
<main>
  <div class="wrap">
    <div class="locked-poster">__POSTER_HTML__</div>
    <div class="info">
      <h1>__TITLE____ARCHIVED_BADGE__</h1>
      <div class="sub">__YEAR____SUBSEP____TAGLINE__</div>
      <div class="meta-row">
        <div class="chip">Rating: __CERT__</div>
        <div class="chip">Runtime: __RUNTIME__</div>
        <div class="chip">User Score: __VOTE__/10</div>
      </div>
      <div class="section">
        <div class="label">Genres</div><div class="cast">__GENRES__</div>
      </div>
      <div class="section"><div class="label">Overview</div>
        <p style="white-space:pre-wrap; line-height:1.5; margin:6px 0 0;">__OVERVIEW__</p>
      </div>
      <div class="fileinfo">
        <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
        <div class="fn">__FILENAME__</div><div class="fs">(__FILESIZE__)</div>
      </div>
      <div class="actions" style="margin-top:14px;">
        <a class="btn" href="__PLAY_HREF__"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>Play</a>
      </div>
    </div>
  </div>
</main></body></html>
"""

SHOW_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"/><title>Show — __TITLE__</title>""" + HEADER_TOP + """
<style>
  body { min-height:100vh;
    background:
      linear-gradient(180deg, rgba(0,0,0,.75) 0%, rgba(0,0,0,.85) 40%, rgba(0,0,0,.95) 100%),
      url('__BACKDROP__') center / cover fixed no-repeat, #000; }
  main { padding:26px 20px 30px; max-width:1100px; margin:0 auto; }
  .wrap { display:grid; grid-template-columns: 280px 1fr; gap:22px; align-items:start; }
  h1 { margin:0 0 6px; font-size:32px; line-height:1.15; }
  .sub { color:var(--muted); margin-bottom:14px; font-size:14px; }
  .meta-row { display:flex; flex-wrap:wrap; gap:12px 18px; margin:8px 0 16px; font-size:14px; color:#ddd;}
  .chip { background:rgba(255,255,255,.08); border:1px solid #444; padding:6px 10px; border-radius:999px; }
  .section { margin-top:16px; }
  .label { font-size:12px; color:#aaa; margin-bottom:6px; }
  .cast { display:flex; flex-wrap:wrap; gap:8px; font-size:13px; color:#ddd; }
  .season { margin-top:16px; background:rgba(255,255,255,.06); border:1px solid #333; border-radius:12px; padding:12px; }
  .season h2 { margin:0 0 12px; font-size:18px; letter-spacing:.3px; }
  .ep { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:8px 10px; border-radius:10px; }
  .ep:hover { background:rgba(20,184,166,.08); box-shadow: inset 0 0 0 1px rgba(20,184,166,.3); }
  .ep .info { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .btn { display:inline-flex; align-items:center; gap:8px; padding:8px 12px; background:#fff; color:#000; text-decoration:none; border-radius:10px; font-weight:700; border:1px solid #ddd; }
  .icon { width:16px; height:16px; display:inline-block; }
  .filesize { color:#9aa3ab; font-size:12px; }
  .badge { display:inline-block; padding:2px 6px; border-radius:6px; font-size:10px; background:#1f3e74; color:#b9d6ff; vertical-align:middle; }
  .badge-new { background: linear-gradient(180deg, #f59e0b, #d97706); color:#111; border:1px solid rgba(245,158,11,.45); box-shadow: 0 6px 22px rgba(245,158,11,.15), 0 0 0 2px rgba(245,158,11,.15) inset; margin-right:8px; }
  .locked-poster { width:280px; height:420px; background:#0f0f0f; border-radius:14px; overflow:hidden; box-shadow: 0 6px 24px rgba(0,0,0,.45); align-self:start; }
  .locked-poster img { width:100%; height:100%; object-fit:cover; display:block; image-rendering:auto; }
</style>
</head>
<body>
<header><div class="topbar">""" + header_nav("shows") + """<div></div></div></header>
<main>
  <div class="wrap">
    <div class="locked-poster">__POSTER_HTML__</div>
    <div class="info">
      <h1>__TITLE__</h1>
      <div class="sub">__FIRSTYEAR____SUBSEP____TAGLINE__</div>
      <div class="meta-row">
        <div class="chip">User Score: __VOTE__/10</div>
        <div class="chip">Genres: __GENRES__</div>
        <div class="chip">Top Cast: __CAST__</div>
      </div>
      <div class="section"><div class="label">Overview</div>
        <p style="white-space:pre-wrap; line-height:1.5; margin:6px 0 0;">__OVERVIEW__</p>
      </div>
      __SEASONS_HTML__
    </div>
  </div>
</main>
</body></html>
"""

# ====== BUILD SITE ======
def build_site(movies_root: str, shows_root: str, standup_root: str, docs_root: str):
    site_dir = os.path.join(movies_root, OUTPUT_DIR_NAME)
    os.makedirs(site_dir, exist_ok=True)

    # ---- Movies ----
    movies = discover_category(movies_root, id_prefix="m")
    movies = enrich_movies(movies, site_dir)
    for m in movies:
        m["href"] = f"/movie?id={urllib.parse.quote(m['id'])}" if m.get("abs_path") else ""

    # ---- Standup ----
    standup = discover_category(standup_root, id_prefix="s")
    standup = enrich_movies(standup, site_dir)
    for it in standup:
        it["href"] = f"/standup_item?id={urllib.parse.quote(it['id'])}" if it.get("abs_path") else ""

    # ---- Documentary ----
    docs = discover_category(docs_root, id_prefix="d")
    docs = enrich_movies(docs, site_dir)
    for it in docs:
        it["href"] = f"/doc_item?id={urllib.parse.quote(it['id'])}" if it.get("abs_path") else ""

    # ---- Shows ----
    shows_list, shows_meta, episodes_index = discover_shows(shows_root)
    shows_list, shows_meta = enrich_shows(shows_list, shows_meta, site_dir)
    shows_meta = fill_episode_titles_from_tmdb(shows_meta, site_dir)

    # Rebuild episodes index
    episodes_index = {}
    for sid, meta in shows_meta.items():
        for skey, eps in meta.get("seasons", {}).items():
            for ep in eps:
                episodes_index[ep["eid"]] = ep["file"]

    # ---- "NEW" Home ----
    newest_movies = sorted([m for m in movies if m.get("abs_path")], key=lambda x: x.get("mtime", 0.0), reverse=True)[:16]
    new_movie_ids = {m["id"] for m in newest_movies}
    new_movies_bytes = sum(safe_size(m["abs_path"]) for m in newest_movies)

    # Condensed shows (by show, list latest 5 per show)
    eps_flat = []
    for sid, meta in shows_meta.items():
        for skey, eps in meta.get("seasons", {}).items():
            for ep in eps:
                eps_flat.append({
                    "sid": sid, "eid": ep["eid"], "show_title": meta.get("title",""),
                    "poster_url": meta.get("poster_url",""), "overview": meta.get("overview",""),
                    "show_href": f"/show?id={urllib.parse.quote(sid)}",
                    "s": int(skey), "e": ep.get("e"), "title": ep.get("title",""),
                    "mtime": ep.get("mtime", 0.0), "size": ep.get("size", 0), "first_year": meta.get("first_year")
                })
    by_show = {}
    for e in eps_flat: by_show.setdefault(e["sid"], []).append(e)
    for sid in by_show: by_show[sid].sort(key=lambda x: x["mtime"], reverse=True)
    ordered_shows = sorted(by_show.keys(), key=lambda sid: by_show[sid][0]["mtime"] if by_show[sid] else 0.0, reverse=True)[:16]

    new_shows_payload, included_ep_eids, new_shows_bytes = [], set(), 0
    for sid in ordered_shows:
        episodes = by_show[sid]
        latest5 = episodes[:5]
        for e in latest5:
            included_ep_eids.add(e["eid"])
            new_shows_bytes += e.get("size", 0)
        has_more = len(episodes) > 5
        meta0 = episodes[0] if episodes else {"show_title":"", "poster_url":"", "overview":"", "show_href":"", "first_year":""}
        new_shows_payload.append({
            "sid": sid, "show_title": meta0["show_title"], "poster_url": meta0["poster_url"],
            "overview": meta0["overview"], "show_href": meta0["show_href"], "first_year": meta0.get("first_year"),
            "has_more": has_more, "latest": [{
                "s": e["s"], "e": e["e"], "title": e.get("title",""),
                "label": f"S{e['s']:02d}E{e['e']:02d}" + (f" — {e['title']}" if e.get('title') else "")
            } for e in latest5]
        })

    # Mark "is_new"
    for m in movies:  m["is_new"]  = m["id"] in new_movie_ids
    for s in shows_list: s["is_new"] = s["id"] in set(ordered_shows)
    for sid, meta in shows_meta.items():
        for skey, eps in meta.get("seasons", {}).items():
            for ep in eps: ep["is_new"] = ep["eid"] in included_ep_eids

    # New Standup / New Docs (top 16 by mtime)
    newest_stand = sorted([x for x in standup if x.get("abs_path")], key=lambda x: x.get("mtime", 0.0), reverse=True)[:16]
    newest_docs  = sorted([x for x in docs if x.get("abs_path")], key=lambda x: x.get("mtime", 0.0), reverse=True)[:16]
    for it in standup: it["is_new"] = it["id"] in {m["id"] for m in newest_stand}
    for it in docs:    it["is_new"] = it["id"] in {m["id"] for m in newest_docs}

    # ---- Persist ----
    site_dir_json = lambda name: os.path.join(site_dir, name)
    def dump_json(name, obj):
        with open(site_dir_json(name), "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=2)

    dump_json("movies_index.json", {m["id"]: m["abs_path"] for m in movies if m["abs_path"]})
    dump_json("movies_meta.json", {
        m["id"]: {"title": m["title"], "year": m["year"], "poster_url": m["poster_url"], "overview": m["overview"],
                  "archived": m.get("archived", False), "genres": m.get("genres", []), "runtime": m.get("runtime"),
                  "vote": m.get("vote"), "certification": m.get("certification"), "cast": m.get("cast", []),
                  "backdrop_url": m.get("backdrop_url", ""), "tagline": m.get("tagline", ""), "mtime": m.get("mtime", 0),
                  "is_new": m.get("is_new", False)} for m in movies
    })
    dump_json("standup_index.json", {m["id"]: m["abs_path"] for m in standup if m["abs_path"]})
    dump_json("standup_meta.json", {
        m["id"]: {"title": m["title"], "year": m["year"], "poster_url": m["poster_url"], "overview": m["overview"],
                  "archived": m.get("archived", False), "genres": m.get("genres", []), "runtime": m.get("runtime"),
                  "vote": m.get("vote"), "certification": m.get("certification"), "cast": m.get("cast", []),
                  "backdrop_url": m.get("backdrop_url", ""), "tagline": m.get("tagline", ""), "mtime": m.get("mtime", 0),
                  "is_new": m.get("is_new", False)} for m in standup
    })
    dump_json("docs_index.json", {m["id"]: m["abs_path"] for m in docs if m["abs_path"]})
    dump_json("docs_meta.json", {
        m["id"]: {"title": m["title"], "year": m["year"], "poster_url": m["poster_url"], "overview": m["overview"],
                  "archived": m.get("archived", False), "genres": m.get("genres", []), "runtime": m.get("runtime"),
                  "vote": m.get("vote"), "certification": m.get("certification"), "cast": m.get("cast", []),
                  "backdrop_url": m.get("backdrop_url", ""), "tagline": m.get("tagline", ""), "mtime": m.get("mtime", 0),
                  "is_new": m.get("is_new", False)} for m in docs
    })
    dump_json("shows_meta.json", shows_meta)
    dump_json("episodes_index.json", episodes_index)

    # ---- Render pages ----
    def sizes_for_category(root):
        active_bytes = folder_size(root, exclude_names={OUTPUT_DIR_NAME, ARCHIVED_DIR_NAME})
        archived_bytes = folder_size(os.path.join(root, ARCHIVED_DIR_NAME), exclude_names={OUTPUT_DIR_NAME})
        total_bytes = active_bytes + archived_bytes
        return active_bytes, archived_bytes, total_bytes

    def render_movie_like(index_name, page_key, title, items, root):
        active = [m for m in items if m.get("abs_path") and not m.get("archived")]
        archived = [m for m in items if m.get("abs_path") and m.get("archived")]
        a, b, t = sizes_for_category(root)
        tpl = build_index_template(page_key, title)
        html = (tpl
            .replace("__JSON__", json.dumps([{
                "id": m["id"], "title": m["title"], "year": m["year"], "poster_url": m["poster_url"],
                "overview": m.get("overview",""), "genres": m.get("genres", []),
                "href": m.get("href",""), "archived": bool(m.get("archived", False)),
                "is_new": bool(m.get("is_new", False))
            } for m in items], ensure_ascii=False))
            .replace("__ACTIVE_COUNT__", str(len(active)))
            .replace("__ARCH_COUNT__", str(len(archived)))
            .replace("__TOTAL_COUNT__", str(len(active)+len(archived)))
            .replace("__ACTIVE_SIZE__", format_size_lower(a))
            .replace("__ARCH_SIZE__", format_size_lower(b))
            .replace("__TOTAL_SIZE__", format_size_lower(t))
        )
        with open(os.path.join(site_dir, index_name), "w", encoding="utf-8") as f: f.write(html)

    render_movie_like("movies.html", "movies", "Movies", movies, movies_root)
    render_movie_like("standup.html", "standup", "Standup", standup, standup_root)
    render_movie_like("documentary.html", "docs", "Documentary", docs, docs_root)

    shows_bytes = folder_size(shows_root, exclude_names={OUTPUT_DIR_NAME})
    episodes_count = sum(len(eps) for s in shows_meta.values() for eps in s["seasons"].values())
    shows_list_payload = []
    for sid, meta in shows_meta.items():
        shows_list_payload.append({
            "id": sid, "title": meta.get("title",""), "poster_url": meta.get("poster_url",""),
            "overview": meta.get("overview",""), "first_year": meta.get("first_year"),
            "genres": meta.get("genres", []), "href": f"/show?id={urllib.parse.quote(sid)}",
            "is_new": sid in set(ordered_shows)
        })
    shows_tpl = build_index_template("shows", "Shows") \
        .replace("__JSON__", json.dumps(shows_list_payload, ensure_ascii=False)) \
        .replace("__SHOWS_COUNT__", str(len(shows_list_payload))) \
        .replace("__EPISODES_COUNT__", str(episodes_count)) \
        .replace("__SHOWS_SIZE__", format_size_lower(shows_bytes))
    with open(os.path.join(site_dir, "shows.html"), "w", encoding="utf-8") as f: f.write(shows_tpl)

    # Home ("New")
    new_movies_payload = [{
        "title": m["title"], "year": m["year"], "poster_url": m["poster_url"],
        "overview": m.get("overview",""), "href": m.get("href","")
    } for m in newest_movies]
    new_stand_payload = [{
        "title": m["title"], "year": m["year"], "poster_url": m["poster_url"],
        "overview": m.get("overview",""), "href": m.get("href","")
    } for m in newest_stand]
    new_docs_payload = [{
        "title": m["title"], "year": m["year"], "poster_url": m["poster_url"],
        "overview": m.get("overview",""), "href": m.get("href","")
    } for m in newest_docs]

    home_html = HOME_TEMPLATE \
        .replace("__NEW_MOVIES_JSON__", json.dumps(new_movies_payload, ensure_ascii=False)) \
        .replace("__NEW_SHOWS_JSON__", json.dumps(new_shows_payload, ensure_ascii=False)) \
        .replace("__NEW_STAND_JSON__", json.dumps(new_stand_payload, ensure_ascii=False)) \
        .replace("__NEW_DOCS_JSON__", json.dumps(new_docs_payload, ensure_ascii=False)) \
        .replace("__NEW_MOV_SIZE__", format_size_lower(new_movies_bytes)) \
        .replace("__NEW_EPS_SIZE__", format_size_lower(new_shows_bytes))
    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f: f.write(home_html)

    print(f"Built site at: {os.path.join(site_dir, 'index.html')} (Home) + movies.html + shows.html + standup.html + documentary.html")
    return site_dir

# ====== SERVER ======
class CinemaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, movies_root=None, shows_root=None, standup_root=None, docs_root=None, site_dir=None, **kwargs):
        self._movies_root  = movies_root
        self._shows_root   = shows_root
        self._standup_root = standup_root
        self._docs_root    = docs_root
        self._site_dir     = site_dir
        super().__init__(*args, directory=site_dir, **kwargs)

    def do_GET(self):
        p = self.path
        if p == "/movies" or p.startswith("/movies?"): return self.serve_file("movies.html")
        if p == "/shows" or p.startswith("/shows?"): return self.erve_file("shows.html") if False else self.serve_file("shows.html")
        if p == "/standup" or p.startswith("/standup?"): return self.serve_file("standup.html")
        if p == "/documentary" or p.startswith("/documentary?"): return self.serve_file("documentary.html")
        if p.startswith("/movie"):        return self.render_media_page("movies", "movies_index.json", "movies_meta.json", "/play_movie?id=")
        if p.startswith("/standup_item"): return self.render_media_page("standup", "standup_index.json", "standup_meta.json", "/play_standup?id=")
        if p.startswith("/doc_item"):     return self.render_media_page("docs", "docs_index.json", "docs_meta.json", "/play_doc?id=")
        if p.startswith("/play_movie?id="):   return self.launch_and_render("movies", "movies_index.json", "movies_meta.json")
        if p.startswith("/play_standup?id="): return self.launch_and_render("standup", "standup_index.json", "standup_meta.json")
        if p.startswith("/play_doc?id="):     return self.launch_and_render("docs", "docs_index.json", "docs_meta.json")
        if p.startswith("/show"):         return self.render_show_page()
        if p.startswith("/play_ep"):      return self.launch_episode()
        return super().do_GET()

    def serve_file(self, name):
        p = os.path.join(self._site_dir, name)
        if not os.path.isfile(p): self.send_error(404, "Not found"); return
        with open(p, "rb") as f: data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if name.endswith(".html") else "application/octet-stream")
        self.end_headers()
        self.wfile.write(data)

    def render_media_page(self, active_key, idx_json, meta_json, play_prefix):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        mid = qs.get("id", [""])[0]

        mapping = load_cache(os.path.join(self._site_dir, idx_json))
        meta_all = load_cache(os.path.join(self._site_dir, meta_json))

        filepath = mapping.get(mid, "")
        meta = meta_all.get(mid, {})
        title = meta.get("title","Unknown Title")
        year  = meta.get("year","")
        poster_url = meta.get("poster_url","")
        overview   = meta.get("overview","")
        archived   = bool(meta.get("archived", False))
        genres     = meta.get("genres",[])
        runtime    = meta.get("runtime")
        vote       = meta.get("vote")
        cert       = meta.get("certification") or "NR"
        cast       = meta.get("cast",[])
        backdrop   = meta.get("backdrop_url","")
        tagline    = meta.get("tagline","")

        poster_html = f'<img src="{html_attr(poster_url)}" alt="Poster">' if poster_url else '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#666;">No Poster</div>'
        archived_badge = ' <span class="badge">ARCHIVED</span>' if archived else ''
        genres_html = ", ".join(html_text(g) for g in genres) if genres else "—"
        runtime_txt = minutes_to_hm(runtime) or "—"
        vote_txt    = f"{vote:.1f}" if isinstance(vote,(int,float)) else "—"
        tagline_txt = tagline or ""
        subsep      = " • " if tagline_txt else ""
        filename = os.path.basename(filepath) if filepath else "—"
        filesize_txt = format_size_lower(safe_size(filepath)) if filepath and os.path.isfile(filepath) else "—"

        page = detail_template(active_key) \
            .replace("__TITLE__", html_text(title)) \
            .replace("__YEAR__", html_text(str(year or ""))) \
            .replace("__POSTER_HTML__", poster_html) \
            .replace("__OVERVIEW__", html_text(overview or "")) \
            .replace("__ARCHIVED_BADGE__", archived_badge) \
            .replace("__GENRES__", genres_html or "—") \
            .replace("__RUNTIME__", html_text(runtime_txt)) \
            .replace("__VOTE__", html_text(vote_txt)) \
            .replace("__CERT__", html_text(cert)) \
            .replace("__TAGLINE__", html_text(tagline_txt)) \
            .replace("__SUBSEP__", subsep) \
            .replace("__BACKDROP__", html_attr(backdrop)) \
            .replace("__FILENAME__", html_text(filename)) \
            .replace("__FILESIZE__", html_text(filesize_txt)) \
            .replace("__PLAY_HREF__", f"{play_prefix}{urllib.parse.quote(mid)}")

        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def launch_and_render(self, active_key, idx_json, meta_json):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        mid = qs.get("id", [""])[0]
        mapping = load_cache(os.path.join(self._site_dir, idx_json))
        filepath = mapping.get(mid, "")
        if filepath and os.path.isfile(filepath):
            base = {"movies": self._movies_root, "standup": self._standup_root, "docs": self._docs_root}[active_key]
            self._launch(filepath, base_root=base)
        path_prefix = {"movies": "/movie", "standup": "/standup_item", "docs": "/doc_item"}[active_key]
        self.path = f"{path_prefix}?id={urllib.parse.quote(mid)}"
        return self.render_media_page(active_key, idx_json, meta_json, f"/play_{'movie' if active_key=='movies' else 'standup' if active_key=='standup' else 'doc'}?id=")

    # ----- Shows -----
    def render_show_page(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        sid = qs.get("id",[""])[0]

        shows_meta = load_cache(os.path.join(self._site_dir, "shows_meta.json"))
        meta = shows_meta.get(sid, {})
        if not meta: self.send_error(404, "Show not found"); return

        title = meta.get("title","Unknown Show")
        poster_url = meta.get("poster_url","")
        overview   = meta.get("overview","")
        genres     = meta.get("genres",[])
        vote       = meta.get("vote")
        cast       = meta.get("cast",[])
        backdrop   = meta.get("backdrop_url","")
        tagline    = meta.get("tagline","")
        first_year = meta.get("first_year")

        poster_html = f'<img src="{html_attr(poster_url)}" alt="Poster">' if poster_url else '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#666;">No Poster</div>'
        genres_html = ", ".join(html_text(g) for g in genres) if genres else "—"
        cast_html   = ", ".join(html_text(c) for c in cast) if cast else "—"
        vote_txt    = f"{vote:.1f}" if isinstance(vote,(int,float)) else "—"
        tagline_txt = tagline or ""
        subsep      = " • " if tagline_txt else ""
        fy_txt      = str(first_year) if first_year else ""

        seasons = meta.get("seasons", {})
        season_nums = sorted((int(k) for k in seasons.keys()))
        blocks = []
        for snum in season_nums:
            s_key = str(snum)
            eps = seasons.get(s_key, [])
            items = []
            for ep in eps:
                label = f"S{snum:02d}E{ep['e']:02d}" + (f" — {html_text(ep.get('title',''))}" if ep.get("title") else "")
                size_txt = format_size_lower(ep.get("size",0))
                new_badge = '<span class="badge badge-new">NEW</span>' if ep.get("is_new") else ''
                items.append(f"""
                  <div class="ep">
                    <div class="info"><div>{label}</div><div class="filesize">({size_txt})</div></div>
                    <div style="display:flex; align-items:center; gap:8px;">
                      {new_badge}
                      <a class="btn" href="/play_ep?id={urllib.parse.quote(ep['eid'])}">
                        <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>Play
                      </a>
                    </div>
                  </div>
                """)
            blocks.append(f"<div class='season'><h2>Season {snum}</h2>{''.join(items)}</div>")
        seasons_html = "\n".join(blocks) if blocks else "<div class='section'><div class='label'>No episodes found.</div></div>"

        page = SHOW_PAGE_TEMPLATE \
            .replace("__TITLE__", html_text(title)) \
            .replace("__POSTER_HTML__", poster_html) \
            .replace("__OVERVIEW__", html_text(overview or "")) \
            .replace("__GENRES__", genres_html) \
            .replace("__CAST__", cast_html) \
            .replace("__VOTE__", vote_txt) \
            .replace("__TAGLINE__", html_text(tagline_txt)) \
            .replace("__FIRSTYEAR__", html_text(fy_txt)) \
            .replace("__SUBSEP__", subsep) \
            .replace("__SEASONS_HTML__", seasons_html) \
            .replace("__BACKDROP__", html_attr(backdrop))

        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def launch_episode(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        eid = qs.get("id",[""])[0]
        idx = load_cache(os.path.join(self._site_dir, "episodes_index.json"))
        filepath = idx.get(eid, "")
        if filepath and os.path.isfile(filepath):
            self._launch(filepath, base_root=self._shows_root)
            self.send_response(302)
            self.send_header("Location", self.headers.get("Referer", "/shows"))
            self.end_headers()
            return
        self.send_error(404, "Episode not found")

    def _launch(self, filepath: str, base_root: str):
        try:
            rp = os.path.realpath(filepath)
            base = os.path.realpath(base_root)
            if not rp.startswith(base): return
            if PREFER_VLC and os.path.isdir("/Applications/VLC.app"):
                subprocess.Popen(["open", "-a", "VLC", filepath])
            else:
                subprocess.Popen(["open", filepath])
        except Exception:
            pass

# ====== CLI ======
def serve_site(site_dir: str, movies_root: str, shows_root: str, standup_root: str, docs_root: str, port: int = 8000):
    handler = partial(CinemaHandler,
                      movies_root=movies_root, shows_root=shows_root,
                      standup_root=standup_root, docs_root=docs_root,
                      site_dir=site_dir)
    httpd = HTTPServer(("127.0.0.1", port), handler)
    print(f"Serving {site_dir} at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\nBye.")

def main():
    ap = argparse.ArgumentParser(description="Build/serve a local Netflix-style site for Movies + Shows + Standup + Documentary")
    ap.add_argument("--movies-root",  default=DEFAULT_MOVIES_ROOT,  help="Movies library root")
    ap.add_argument("--shows-root",   default=DEFAULT_SHOWS_ROOT,   help="Shows  library root")
    ap.add_argument("--standup-root", default=DEFAULT_STANDUP_ROOT, help="Standup library root")
    ap.add_argument("--docs-root",    default=DEFAULT_DOCS_ROOT,    help="Documentary library root")
    ap.add_argument("--port", type=int, default=8000, help="Port to serve on")
    ap.add_argument("--serve", action="store_true", help="Run local server after building")
    ap.add_argument("--quiet", action="store_true", help="Reduce TMDB logs")
    args = ap.parse_args()

    global LOG_TMDB
    LOG_TMDB = not args.quiet

    site_dir = build_site(args.movies_root, args.shows_root, args.standup_root, args.docs_root)
    if args.serve:
        serve_site(site_dir, args.movies_root, args.shows_root, args.standup_root, args.docs_root, args.port)
    else:
        print("Open the site:")
        print("  - Home:        " + os.path.join(site_dir, "index.html"))
        print("  - Movies:      " + os.path.join(site_dir, "movies.html"))
        print("  - Shows:       " + os.path.join(site_dir, "shows.html"))
        print("  - Standup:     " + os.path.join(site_dir, "standup.html"))
        print("  - Documentary: " + os.path.join(site_dir, "documentary.html"))

if __name__ == "__main__":
    main()
