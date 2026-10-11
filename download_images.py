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
  attributes, links to full-size files, and guessed "original" URLs for major platforms
  like Pixiv, Wallhaven, WallpaperCave, WallpaperFlare, WallpapersWide, Reddit, Imgur,
  Pinterest, ArtStation, DeviantArt, WordPress, Shopify, Wikipedia, Unsplash, Boorus,
  Flickr, Twitter/X, Google), downloads the candidates, and KEEPS THE ONE WITH THE MOST PIXELS.
"""

import argparse
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image
except ImportError:
    Image = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".svg")

EXTENDED_LAZY_ATTRS = (
    "data-src", "data-original", "data-lazy-src", "data-full", "data-large",
    "data-hi-res", "data-zoom-src", "data-image", "data-img", "data-big",
    "data-full-src", "data-orig-file", "data-large-file", "data-high-res-src",
    "data-original-src", "data-full-image", "data-wallpaper", "data-desktop",
    "data-download-url", "data-download", "data-hires", "data-highres",
    "data-url", "data-full-url", "data-src-retina", "data-raw", "data-wp",
    "data-fullsize", "data-original-image", "data-zoom-image", "data-src-zoom",
    "data-source", "data-max-url", "data-bg", "data-background", "data-target",
    "data-original-file-url", "data-asset-url", "data-cdn-src"
)

LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")

RESIZE_PARAMS = {
    "w", "h", "width", "height", "resize", "fit", "size", "s", "maxwidth",
    "maxheight", "quality", "q", "dpr", "crop", "thumb", "thumbnail",
    "zoom", "scale", "sz"
}

REFERER_OVERRIDES = {
    "pximg.net": "https://www.pixiv.net/",
    "donmai.us": "https://danbooru.donmai.us/",
    "gelbooru.com": "https://gelbooru.com/",
    "artstation.com": "https://www.artstation.com/",
    "wixmp.com": "https://www.deviantart.com/",
    "deviantart.net": "https://www.deviantart.com/",
    "sinaimg.cn": "https://weibo.com/",
    "hdslb.com": "https://www.bilibili.com/",
    "wallhaven.cc": "https://wallhaven.cc/",
    "wallpapercave.com": "https://wallpapercave.com/",
    "wallpaperflare.com": "https://www.wallpaperflare.com/",
}

UI_CLUTTER_PATTERNS = [
    r'/common/images/services/',
    r'/common/images/icons/',
    r'apple-touch-icon',
    r'/favicon\.',
    r'/site-icons/',
    r'/nav_logo',
    r'gravatar\.com/avatar',
    r'spacer\.gif',
    r'blank\.gif',
    r'pixel\.gif',
    r'/reaction/',
    r'/emoji/',
    r'abs-0\.twimg\.com',
    r'/hashflags/',
]

# (regex, replacement, host_must_match_or_None) -- each rewrites a thumbnail path into the original
PATH_RULES = [
    # Wikipedia
    (r"/thumb/(.+?\.\w+)/[^/]+$", r"/\1", None),
    # Shopify
    (r"_(?:pico|icon|thumb|small|compact|medium|large|grande|\d{2,4}x(?:\d{2,4})?)(?=\.\w+$)", "", None),
    # WordPress -300x200, -scaled, -rotated
    (r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", None),
    (r"-(?:scaled|rotated)(?=\.\w+$)", "", None),
    # Amazon
    (r"\._[A-Z0-9,_\-]+_(?=\.\w+$)", "", None),
    # Cloudinary
    (r"/(?:(?:w|h|c|q|f|ar|dpr|g|e)_[\w.:]+,?)+(?=/)", "", None),
    # Pinterest: /736x/ or /236x/ -> /originals/
    (r"/\d{2,4}x(?:\d{2,4})?(?=/)", "/originals", r"pinimg"),
    # Generic resolution subfolders e.g. /72x72/, /300x200/
    (r"/\d{2,4}x\d{2,4}(?=/)", "", None),
    # Google images / Google User Content / Blogger
    (r"=[swh]\d+[-\w]*$", "=s0", r"googleusercontent|ggpht|blogger"),
    (r"/s\d+(?:-c)?(?=/)", "/s0", r"googleusercontent|ggpht|blogger|bp\.blogspot"),
    (r"/w\d+-h\d+(?=/)", "/s0", r"googleusercontent|ggpht|blogger|bp\.blogspot"),
    # Medium
    (r"/resize:\w+:\d+(?::\d+)?", "", None),
    # WallpaperCave: /dwp1x/, /dwp2x/, /mwp/, /w200/, /w400/ -> /wp/, /fuwp/ -> /uwp/
    (r"/dwp\d*x?/(?=wp\d+)", "/wp/", r"wallpapercave"),
    (r"/mwp/(?=wp\d+)", "/wp/", r"wallpapercave"),
    (r"/w\d+/(?=wp\d+)", "/wp/", r"wallpapercave"),
    (r"/fuwp/(?=uwp\d+)", "/uwp/", r"wallpapercave"),
    # WallpaperFlare / generic preview & thumb suffixes
    (r"[-_](?:preview|thumb|thumbnail|sample|small|mini)(?=\.\w+$)", "", None),
    # WallpapersWide
    (r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "-3840x2160", r"wallpaperswide"),
    # Galleries & Manga trailing 't' suffix: 1t.jpg -> 1.jpg, 40t.jpg -> 40.jpg
    (r"(\d+)t(?=\.\w+$)", r"\1", None),
    # Subfolders like /thumbs/, /thumbnails/, /previews/, /samples/
    (r"/(?:thumbs?|thumbnails?|previews?|samples?)/(?=[^/]+\.\w+$)", "/", None),
    # DeviantArt / Wix
    (r"/v1/fill/w_\d+,h_\d+.*?/(.+?)(?:\?.*)?$", r"/\1", r"wixmp"),
    # Boorus (Danbooru, Gelbooru, Safebooru, etc.)
    (r"/(?:preview|thumbnails?|sample)/(?=[^/]+\.\w+$)", "/original/", r"donmai|gelbooru|safebooru|booru"),
    # Flickr
    (r"_([sqtmnwzcbk])(?=\.\w+$)", "_b", r"staticflickr"),
    # Tumblr
    (r"_\d{3,4}(?=\.\w+$)", "_1280", r"media\.tumblr"),
]


# ---------------------------------------------------------------- URL helpers
def best_from_srcset(srcset):
    if not srcset:
        return None
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
    if not url:
        return False
    return urlparse(url).path.lower().endswith(IMG_EXTS)


def is_image_or_download_url(url):
    if not url:
        return False
    p = urlparse(url)
    path = p.path.lower()
    if path.endswith(IMG_EXTS):
        return True
    q = p.query.lower()
    if any(q.endswith(ext) or (ext + "&") in q for ext in IMG_EXTS):
        return True
    if "/download" in path or "download=" in q or "force=true" in q:
        return True
    return False


def is_ui_clutter(url):
    """Detect website UI chrome, service icons, and tracking pixels."""
    if not url:
        return True
    u_lower = url.lower()
    for pat in UI_CLUTTER_PATTERNS:
        if re.search(pat, u_lower):
            return True
    return False


def upgrade_variants(url):
    """Return (variants, canonical). Variants = guessed bigger/original versions of `url`."""
    p = urlparse(url)
    host = p.netloc.lower()
    path = p.path
    pairs = parse_qsl(p.query, keep_blank_values=True)

    def build(new_path, new_query, new_netloc=None):
        nl = new_netloc or p.netloc
        return urlunparse(p._replace(netloc=nl, path=new_path, query=new_query))

    variants = []
    path_variants = []
    full_path = path

    # 1. Specialized platform handlers
    # --- Pixiv (pximg.net) ---
    if "pximg.net" in host:
        m = re.search(r'/(?:img-master|custom-thumb)/img/(.+?/(\d+_p\d+))(?:_(?:master|square|custom)\d+)?\.\w+', path)
        if not m:
            m = re.search(r'/img/(.+?/(\d+_p\d+))(?:_(?:master|square|custom)\d+)?\.\w+', path)
        if m:
            rel = m.group(1)
            variants.append(build(f"/img-original/img/{rel}.jpg", ""))
            variants.append(build(f"/img-original/img/{rel}.png", ""))
            variants.append(build(f"/img-master/img/{rel}_master1200.jpg", ""))

    # --- Wallhaven (wallhaven.cc) ---
    if "wallhaven.cc" in host:
        m = re.search(r'th\.wallhaven\.cc/(?:small|lg)/(\w{2})/(\w+)\.\w+', url)
        if m:
            sub, wid = m.group(1), m.group(2)
            variants.append(f"https://w.wallhaven.cc/full/{sub}/wallhaven-{wid}.jpg")
            variants.append(f"https://w.wallhaven.cc/full/{sub}/wallhaven-{wid}.png")

    # --- Reddit (preview.redd.it) ---
    if "redd.it" in host or "reddit.com" in host:
        m = re.search(r'preview\.redd\.it/([a-zA-Z0-9_-]+\.\w+)', url)
        if m:
            variants.append(f"https://i.redd.it/{m.group(1)}")
            variants.append(build(path, ""))

    # --- Imgur (i.imgur.com) ---
    if "imgur.com" in host:
        m = re.search(r'/([a-zA-Z0-9]{5,8})[sbtmlh]\.(\w+)$', path)
        if m:
            variants.append(build(f"/{m.group(1)}.{m.group(2)}", ""))

    # --- Gallery subdomains: t1.domain.com -> i1.domain.com or i.domain.com ---
    if re.match(r'^t\d*\.', host):
        new_host_i = re.sub(r'^t(\d*)\.', r'i\1.', host)
        p_strip = re.sub(r'(\d+)t(?=\.\w+$)', r'\1', path)
        variants.append(build(p_strip, p.query, new_netloc=new_host_i))
        variants.append(build(p_strip, "", new_netloc=new_host_i))

    # --- ArtStation ---
    if "artstation" in host:
        for size in ("/4k/", "/original/", "/large/"):
            variants.append(build(re.sub(r'/(?:small|medium|large|4k|original)/', size, path), p.query))

    # --- Twitter / X (pbs.twimg.com) ---
    if "twimg.com" in host:
        m = re.search(r'/media/([a-zA-Z0-9_-]+)', path)
        if m:
            mid = m.group(1)
            # Twitter orig is usually uploaded jpg or png; format=webp&name=orig often returns 404
            variants.append(f"https://pbs.twimg.com/media/{mid}?format=jpg&name=orig")
            variants.append(f"https://pbs.twimg.com/media/{mid}?format=png&name=orig")
            variants.append(f"https://pbs.twimg.com/media/{mid}?format=webp&name=orig")
            variants.append(f"https://pbs.twimg.com/media/{mid}?format=jpg&name=large")
            variants.append(f"https://pbs.twimg.com/media/{mid}?format=png&name=large")
        elif "profile_banners" in path:
            base_b = re.sub(r'/\d+x\d+$', '', url)
            variants.append(f"{base_b}/1500x500")
            variants.append(base_b)
        elif "profile_images" in path:
            variants.append(re.sub(r'_(?:normal|reasonably_small|\d+x\d+)(\.\w+)$', r'\1', url))

    # 2. General Regex Path Rules
    for pattern, repl, host_re in PATH_RULES:
        if host_re and not re.search(host_re, host):
            continue
        new = re.sub(pattern, repl, path)
        if new != path:
            path_variants.append(new)
        full_path = re.sub(pattern, repl, full_path)

    # 3. Query rewrites
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

    # 4. Assemble candidate variations
    variants.append(build(full_path, full_query))
    for pa in path_variants:
        variants.append(build(pa, p.query))
        variants.append(build(pa, full_query))
        variants.append(build(pa, ""))

    if full_query != p.query:
        variants.append(build(path, full_query))
    if pairs:
        variants.append(build(path, ""))
        variants.append(build(full_path, ""))

    # Unsplash: request maximum uncropped resolution
    if "unsplash.com" in host:
        variants.append(build(path, "q=100&w=3840&auto=format&fit=max"))

    # For original guesses, if path changed, also try alternative extensions (.png, .jpg)
    ext_alts = []
    for v in variants:
        vp = urlparse(v)
        root, ext = re.sub(r'\.\w+$', '', vp.path), (re.search(r'\.\w+$', vp.path).group(0) if re.search(r'\.\w+$', vp.path) else "")
        if ext.lower() in (".jpg", ".jpeg"):
            ext_alts.append(urlunparse(vp._replace(path=root + ".png")))
        elif ext.lower() == ".png":
            ext_alts.append(urlunparse(vp._replace(path=root + ".jpg")))
    variants += ext_alts

    # Deduplicate while preserving order
    seen, out = {url}, []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    return out, build(full_path, full_query)


# ------------------------------------------------------------ specialized platform extractors
def check_pixiv_artwork(session, url):
    """If the target URL is a Pixiv artwork page, retrieve the original UHD image URLs via Pixiv's official AJAX API."""
    p = urlparse(url)
    if "pixiv.net" in p.netloc:
        m = re.search(r'/artworks/(\d+)', p.path)
        if m:
            illust_id = m.group(1)
            api_url = f"https://www.pixiv.net/ajax/illust/{illust_id}"
            headers = {"User-Agent": UA, "Referer": url}
            try:
                r = session.get(api_url, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json().get("body", {})
                    urls = []
                    page_count = data.get("pageCount", 1)
                    if page_count > 1:
                        pages_r = session.get(f"{api_url}/pages", headers=headers, timeout=15)
                        if pages_r.status_code == 200:
                            for p_info in pages_r.json().get("body", []):
                                orig = p_info.get("urls", {}).get("original")
                                if orig:
                                    urls.append(orig)
                    if not urls:
                        orig = data.get("urls", {}).get("original")
                        if orig:
                            urls.append(orig)
                    if urls:
                        return urls
            except Exception:
                pass
    return None


def resolve_wallpaperflare_detail(session, detail_url):
    """Retrieve full 4K resolution image URL from a WallpaperFlare wallpaper page."""
    dl_url = detail_url.rstrip("/") + "/download"
    try:
        r = session.get(dl_url, headers={"User-Agent": UA, "Referer": detail_url}, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            show_img = soup.find("img", id="show_img")
            if show_img and show_img.get("src"):
                return show_img["src"]
            for img in soup.find_all("img"):
                src = img.get("src") or ""
                if "wallpaper" in src and ("r4.wallpaperflare.com" in src or "c4.wallpaperflare.com" in src):
                    if "-preview" not in src and "-thumb" not in src:
                        return src
    except Exception:
        pass
    return None


# ------------------------------------------------------------ page scraping
def render_page(url, is_cancelled=None):
    """Load the page in a real browser (runs JS, scrolls to trigger lazy loading)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as pw:
        browser = None
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        # Try Playwright's Chromium or local Edge/Chrome with stealth args
        for opts in (
            {"args": launch_args},
            {"channel": "chrome", "args": launch_args},
            {"channel": "msedge", "args": launch_args},
            {},
            {"channel": "chrome"},
            {"channel": "msedge"},
        ):
            try:
                browser = pw.chromium.launch(**opts)
                break
            except Exception:
                continue

        if browser is None:
            raise RuntimeError(
                "No browser found. Install Google Chrome or Microsoft Edge, "
                "or run: python -m playwright install chromium"
            )

        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = context.new_page()

        # Mask automation properties
        try:
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        except Exception:
            pass

        # Dynamic websites (like X/Twitter, Reddit, YouTube) have persistent network activity
        # (WebSockets, analytics, long-polling) that causes wait_until="networkidle" to time out.
        # Wait until the DOM is loaded first, then optionally allow a brief window for extra resources.
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            page.goto(url, wait_until="commit", timeout=20000)

        # Allow basic scripts to execute and initial images to render
        try:
            page.wait_for_load_state("load", timeout=8000)
        except Exception:
            pass

        # Settle network if idle quickly, but do not wait indefinitely
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        if is_cancelled and is_cancelled():
            browser.close()
            return "", url

        # Safe scrolling: bounds scroll distance and stops when no new content is loading
        page.evaluate("""async () => {
            await new Promise(resolve => {
                let totalScrolled = 0;
                const maxScroll = 12000;
                let lastHeight = document.body ? document.body.scrollHeight : 0;
                let stalled = 0;
                const timer = setInterval(() => {
                    window.scrollBy(0, 800);
                    totalScrolled += 800;
                    const curHeight = document.body ? document.body.scrollHeight : 0;
                    if (curHeight === lastHeight) {
                        stalled++;
                    } else {
                        stalled = 0;
                        lastHeight = curHeight;
                    }
                    if (totalScrolled >= maxScroll || stalled >= 8 || totalScrolled >= curHeight + 1000) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 150);
                setTimeout(() => { clearInterval(timer); resolve(); }, 12000);
            });
        }""")

        page.wait_for_timeout(1500)
        html, final = page.content(), page.url
        browser.close()
    return html, final


def collect_groups(html, base_url, deep=False, session=None):
    """Return a list of groups; each group = candidate URLs for ONE logical image."""
    soup = BeautifulSoup(html, "html.parser")
    groups, index = [], {}

    def norm(u):
        if not u or u.startswith("data:"):
            return None
        full = urljoin(base_url, u.strip())
        return full if full.startswith(("http://", "https://")) else None

    def add_group(cands):
        # Filter UI icons and empty values
        cleaned = []
        for c in cands:
            nc = norm(c)
            if nc and not is_ui_clutter(nc):
                cleaned.append(nc)
        cands = list(dict.fromkeys(cleaned))
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
        if not el:
            return None
        for attr in ("srcset",) + LAZY_SRCSET:
            if el.get(attr):
                b = best_from_srcset(el[attr])
                if b:
                    return b
        return None

    # 1. Process <picture> tags (binds sources and child img together into ONE logical group)
    processed_imgs = set()
    for pic in soup.find_all("picture"):
        cands = []
        img = pic.find("img")
        if img:
            processed_imgs.add(img)
            cands.append(srcset_best(img))
            cands += [img.get(x) for x in EXTENDED_LAZY_ATTRS]
            cands.append(img.get("src"))
        for source in pic.find_all("source"):
            cands.append(srcset_best(source))
            cands.append(source.get("src"))
            cands += [source.get(x) for x in EXTENDED_LAZY_ATTRS]
        a = pic.find_parent("a", href=True) or (img.find_parent("a", href=True) if img else None)
        if a:
            cands += [a.get(x) for x in EXTENDED_LAZY_ATTRS]
            href = a.get("href")
            if href and is_image_or_download_url(urljoin(base_url, href)):
                cands.append(href)
        add_group(cands)

    # 2. Process all remaining <img> tags
    for img in soup.find_all("img"):
        if img in processed_imgs:
            continue
        cands = []
        a = img.find_parent("a", href=True)
        if a:
            cands += [a.get(x) for x in EXTENDED_LAZY_ATTRS]
            href = a.get("href")
            if href and is_image_or_download_url(urljoin(base_url, href)):
                cands.append(href)
        cands.append(srcset_best(img))
        cands += [img.get(x) for x in EXTENDED_LAZY_ATTRS]
        cands.append(img.get("src"))
        add_group(cands)

    # 3. Direct links to image files <a>
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if is_image_url(urljoin(base_url, href)):
            add_group([href])

    # 4. OpenGraph and Twitter cards (og:image often holds higher-res preview)
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src", "image"):
            content = meta.get("content")
            if content and not is_ui_clutter(content):
                add_group([content])

    # 5. Background images in inline styles
    for el in soup.find_all(style=True):
        for m in re.finditer(r"url\(['\"]?([^'\")]+)['\"]?\)", el["style"]):
            u = m.group(1)
            if not is_ui_clutter(u):
                add_group([u])

    # 6. Structured JSON data (Next.js __NEXT_DATA__, JSON-LD, meta-preload-data)
    for script in soup.find_all("script"):
        stype = script.get("type", "").lower()
        sid = script.get("id", "").lower()
        if "json" in stype or sid in ("__next_data__", "meta-preload-data") or script.string:
            s_content = script.string or ""
            if len(s_content) > 10 and ("image" in s_content or "http" in s_content):
                # Search for original/full image URLs in JSON
                pattern = r"https?://[^\s\"'<>()\\,]+?\.(?:jpe?g|png|webp|avif|bmp|tiff?)(?:\?[^\s\"'<>()\\]*)?"
                for m in re.finditer(pattern, s_content.replace("\\/", "/")):
                    found_u = m.group(0)
                    if not is_ui_clutter(found_u):
                        add_group([found_u])

    # 7. Deep scan: also scan raw HTML/JSON for any image URL if requested
    if deep:
        raw = html.replace("\\/", "/").replace("\\u002F", "/")
        pattern = r"https?://[^\s\"'<>()\\,]+?\.(?:jpe?g|png|webp|avif|gif|bmp|tiff?)(?:\?[^\s\"'<>()\\]*)?"
        for m in re.finditer(pattern, raw, flags=re.I):
            u = m.group(0)
            if not is_ui_clutter(u):
                add_group([u])

        # Deep gallery resolution: if on WallpaperFlare, resolve detail pages for full UHD images
        if "wallpaperflare.com" in base_url and session:
            detail_links = []
            for a in soup.find_all("a", href=True):
                href = urljoin(base_url, a["href"])
                if "wallpaperflare.com" in href and "-wallpaper-" in href and not href.endswith(IMG_EXTS):
                    if href not in detail_links:
                        detail_links.append(href)
            if detail_links:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    futures = [ex.submit(resolve_wallpaperflare_detail, session, dl) for dl in detail_links[:30]]
                    for f in futures:
                        try:
                            full_res = f.result()
                            if full_res:
                                add_group([full_res])
                        except Exception:
                            pass

    return groups


# --------------------------------------------------------------- downloading
def is_valid_image(data, ctype):
    if not data or len(data) < 24:
        return False
    if ctype.startswith("image/"):
        return True
    # Magic bytes check
    if data.startswith(b"\xff\xd8\xff"): return True              # JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return True          # PNG
    if data.startswith(b"GIF8"): return True                       # GIF
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]: return True # WEBP
    if b"ftyp" in data[:16]: return True                           # AVIF/HEIF
    if data.startswith(b"BM"): return True                         # BMP
    if b"<svg" in data[:256].lower(): return True                  # SVG
    return False


def fetch_image(session, url, referer):
    """Fetch image with automatic anti-hotlinking handling and referer fallbacks."""
    host = urlparse(url).netloc.lower()

    # Determine primary referer for this CDN
    target_ref = referer
    for k, v in REFERER_OVERRIDES.items():
        if k in host:
            target_ref = v
            break

    # Sequence of referers to try if hotlink protection returns 403 or 401
    ref_attempts = [target_ref]
    host_ref = f"https://{host}/"
    if host_ref not in ref_attempts:
        ref_attempts.append(host_ref)
    if None not in ref_attempts:
        ref_attempts.append(None)

    for ref in ref_attempts:
        headers = {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        if ref:
            headers["Referer"] = ref

        try:
            r = session.get(url, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code == 200 and r.content:
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if is_valid_image(r.content, ctype):
                    return r.content, ctype or "image/jpeg"
            elif r.status_code in (401, 403):
                continue
            else:
                break
        except requests.RequestException:
            continue

    return None, ""


def dimensions(data):
    if Image is None or not data:
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

    # Specialized direct API handler for single Pixiv artworks
    pixiv_direct_urls = check_pixiv_artwork(session, url)
    if pixiv_direct_urls:
        emit("status", stage="pixiv_api", message=f"Identified Pixiv artwork: extracting {len(pixiv_direct_urls)} original UHD master file(s)...")
        groups = [[u] for u in pixiv_direct_urls]
        page_url = url
    else:
        if render:
            emit("status", stage="rendering", message="Rendering page in headless browser (executing JS & scrolling)...")
            try:
                html, page_url = render_page(url, is_cancelled=is_cancelled)
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
        groups = collect_groups(html, page_url, deep=deep, session=session)

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
                upgrades, _ = upgrade_variants(c)
                cands += upgrades
            cands.append(c)
        cands = list(dict.fromkeys(cands))[:16]

        emit("candidates", index=i, total=total_groups, candidate_count=len(cands), initial_url=group[0])

        best = None  # (score, url, data, ctype, dims)
        for c in cands:
            if is_cancelled and is_cancelled():
                break
            data, ctype = fetch_image(session, c, page_url)
            if not data:
                if debug:
                    emit("log", level="debug", message=f"[{i}/{total_groups}] [x] candidate failed: {c}")
                continue
            dims = dimensions(data)
            score = ((dims[0] * dims[1]) if dims else 0, len(data))
            if debug:
                dim_str = f"{dims[0]}x{dims[1]}" if dims else "?"
                emit("log", level="debug", message=f"[{i}/{total_groups}] [+] candidate {dim_str} ({len(data)//1024} KB): {c}")
            if best is None or score > best[0]:
                best = (score, c, data, ctype, dims)

            # Optimization: If we found an ultra-HD original (>= 2560x1440 or >= 4MP), no need to fetch low-res previews
            if dims and (dims[0] >= 2560 or dims[1] >= 1440 or (dims[0] * dims[1]) >= 4_000_000):
                break

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
        os.makedirs(os.path.dirname(os.path.abspath(fpath)), exist_ok=True)
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
