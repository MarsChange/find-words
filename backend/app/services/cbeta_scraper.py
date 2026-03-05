"""CBETA online scraper using Selenium in headless mode.

Automatically detects the user's default browser and uses the
corresponding WebDriver (Chrome, Firefox, Edge, or Safari).
"""

import logging
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from app.config import settings

logger = logging.getLogger(__name__)

_CBETA_SEARCH_URL = "https://cbetaonline.dila.edu.tw/search/"
_WAIT_TIMEOUT = 20  # seconds

# Only allow CJK characters, basic Latin letters/digits, and common punctuation
_QUERY_SANITIZE_RE = re.compile(
    r'[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
    r'\u3000-\u303fa-zA-Z0-9\s]'
)

# Browser name → keyword patterns used to identify it
_BROWSER_PATTERNS: dict[str, list[str]] = {
    "chrome":  ["chrome", "google chrome", "chromium", "google-chrome"],
    "firefox": ["firefox", "mozilla firefox"],
    "edge":    ["edge", "microsoft edge", "msedge"],
    "safari":  ["safari"],
}


@dataclass
class CBETAResult:
    title: str
    sutra_id: str
    snippets: list[str]
    dynasty: str = ""
    author: str = ""


# ── Default browser detection ──────────────────────────────────────────────


def _detect_default_browser_darwin() -> str:
    """Detect default browser on macOS via LaunchServices."""
    try:
        raw = subprocess.check_output(
            [
                "defaults", "read",
                "com.apple.LaunchServices/com.apple.launchservices.secure",
                "LSHandlers",
            ],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        )
        # Find the handler for http scheme
        # The plist output contains blocks with LSHandlerURLScheme = http;
        # followed by LSHandlerRoleAll = "bundle.id";
        for m in re.finditer(
            r'LSHandlerURLScheme\s*=\s*https?;.*?LSHandlerRoleAll\s*=\s*"([^"]+)"',
            raw, re.DOTALL,
        ):
            bundle = m.group(1).lower()
            if "chrome" in bundle:
                return "chrome"
            if "firefox" in bundle:
                return "firefox"
            if "edge" in bundle or "msedge" in bundle:
                return "edge"
            if "safari" in bundle:
                return "safari"
    except Exception:
        pass

    # Fallback: use the open command to check
    try:
        raw = subprocess.check_output(
            ["plutil", "-convert", "json", "-o", "-",
             "/Users/" + __import__("os").getlogin()
             + "/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

    return ""


def _detect_default_browser_linux() -> str:
    """Detect default browser on Linux via xdg-settings."""
    try:
        raw = subprocess.check_output(
            ["xdg-settings", "get", "default-web-browser"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        ).strip().lower()
        for name, patterns in _BROWSER_PATTERNS.items():
            if any(p in raw for p in patterns):
                return name
    except Exception:
        pass
    return ""


def _detect_default_browser_windows() -> str:
    """Detect default browser on Windows via registry."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
            prog_id = prog_id.lower()
            if "chrome" in prog_id:
                return "chrome"
            if "firefox" in prog_id or "firefoxurl" in prog_id:
                return "firefox"
            if "edge" in prog_id or "msedge" in prog_id:
                return "edge"
    except Exception:
        pass
    return ""


@lru_cache(maxsize=1)
def detect_default_browser() -> str:
    """Return the default browser name: 'chrome', 'firefox', 'edge', 'safari', or ''."""
    system = platform.system()
    if system == "Darwin":
        result = _detect_default_browser_darwin()
    elif system == "Linux":
        result = _detect_default_browser_linux()
    elif system == "Windows":
        result = _detect_default_browser_windows()
    else:
        result = ""

    # Fallback: probe which browser binary is available
    if not result:
        result = _probe_available_browser()

    if result:
        logger.info("Detected default browser: %s", result)
    else:
        logger.warning("Could not detect default browser, falling back to Chrome")
    return result


def _probe_available_browser() -> str:
    """Check which browser binary exists on PATH as a last resort."""
    probes = [
        ("chrome", ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]),
        ("firefox", ["firefox"]),
        ("edge", ["microsoft-edge", "microsoft-edge-stable", "msedge"]),
    ]
    system = platform.system()
    if system == "Darwin":
        # Also check macOS .app bundles
        import os
        app_checks = {
            "chrome": "/Applications/Google Chrome.app",
            "firefox": "/Applications/Firefox.app",
            "edge": "/Applications/Microsoft Edge.app",
            "safari": "/Applications/Safari.app",
        }
        for name, path in app_checks.items():
            if os.path.isdir(path):
                return name

    for name, binaries in probes:
        for b in binaries:
            if shutil.which(b):
                return name
    return ""


# ── WebDriver creation ─────────────────────────────────────────────────────

_HEADLESS_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--lang=zh-TW",
]


def _create_chrome_driver(headless: bool) -> webdriver.Chrome:
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    for arg in _HEADLESS_ARGS:
        opts.add_argument(arg)
    svc_kwargs = {}
    if settings.chrome_driver_path:
        svc_kwargs["executable_path"] = settings.chrome_driver_path
    return webdriver.Chrome(service=Service(**svc_kwargs), options=opts)


def _create_firefox_driver(headless: bool) -> webdriver.Firefox:
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    opts = Options()
    if headless:
        opts.add_argument("-headless")
    opts.set_preference("intl.accept_languages", "zh-TW")
    return webdriver.Firefox(service=Service(), options=opts)


def _create_edge_driver(headless: bool) -> webdriver.Edge:
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    for arg in _HEADLESS_ARGS:
        opts.add_argument(arg)
    return webdriver.Edge(service=Service(), options=opts)


def _create_safari_driver(headless: bool) -> webdriver.Safari:
    # Safari doesn't support headless mode natively
    from selenium.webdriver.safari.service import Service
    return webdriver.Safari(service=Service())


_DRIVER_FACTORIES = {
    "chrome":  _create_chrome_driver,
    "firefox": _create_firefox_driver,
    "edge":    _create_edge_driver,
    "safari":  _create_safari_driver,
}


def _create_driver() -> webdriver.Remote:
    """Create a headless WebDriver using the user's default browser."""
    headless = settings.headless
    browser = detect_default_browser()

    # Try the detected browser first, then fall back to others
    order = [browser] if browser else []
    for name in _DRIVER_FACTORIES:
        if name not in order:
            order.append(name)

    last_error = None
    for name in order:
        factory = _DRIVER_FACTORIES.get(name)
        if not factory:
            continue
        try:
            driver = factory(headless)
            logger.info("Using %s WebDriver", name)
            return driver
        except Exception as e:
            logger.debug("Failed to create %s driver: %s", name, e)
            last_error = e
            continue

    raise WebDriverException(
        f"No supported browser/driver found. Tried: {order}. "
        f"Last error: {last_error}"
    )


# ── Parsing helpers ────────────────────────────────────────────────────────


def _parse_dynasty_author(info_text: str) -> tuple[str, str]:
    """Parse dynasty and author from text like '東晉 法顯譯 (作品時間：416~418)'."""
    dynasty = ""
    author = ""
    if not info_text:
        return dynasty, author
    # Remove parenthesized content like (作品時間：416~418)
    cleaned = re.sub(r'\(.*?\)', '', info_text).strip()
    parts = cleaned.split(None, 1)
    if len(parts) >= 2:
        dynasty = parts[0].strip()
        author = parts[1].strip()
    elif len(parts) == 1:
        dynasty = parts[0].strip()
    return dynasty, author


# ── Main search function ──────────────────────────────────────────────────


def search_cbeta(query: str, max_results: int = 20) -> list[CBETAResult]:
    """
    Search CBETA online and scrape results.

    Args:
        query: Search term (traditional Chinese preferred).
        max_results: Maximum number of results to return.

    Returns:
        List of CBETAResult with title, sutra_id, snippet, dynasty, and author.
    """
    driver = None
    results: list[CBETAResult] = []
    try:
        driver = _create_driver()
        # Sanitize and URL-encode the query to prevent injection
        sanitized = _QUERY_SANITIZE_RE.sub("", query).strip()
        if not sanitized:
            return results
        url = f"{_CBETA_SEARCH_URL}?q={quote(sanitized)}&lang=zh"
        driver.get(url)

        # Wait for the search result list to load
        WebDriverWait(driver, _WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul#search-result-area"))
        )

        # Each result is a <li class="list-group-item"> inside the result list
        items = driver.find_elements(
            By.CSS_SELECTOR, "ul#search-result-area > li.list-group-item"
        )

        for item in items[:max_results]:
            try:
                # Title: <span class="search-results-title-juan">
                title = ""
                title_el = item.find_elements(
                    By.CSS_SELECTOR, "span.search-results-title-juan"
                )
                if title_el:
                    title = title_el[0].text.strip()

                # Extract sutra ID from the title
                sutra_id = ""
                id_match = re.match(r'([A-Z]+\d+)', title)
                if id_match:
                    sutra_id = id_match.group(1)

                # Dynasty/author info: <span class="text-secondary small">
                dynasty = ""
                author = ""
                info_el = item.find_elements(
                    By.CSS_SELECTOR, "span.text-secondary.small"
                )
                if info_el:
                    info_text = info_el[0].text.strip()
                    dynasty, author = _parse_dynasty_author(info_text)

                # Text snippets: <div class="pr-5 listtxt">
                snippet_els = item.find_elements(
                    By.CSS_SELECTOR, "div.pr-5.listtxt"
                )
                snippets = [el.text.strip() for el in snippet_els if el.text.strip()]

                if title or snippets:
                    results.append(CBETAResult(
                        title=title,
                        sutra_id=sutra_id,
                        snippets=snippets,
                        dynasty=dynasty,
                        author=author,
                    ))
            except Exception:
                logger.debug("Skipping malformed result item", exc_info=True)
                continue

    except TimeoutException:
        logger.warning("CBETA search timed out for query: %s", query)
    except WebDriverException:
        logger.error("WebDriver error during CBETA search", exc_info=True)
    except Exception:
        logger.exception("Unexpected error during CBETA search")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return results
