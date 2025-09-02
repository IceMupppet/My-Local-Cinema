#!/usr/bin/env python3
import os, re, argparse, sys, shutil

# ===== Defaults =====
ROOT = "/Users/icemuppet/OTHER/SCN/0-INCOMING/SHOWS"   # scan + destination root by default
VIDEO_EXTS = {".mkv",".mp4",".mov",".m4v",".avi",".ts",".m2ts",".wmv",".webm"}

# Known tokens (normalized)
QUALITY = {"2160P","1080P","720P","480P","540P"}
SOURCES = {"WEB-DL","WEB","BLURAY","BRRIP","HDTV","WEBDL","WEBRIP","DVDRIP","DSNP","AMZN","NF","HULU","MAX"}
VCODECS = {"X264","X265","H.264","H264","HEVC","XVID"}
ACODECS = {"AAC","AC3","DDP5.1","DDP5.0","DDP5.2","EAC3","TRUEHD","DTS","PCM","FLAC"}

SxxEyy_RE = re.compile(r"\b[Ss]\s*(\d{1,2})\s*[.\-_ ]*[Ee]\s*(\d{1,2})\b")
FALLBACK_RE = re.compile(r"^\s*(?P<show>.+?)\s*-\s*(?P<num>\d{3,4})(?:\s*-\s*(?P<title>.*?))?\s*$")

def norm_spaces(s: str) -> str:
    s = re.sub(r"[()\[\]{}]", " ", s)
    s = s.replace("_"," ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def dotify(s: str) -> str:
    s = norm_spaces(s).replace(" ", ".")
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"\.-", "-", s)
    s = re.sub(r"-\.", "-", s)
    return s.strip(".")

def normalize_token(tok: str) -> str:
    t = tok.upper().replace(" ", "").replace("_","").replace("-", "")
    if t in {"WEB", "WEBDL", "WEBRIP"}: return "WEB-DL"
    if t in {"BLURAY","BRRIP"}: return "BluRay"
    if t == "HDTV": return "HDTV"
    if t == "AMZN": return "AMZN"
    if t == "NF": return "NF"
    if t in {"H264","H.264"}: return "H.264"
    if t == "X264": return "x264"
    if t == "X265": return "x265"
    if t == "HEVC": return "HEVC"
    if t == "XVID": return "XviD"
    if t in {"AAC","AC3","EAC3","DTS","FLAC"}: return t
    if t.startswith("DDP"): return "DDP5.1"
    if t == "TRUEHD": return "TrueHD"
    if t in QUALITY: return t
    return tok

def split_tokens(text_after_ep: str):
    raw = re.split(r"[.\s_]+", text_after_ep.strip())
    toks = []
    for r in raw:
        if not r: continue
        if r.startswith("-") and len(r) > 1:
            toks.append(r); continue
        toks.append(r)
    return toks

def classify_tokens(tokens):
    groups = {"quality":[], "providers":[], "sources":[], "audio":[], "video":[], "other":[]}
    group_suffix = None
    for tok in tokens:
        if tok.startswith("-") and len(tok) > 1:
            group_suffix = tok; continue
        n = normalize_token(tok); u = n.upper()
        if u in QUALITY:
            groups["quality"].append(n)
        elif u in {"DSNP","AMZN","NF","HULU","MAX"}:
            groups["providers"].append(n)
        elif u in {"WEB-DL","BLURAY","BRRIP","HDTV","DVDRIP"}:
            groups["sources"].append("BluRay" if u in {"BLURAY","BRRIP"} else ("WEB-DL" if u=="WEB-DL" else n))
        elif u in {"AAC","AC3","DDP5.1","EAC3","TRUEHD","DTS","FLAC"}:
            groups["audio"].append(n)
        elif u in {"X264","X265","H.264","HEVC","XVID"} or n in {"x264","x265","XviD"}:
            groups["video"].append(n)
        else:
            groups["other"].append(tok)
    return groups, group_suffix

def compose_name(show, season, episode, ep_title, groups, group_suffix, ext, fallback_used):
    parts = [dotify(show), f"S{int(season):02d}E{int(episode):02d}"]
    if ep_title:
        parts.append(dotify(ep_title))

    # If fallback used and no media tokens, add minimal guess for .avi
    if fallback_used:
        have_media = any(groups[k] for k in ("quality","providers","sources","audio","video"))
        if ext.lower()==".avi" and not have_media:
            if "HDTV" not in groups["sources"]:
                groups["sources"].append("HDTV")
            if "XviD" not in groups["video"]:
                groups["video"].append("XviD")

    def dedup(seq):
        seen=set(); out=[]
        for x in seq:
            if x in seen: continue
            seen.add(x); out.append(x)
        return out

    tail = []
    tail += dedup(groups["quality"])
    tail += dedup(groups["providers"])
    tail += dedup(groups["sources"])
    tail += dedup(groups["audio"])
    tail += dedup(groups["video"])
    if tail:
        parts.append(".".join(tail))

    base = ".".join(parts)
    base = re.sub(r"\.-", "-", base)
    base = re.sub(r"-\.", "-", base)

    if group_suffix and group_suffix != "-":
        base = f"{base}{group_suffix}"

    return f"{base}{ext}"

def already_canonical(name: str) -> bool:
    return bool(re.search(r"\.[Ss]\d{2}[Ee]\d{2}\.", f".{name}."))

def parse_standard(base_no_ext: str):
    s = norm_spaces(base_no_ext)
    group_suffix = None
    m_group = re.search(r"\s(-[A-Za-z0-9]+)\s*$", s)
    if m_group:
        group_suffix = m_group.group(1)
        s = s[:m_group.start()].rstrip()

    m = SxxEyy_RE.search(s)
    if not m: return None
    season = int(m.group(1)); episode = int(m.group(2))
    show = s[:m.start()].strip(" .-_")
    rest = s[m.end():].strip(" .-_")

    tokens = split_tokens(rest)
    title_tokens = []; trailing=[]
    hit_meta=False
    for t in tokens:
        n = normalize_token(t); u = n.upper()
        is_meta = (
            u in QUALITY or
            u in {"WEB-DL","BLURAY","BRRIP","HDTV","DVDRIP"} or
            u in {"DSNP","AMZN","NF","HULU","MAX"} or
            u in {"AAC","AC3","DDP5.1","EAC3","TRUEHD","DTS","FLAC"} or
            u in {"X264","X265","H.264","HEVC","XVID"} or
            t.startswith("-")
        )
        if not hit_meta and not is_meta:
            title_tokens.append(t)
        else:
            hit_meta=True; trailing.append(t)

    ep_title = " ".join(title_tokens).strip()
    groups, suffix = classify_tokens(trailing)
    if group_suffix and not suffix:
        suffix = group_suffix
    return {
        "show": show, "season": season, "episode": episode, "ep_title": ep_title,
        "groups": groups, "group_suffix": suffix, "fallback_used": False
    }

def parse_fallback(base_no_ext: str):
    s = norm_spaces(base_no_ext)
    group_suffix = None
    m_group = re.search(r"\s(-[A-Za-z0-9]+)\s*$", s)
    if m_group:
        group_suffix = m_group.group(1)
        s = s[:m_group.start()].rstrip()

    m = FALLBACK_RE.match(s)
    if not m: return None
    show = m.group("show").strip(" .-_")
    num  = m.group("num")
    title = (m.group("title") or "").strip()

    if len(num)==3:
        season = int(num[0]); episode=int(num[1:])
    elif len(num)==4:
        season = int(num[:2]); episode=int(num[2:])
    else:
        return None

    groups = {"quality":[], "providers":[], "sources":[], "audio":[], "video":[], "other":[]}
    return {
        "show": show, "season": season, "episode": episode, "ep_title": title,
        "groups": groups, "group_suffix": group_suffix, "fallback_used": True
    }

def plan_destination(root_dest: str, info: dict, ext: str, original_fn: str):
    show_folder = dotify(info["show"])
    season_folder = f"S{int(info['season']):02d}"
    dest_dir = os.path.join(root_dest, show_folder, season_folder)
    new_filename = compose_name(
        info["show"], info["season"], info["episode"], info["ep_title"],
        info["groups"], info["group_suffix"], ext, info["fallback_used"]
    )
    return dest_dir, new_filename

def ensure_unique(path: str):
    if not os.path.exists(path): return path
    base, ext = os.path.splitext(path); i=1
    while True:
        cand = f"{base}._{i}{ext}"
        if not os.path.exists(cand): return cand
        i += 1

def plan(path: str, dest_root: str):
    d, fn = os.path.dirname(path), os.path.basename(path)
    base, ext = os.path.splitext(fn)
    if ext.lower() not in VIDEO_EXTS: return None

    # Parse
    parsed = parse_standard(base) or parse_fallback(base)
    if not parsed: return None

    # Destination
    dest_dir, new_name = plan_destination(dest_root, parsed, ext, fn)
    dest_path = os.path.join(dest_dir, new_name)

    # Skip if already perfect (filename + location)
    if os.path.realpath(os.path.join(d, fn)) == os.path.realpath(dest_path):
        return None

    return {
        "src": os.path.join(d, fn),
        "dest_dir": dest_dir,
        "dest": dest_path
    }

def scan_move_and_rename(scan_root: str, dest_root: str, dry_run: bool):
    checked = 0; moved = 0
    for dirpath, _, filenames in os.walk(scan_root):
        for fname in filenames:
            checked += 1
            src = os.path.join(dirpath, fname)
            p = plan(src, dest_root)
            if not p: continue
            os.makedirs(p["dest_dir"], exist_ok=True)
            dst = ensure_unique(p["dest"])
            rel_src = os.path.relpath(src, scan_root)
            rel_dst = os.path.relpath(dst, dest_root)
            print(f"[MOVE] {rel_src}  ->  {rel_dst}")
            if not dry_run:
                try:
                    shutil.move(src, dst)
                    moved += 1
                except Exception as e:
                    print(f"   !! Failed to move: {e}", file=sys.stderr)
    print(f"\nDone. Checked {checked} files. Moved/Renamed {moved}.\n")

def main():
    ap = argparse.ArgumentParser(description="Rename and organize TV files into SHOWS/Show.Name/Sxx/")
    ap.add_argument("--root", default=ROOT, help="Scan root (default also used as destination root)")
    ap.add_argument("--dest-root", default=None, help="Destination root (defaults to --root)")
    ap.add_argument("--dry-run", action="store_true", help="Preview without moving/renaming")
    args = ap.parse_args()
    dest_root = args.dest_root or args.root
    scan_move_and_rename(args.root, dest_root, args.dry_run)

if __name__ == "__main__":
    main()
