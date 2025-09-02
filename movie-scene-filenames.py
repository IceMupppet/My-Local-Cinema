#!/usr/bin/env python3
import os
import re
import shutil
import unicodedata
import traceback

# >>>> Your movies/shows folder <<<<
DIRECTORY = "/Users/icemuppet/OTHER/SCN/0-INCOMING/MOVIES"

# Preview mode (no renames/moves) if True
DRY_RUN = False

# If True, ALWAYS treat the last token as uploader/group.
# If False, only treat the last token as uploader if it is NOT a known tag.
ALWAYS_TAKE_LAST_AS_UPLOADER = False

# ---------- Normalization Helpers ----------

def clean_unicode(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("_", " ").replace(",", " ").replace("[", " ").replace("]", " ")
    s = s.replace("{", " ").replace("}", " ").replace(";", " ").replace("+", " ")
    s = s.replace("–", "-").replace("—", "-").replace("·", " ")
    return s

def pre_split_fixes(name: str) -> str:
    # Remove parentheses and normalize punctuation
    name = name.replace("(", "").replace(")", "")
    name = clean_unicode(name)

    # Insert spaces at common glued boundaries (no lookbehinds)
    name = re.sub(r'(\b(?:19|20)\d{2})([A-Za-z])', r'\1 \2', name)  # 2005Unrated -> 2005 Unrated
    name = re.sub(r'([A-Za-z])(\d{3,4}p\b)', r'\1 \2', name, flags=re.IGNORECASE)  # Unrated1080p -> Unrated 1080p
    name = re.sub(r'(\d{3,4}p)([A-Za-z])', r'\1 \2', name, flags=re.IGNORECASE)    # 1080pBluRay -> 1080p BluRay
    # Jammed tokens like BluRayx264 -> BluRay x264 (extend as needed)
    name = re.sub(r'(BluRay)(x\d{3}|h\d{3}|HEVC|AV1|VP9)', r'\1 \2', name, flags=re.IGNORECASE)
    name = re.sub(r'(WEB[- ]?DL)(x\d{3}|h\d{3}|HEVC|AV1|VP9)', r'\1 \2', name, flags=re.IGNORECASE)

    return name

def tokenize(name: str):
    name = pre_split_fixes(name)
    # Preserve hyphens by marking them temporarily
    name = name.replace("-", "§DASH§")
    # Split on any non-alnum/underscore/marker
    parts = re.split(r"[^\w§]+", name)
    tokens = [p for p in parts if p]
    # Restore hyphens
    tokens = [t.replace("§DASH§", "-") for t in tokens]
    return tokens

def find_year_index(tokens):
    for i, t in enumerate(tokens):
        if re.fullmatch(r"(19\d{2}|20\d{2})", t):
            return i
    return None

# ---------- Tag Ordering & Classification ----------

QUALITY_RE = re.compile(r"^(?:\d{3,4}p)$", re.IGNORECASE)

EDITION = {
    "unrated", "extended", "theatrical", "director", "directors", "dc",
    "remastered", "imax", "uncut"
}
SOURCE = {"bluray", "bdrip", "webdl", "web-dl", "webrip", "web", "hdtv", "dvdrip", "remux", "hdrip"}
HDR = {"hdr", "hdr10", "hdr10+", "dolby", "vision", "dv"}
VIDEO = {"x264", "h264", "x265", "h265", "hevc", "xvid", "divx", "av1", "vp9"}
AUDIO = {"aac", "ac3", "eac3", "ddp", "dd5", "dd5.1", "dts", "truehd", "flac", "opus", "mp3", "atmos"}

def classify_token(token: str) -> str | None:
    """Return category name or None if not a known tag."""
    t = token.lower().lstrip("-")
    if QUALITY_RE.match(t):
        return "quality"
    if t in EDITION:
        return "edition"
    if t in SOURCE:
        return "source"
    if t in HDR:
        return "hdr"
    if t in VIDEO:
        return "video"
    if t in AUDIO:
        return "audio"
    return None

def pick_quality(tokens):
    for i, t in enumerate(tokens):
        if QUALITY_RE.match(t):
            return tokens.pop(i)
    return None

def dedupe_preserve_order(seq, key=lambda x: x.lower()):
    seen = set()
    out = []
    for item in seq:
        k = key(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out

def categorize_tags(rest_tokens):
    """Sort tokens into canonical order and remove duplicates."""
    rest = rest_tokens[:]  # copy
    quality = pick_quality(rest)

    buckets = {k: [] for k in ["quality", "edition", "source", "hdr", "video", "audio", "other"]}
    for t in rest:
        cat = classify_token(t)
        if cat:
            # Normalize WEB-DL visual if desired
            if cat == "source" and t.lower() in {"webdl", "web-dl"}:
                t = "WEB-DL"
            # Merge "Dolby Vision" if it was split
            if cat == "hdr" and t.lower() == "vision" and any(x.lower() == "dolby" for x in rest):
                t = "DolbyVision"
            buckets[cat].append(t)
        else:
            buckets["other"].append(t)

    for k in buckets:
        buckets[k] = dedupe_preserve_order(buckets[k])

    ordered = []
    if quality:
        ordered.append(quality)
    if buckets["quality"]:
        ordered.extend(buckets["quality"])
    for cat in ["edition", "source", "hdr", "video", "audio", "other"]:
        ordered.extend(buckets[cat])

    # Final cross-bucket dedupe
    ordered = dedupe_preserve_order(ordered)
    return ordered

# ---------- Core Normalizer ----------

def normalize_name(original_name: str) -> str:
    tokens = tokenize(original_name)
    if not tokens:
        return original_name

    year_idx = find_year_index(tokens)
    if year_idx is None:
        base = ".".join(tokens)
        base = re.sub(r"\.-\.", "-", base)
        base = re.sub(r"\.+", ".", base).strip(".")
        return base

    title_tokens = tokens[:year_idx]
    year = tokens[year_idx]
    rest = tokens[year_idx + 1:]

    uploader = None
    if rest:
        last = rest[-1]
        last_clean = last.lstrip("-")
        last_cat = classify_token(last_clean)
        if ALWAYS_TAKE_LAST_AS_UPLOADER or last_cat is None:
            uploader = last_clean
            rest = rest[:-1]

    ordered_tags = categorize_tags(rest)

    # If uploader duplicates a tag (case-insensitive), drop from tags
    if uploader:
        ordered_tags = [t for t in ordered_tags if t.lower() != uploader.lower()]

    parts = []
    if title_tokens:
        parts.append(".".join(title_tokens))
    parts.append(year)
    if ordered_tags:
        parts.append(".".join(ordered_tags))

    base = ".".join(parts)
    base = re.sub(r"\.-\.", "-", base)
    base = re.sub(r"\.+", ".", base).strip(".")

    if uploader:
        base = base.rstrip(".")
        base = f"{base}-{uploader}"

    return base

def unique_target_path(dirpath: str, target_name: str) -> str:
    candidate = os.path.join(dirpath, target_name)
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while True:
        with_suffix = os.path.join(dirpath, f"{target_name}.{n}")
        if not os.path.exists(with_suffix):
            return with_suffix
        n += 1

# ---------- File & Folder Processing ----------

def process_folder(entry_path: str, entry_name: str):
    new_name = normalize_name(entry_name)
    if not new_name or new_name == entry_name:
        return
    new_path = unique_target_path(DIRECTORY, new_name)
    print(f"Renaming folder:\n  {entry_name}\n→ {os.path.basename(new_path)}")
    if not DRY_RUN:
        try:
            os.rename(entry_path, new_path)
        except OSError as e:
            print(f"  !! Failed: {e}")

def process_file(entry_path: str, entry_name: str):
    # Build normalized folder name from the file's base name (no extension)
    base, ext = os.path.splitext(entry_name)
    folder_name = normalize_name(base)
    if not folder_name:
        folder_name = base  # fallback

    target_dir = unique_target_path(DIRECTORY, folder_name)
    print(f"Creating folder + moving file:\n  {entry_name}\n→ {os.path.basename(target_dir)}/")
    if not DRY_RUN:
        try:
            os.makedirs(target_dir, exist_ok=True)
            # Move file into the new folder (keep original file name)
            shutil.move(entry_path, os.path.join(target_dir, entry_name))
        except OSError as e:
            print(f"  !! Failed: {e}")

def main():
    if not os.path.isdir(DIRECTORY):
        print(f"Directory not found: {DIRECTORY}")
        return

    entries = sorted(os.listdir(DIRECTORY))
    for entry in entries:
        if entry.startswith("."):
            continue  # skip hidden files like .DS_Store

        entry_path = os.path.join(DIRECTORY, entry)

        try:
            if os.path.isdir(entry_path):
                process_folder(entry_path, entry)
            elif os.path.isfile(entry_path):
                process_file(entry_path, entry)
        except Exception as e:
            print(f"!! Error handling '{entry}': {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main()