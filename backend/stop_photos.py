from functools import lru_cache
from html import unescape
import re
from urllib.parse import quote, urlsplit

import requests

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TransitPulse/1.0 (Boston transit dashboard; nearby photo discovery)"
NIGHT = re.compile(r"\b(night(?:time)?|after dark|dusk|twilight|blue hour)\b", re.I)
NON_SCENIC = re.compile(
    r"\b(headstone|gravestone|burial|portrait|interior|map|diagram|logo|plaque|"
    r"staircase|faregate|close.up|midnight ride)\b", re.I
)
DAY = re.compile(r"\b(daytime|midday|daylight)\b", re.I)
LICENSE = re.compile(r"https?://creativecommons\.org/(?:licenses/by(?:-sa)?/[1-4]\.0|publicdomain/zero/1\.0)/?")


def thumbnail_url(value):
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc not in {"thumb.wikimedia.org", "upload.wikimedia.org"}:
        return None
    if not url.path.startswith("/wikipedia/commons/thumb/"):
        return None
    # The URL also appears inside a CSS string in the frontend.
    return f"https://{url.netloc}{quote(url.path, safe='/%.:_-')}"


@lru_cache(maxsize=1024)
def nearby_photo(latitude, longitude, night, _cache_window):
    radius = 1600 if night else 900
    query = f"nearcoord:{radius}m,{latitude},{longitude} filetype:bitmap"
    query += " intitle:/night|dusk|twilight/" if night else " -intitle:/night|dusk|twilight/"
    response = requests.get(
        COMMONS_API,
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": query,
            "gsrlimit": 24,
            "prop": "imageinfo|coordinates",
            "iiprop": "url|extmetadata|mime",
            "iiextmetadatafilter": "Artist|LicenseUrl|LicenseShortName|DateTimeOriginal",
            "iiurlwidth": 960,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=4,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", [])
    def proximity(page):
        coordinates = next(iter(page.get("coordinates", [])), None)
        if coordinates is None:
            return (float("inf"), page.get("index", 0))
        distance = (coordinates["lat"] - latitude) ** 2 + ((coordinates["lon"] - longitude) * 0.74) ** 2
        return (distance, page.get("index", 0))

    for page in sorted(pages, key=proximity):
        title = page.get("title", "")
        if NON_SCENIC.search(title) or bool(NIGHT.search(title)) != night:
            continue
        info = next(iter(page.get("imageinfo", [])), {})
        if info.get("mime") not in {"image/jpeg", "image/webp", "image/png"}:
            continue
        width, height = info.get("thumbwidth", 0), info.get("thumbheight", 0)
        if not height or width < 640 or width < height:
            continue

        metadata = info.get("extmetadata", {})
        license_url = metadata.get("LicenseUrl", {}).get("value", "")
        license_name = metadata.get("LicenseShortName", {}).get("value", "")
        artist = unescape(re.sub(r"<[^>]*>", "", metadata.get("Artist", {}).get("value", ""))).strip()
        image_url = thumbnail_url(info.get("thumburl", ""))
        if not image_url or not artist or not license_name or not LICENSE.fullmatch(license_url):
            continue
        if not night:
            taken = metadata.get("DateTimeOriginal", {}).get("value", "")
            hour = re.search(r"[T ](\d{2}):\d{2}", taken)
            if not DAY.search(title) and (not hour or not 9 <= int(hour[1]) <= 15):
                continue

        return {
            "image": image_url,
            "source": f"https://commons.wikimedia.org/wiki/{quote(title.replace(' ', '_'), safe=':')}",
            "artist": " ".join(artist.split()),
            "license_url": license_url,
            "license_name": license_name,
        }
    return None
