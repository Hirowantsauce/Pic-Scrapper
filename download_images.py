#!/usr/bin/env python3
"""
Download all images from a webpage at the HIGHEST quality available.

Install:
    pip install requests beautifulsoup4 pillow
    # optional, for JavaScript-heavy sites:
    pip install playwright && playwright install chromium

Usage:
    python download_images.py https://example.com/page
    python download_images.py https://example.com/page --render        # JS / lazy-loaded sites
    python download_images.py https://example.com/page --deep --min-dim 300
    python download_images.py https://example.com/page --debug         # show every candidate tried

How it gets max quality:
  For every image on the page it collects ALL possible versions (srcset, lazy-load
  attributes, links to full-size files, and guessed "original" URLs for common CDNs
  like WordPress, Shopify, Wikipedia, Amazon, Cloudinary, Pinterest, Google, Twitter),
  downloads the candidates, and KEEPS THE ONE WITH THE MOST PIXELS.
"""

import argparse
import hashlib
import io
import mimetypes
import os
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image
except ImportError:
    Image = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".svg")
LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-full", "data-large",
              "data-hi-res", "data-zoom-src", "data-image", "data-img", "data-big",
              "data-full-src", "data-orig-file", "data-large-file")
LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")
RESIZE_PARAMS = {"w", "h", "width", "height", "resize", "fit", "size", "s", "maxwidth",
                 "maxheight", "quality", "q", "dpr", "crop", "thumb", "thumbnail"}

# (regex, replacement, host_must_match_or_None) -- each rewrites a thumbnail path into the original
PATH_RULES = [
    (r"/thumb/(.+?\.\w+)/[^/]+$", r"/\1", None),                                   # Wikipedia
    (r"_(?:pico|icon|thumb|small|compact|medium|large|grande|\d{2,4}x(?:\d{2,4})?)(?=\.\w+$)", "", None),  # Shopify
    (r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", None),                                    # WordPress -300x200
    (r"\._[A-Z0-9,_\-]+_(?=\.\w+$)", "", None),                                   # Amazon ._SX72_
    (r"/(?:(?:w|h|c|q|f|ar|dpr|g|e)_[\w.:]+,?)+(?=/)", "", None),                 # Cloudinary
    (r"/\d{2,4}x(?:\d{2,4})?(?=/)", "/originals", r"pinimg"),                     # Pinterest
    (r"/\d{2,4}x\d{2,4}(?=/)", "", None),                                         # /72x72/ folders
    (r"=[swh]\d+[-\w]*$", "=s0", r"googleusercontent|ggpht"),                     # Google images
    (r"/resize:\w+:\d+(?::\d+)?", "", None),                                      # Medium
]


# ---------------------------------------------------------------- URL helpers
def best_from_srcset(srcset):
    best, best_score = None, -1.0
    for part in re.split(r",\s+", srcset.strip()):
        bits = part.strip().split()
        if not bits:
            continue
        score = 1.0
        if len(bits) > 1:
            m = re.match(r"([\d.]+)([wx])", bits[1])
            if m:
                score = float(m.group(1)) * (1 if m.group(2) == "w" else 1000)
        if score > best_score:
            best, best_score = bits[0], score
    return best


def is_image_url(url):
    return urlparse(url).path.lower().endswith(IMG_EXTS)


def upgrade_variants(url):
    """Return (variants, canonical). Variants = guessed bigger/original versions of `url`."""
    p = urlparse(url)
    host = p.netloc.lower()
    pairs = parse_qsl(p.query, keep_blank_values=True)

    def build(path, query):
        return urlunparse(p._replace(path=path, query=query))

    # path rewrites: individually and cumulatively
    path_variants, full_path = [], p.path
    for pattern, repl, host_re in PATH_RULES:
        if host_re and not re.search(host_re, host):
            continue
        new = re.sub(pattern, repl, p.path)
        if new != p.path:
            path_variants.append(new)
        full_path = re.sub(pattern, repl, full_path)

    # query rewrites
    fixed = []
    for k, v in pairs:
        if k.lower() in RESIZE_PARAMS:
            continue
        if k == "name" and "twimg" in host:
            v = "orig"
        if k == "format" and re.fullmatch(r"\d+w", v):
            v = "original"
        fixed.append((k, v))
    full_query = urlencode(fixed)

    variants = [build(full_path, full_query)]
    variants += [build(pa, p.query) for pa in path_variants]
    if full_query != p.query:
        variants.append(build(p.path, full_query))
    if pairs:
        variants.append(build(p.path, ""))
        variants.append(build(full_path, ""))

    seen, out = {url}, []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out, build(full_path, full_query)


# ------------------------------------------------------------ page scraping
def render_page(url):
    """Load the page in a real browser (runs JS, scrolls to trigger lazy loading)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("--render needs Playwright:  pip install playwright && playwright install chromium")
    with sync_playwright() as pw:
        browser = None
        # Try Playwright's own Chromium first, then Chrome / Edge already installed on this PC
        for opts in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
            try:
                browser = pw.chromium.launch(**opts)
                break
            except Exception:
                continue
        if browser is None:
            sys.exit("No browser found. Install Google Chrome or Microsoft Edge, "
                     "or run:  python -m playwright install chromium")
        page = browser.new_page(user_agent=UA)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.evaluate("""async () => {
            await new Promise(resolve => {
                let y = 0;
                const t = setInterval(() => {
                    window.scrollBy(0, 700); y += 700;
                    if (y >= document.body.scrollHeight + 700) { clearInterval(t); resolve(); }
                }, 150);
            });
        }""")
        page.wait_for_timeout(1500)
        html, final = page.content(), page.url
        browser.close()
    return html, final


def collect_groups(html, base_url, deep=False):
    """Return a list of groups; each group = candidate URLs for ONE logical image."""
    soup = BeautifulSoup(html, "html.parser")
    groups, index = [], {}

    def norm(u):
        if not u or u.startswith("data:"):
            return None
        full = urljoin(base_url, u.strip())
        return full if full.startswith(("http://", "https://")) else None

    def add_group(cands):
        cands = [c for c in dict.fromkeys(norm(c) for c in cands) if c]
        if not cands:
            return
        keys = [upgrade_variants(c)[1] for c in cands]
        gi = next((index[k] for k in keys if k in index), None)
        if gi is None:
            groups.append([])
            gi = len(groups) - 1
        for c, k in zip(cands, keys):
            if c not in groups[gi]:
                groups[gi].append(c)
            index[k] = gi

    def srcset_best(el):
        for attr in ("srcset",) + LAZY_SRCSET:
            if el.get(attr):
                b = best_from_srcset(el[attr])
                if b:
                    return b
        return None

    for img in soup.find_all("img"):
        cands = []
        a = img.find_parent("a", href=True)
        if a and is_image_url(urljoin(base_url, a["href"])):
            cands.append(a["href"])
        cands.append(srcset_best(img))
        cands += [img.get(x) for x in LAZY_ATTRS]
        cands.append(img.get("src"))
        add_group(cands)

    for source in soup.find_all("source"):
        add_group([srcset_best(source), source.get("src")])

    for a in soup.find_all("a", href=True):
        if is_image_url(a["href"]):
            add_group([a["href"]])

    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            add_group([meta.get("content")])

    for el in soup.find_all(style=True):
        for m in re.finditer(r"url\(['\"]?([^'\")]+)['\"]?\)", el["style"]):
            add_group([m.group(1)])

    if deep:  # also scan raw HTML/JSON/script text for any image URL
        raw = html.replace("\\/", "/").replace("\\u002F", "/")
        pattern = r"https?://[^\s\"'<>()\\,]+?\.(?:jpe?g|png|webp|avif|gif|bmp|tiff?)(?:\?[^\s\"'<>()\\]*)?"
        for m in re.finditer(pattern, raw, flags=re.I):
            add_group([m.group(0)])

    return groups


# --------------------------------------------------------------- downloading
def fetch_image(session, url, referer):
    try:
        r = session.get(url, headers={"User-Agent": UA, "Referer": referer,
                                      "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
                        timeout=30)
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or not r.content:
            return None, ""
        if not (ctype.startswith("image/") or is_image_url(url)):
            return None, ""
        return r.content, ctype
    except requests.RequestException:
        return None, ""


def dimensions(data):
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def make_filename(url, ctype, used):
    name = os.path.basename(unquote(urlparse(url).path)) or "image"
    name = re.sub(r"[^\w.\-]+", "_", name)[:120]
    root, ext = os.path.splitext(name)
    if ext.lower() not in IMG_EXTS:
        root, ext = name, (mimetypes.guess_extension(ctype) or ".jpg")
        if ext == ".jpe":
            ext = ".jpg"
    name = root + ext
    if name in used:
        name = f"{root}_{hashlib.md5(url.encode()).hexdigest()[:8]}{ext}"
    used.add(name)
    return name


def download_images(
    url,
    output="downloaded_images",
    render=False,
    deep=False,
    no_upgrade=False,
    min_dim=0,
    debug=False,
    progress_callback=None,
    is_cancelled=None
):
    """
    Downloads all images at highest resolution.
    progress_callback receives dict with event info.
    is_cancelled is a callable returning bool.
    """
    def emit(event_type, **kwargs):
        if progress_callback:
            progress_callback({"type": event_type, **kwargs})

    os.makedirs(output, exist_ok=True)
    session = requests.Session()

    emit("status", stage="connecting", message=f"Connecting to {url}...")

    if render:
        emit("status", stage="rendering", message="Rendering page in headless browser (executing JS & scrolling)...")
        try:
            html, page_url = render_page(url)
        except Exception as e:
            emit("error", message=f"Rendering failed: {e}")
            raise
    else:
        try:
            r = session.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            html, page_url = r.text, r.url
        except requests.RequestException as e:
            emit("error", message=f"Could not load page: {e}")
            raise

    if is_cancelled and is_cancelled():
        emit("cancelled", message="Download cancelled by user.")
        return {"saved": 0, "total": 0, "output": output}

    emit("status", stage="parsing", message="Parsing DOM and extracting image variants...")
    groups = collect_groups(html, page_url, deep=deep)
    total_groups = len(groups)
    emit("scraped", total=total_groups, message=f"Found {total_groups} distinct image(s)")

    if Image is None:
        emit("log", level="warn", message="Pillow not installed: choosing largest file size instead of resolution.")

    used = set()
    saved = 0
    saved_files = []

    for i, group in enumerate(groups, 1):
        if is_cancelled and is_cancelled():
            emit("cancelled", message="Download cancelled by user.")
            break

        emit("progress", index=i, total=total_groups, percent=round(((i - 1) / total_groups) * 100, 1),
             status=f"Processing image {i} of {total_groups}...")

        cands = []
        for c in group:
            if not no_upgrade:
                cands += upgrade_variants(c)[0]
            cands.append(c)
        cands = list(dict.fromkeys(cands))[:12]

        emit("candidates", index=i, total=total_groups, candidate_count=len(cands), initial_url=group[0])

        best = None  # (score, url, data, ctype, dims)
        for c in cands:
            if is_cancelled and is_cancelled():
                break
            data, ctype = fetch_image(session, c, page_url)
            if not data:
                if debug:
                    emit("log", level="debug", message=f"[{i}/{total_groups}] ✕ candidate failed: {c}")
                continue
            dims = dimensions(data)
            score = ((dims[0] * dims[1]) if dims else 0, len(data))
            if debug:
                dim_str = f"{dims[0]}x{dims[1]}" if dims else "?"
                emit("log", level="debug", message=f"[{i}/{total_groups}] ✓ candidate {dim_str} ({len(data)//1024} KB): {c}")
            if best is None or score > best[0]:
                best = (score, c, data, ctype, dims)

        if is_cancelled and is_cancelled():
            emit("cancelled", message="Download cancelled by user.")
            break

        if not best:
            emit("image_result", index=i, total=total_groups, status="failed", url=group[0],
                 message=f"[{i}/{total_groups}] Failed to fetch any valid candidate for: {group[0]}")
            continue

        _, best_url, data, ctype, dims = best
        if min_dim and dims and min(dims) < min_dim:
            emit("image_result", index=i, total=total_groups, status="skipped", url=best_url, dims=dims,
                 message=f"[{i}/{total_groups}] Skipped (dimensions {dims[0]}x{dims[1]} below minimum {min_dim}px)")
            continue

        fname = make_filename(best_url, ctype, used)
        fpath = os.path.join(output, fname)
        with open(fpath, "wb") as f:
            f.write(data)

        saved += 1
        dim_str = f"{dims[0]}x{dims[1]}px" if dims else "?px"
        file_info = {
            "filename": fname,
            "filepath": fpath,
            "url": best_url,
            "dimensions": dims,
            "dim_str": dim_str,
            "size_bytes": len(data),
            "size_kb": round(len(data) / 1024, 1),
            "content_type": ctype
        }
        saved_files.append(file_info)

        emit("image_result", index=i, total=total_groups, status="saved", file=file_info,
             message=f"[{i}/{total_groups}] Saved {fname} ({dim_str}, {file_info['size_kb']} KB)")

    percent_final = 100.0 if not (is_cancelled and is_cancelled()) else round((saved / max(total_groups, 1)) * 100, 1)
    emit("progress", index=total_groups, total=total_groups, percent=percent_final, status="Done")
    emit("done", saved=saved, total=total_groups, output=output, files=saved_files)
    return {"saved": saved, "total": total_groups, "output": output, "files": saved_files}


def main():
    ap = argparse.ArgumentParser(description="Download all images from a page in max quality.")
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default="downloaded_images")
    ap.add_argument("--render", action="store_true",
                    help="Render the page in a headless browser first (JS / lazy-loaded sites)")
    ap.add_argument("--deep", action="store_true",
                    help="Also scan raw page source / JSON for image URLs")
    ap.add_argument("--no-upgrade", action="store_true", help="Don't guess original-size URLs")
    ap.add_argument("--min-dim", type=int, default=0,
                    help="Skip images whose shortest side is below this many pixels")
    ap.add_argument("--debug", action="store_true", help="Print every candidate URL and its size")
    args = ap.parse_args()

    def cli_cb(ev):
        t = ev.get("type")
        if t == "scraped":
            print(f"Found {ev['total']} distinct image(s)\n")
        elif t == "log" and ev.get("level") == "debug":
            print(f"      {ev['message']}")
        elif t == "image_result":
            status = ev.get("status")
            if status == "saved":
                f = ev["file"]
                print(f"[{ev['index']}/{ev['total']}] {f['filename']}  {f['dim_str']}  {f['size_kb']} KB")
            elif status == "skipped":
                print(ev["message"])
            elif status == "failed":
                print(ev["message"])
        elif t == "done":
            print(f"\nDone: {ev['saved']} saved to '{ev['output']}/'")

    download_images(
        args.url,
        output=args.output,
        render=args.render,
        deep=args.deep,
        no_upgrade=args.no_upgrade,
        min_dim=args.min_dim,
        debug=args.debug,
        progress_callback=cli_cb
    )


if __name__ == "__main__":
    main()
