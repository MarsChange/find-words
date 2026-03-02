"""CBETA online scraper using Selenium in headless mode."""

import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from app.config import settings

logger = logging.getLogger(__name__)

_CBETA_SEARCH_URL = "https://cbetaonline.dila.edu.tw/search/"
_WAIT_TIMEOUT = 15  # seconds

# Only allow CJK characters, basic Latin letters/digits, and common punctuation
_QUERY_SANITIZE_RE = re.compile(r'[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
                                 r'\u3000-\u303fa-zA-Z0-9\s]')


@dataclass
class CBETAResult:
    title: str
    sutra_id: str
    snippet: str


def _create_driver() -> webdriver.Chrome:
    """Create a headless Chrome WebDriver instance."""
    opts = Options()
    if settings.headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--lang=zh-TW")

    service_kwargs = {}
    if settings.chrome_driver_path:
        service_kwargs["executable_path"] = settings.chrome_driver_path
    service = Service(**service_kwargs)

    return webdriver.Chrome(service=service, options=opts)


def search_cbeta(query: str, max_results: int = 20) -> list[CBETAResult]:
    """
    Search CBETA online and scrape results.

    Args:
        query: Search term (traditional Chinese preferred).
        max_results: Maximum number of results to return.

    Returns:
        List of CBETAResult with title, sutra_id, and snippet.
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

        # Wait for search results container to load
        WebDriverWait(driver, _WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".js-search-results, .search-results, #search-results"))
        )

        # Try multiple possible selectors for result items
        items = driver.find_elements(By.CSS_SELECTOR, ".search-result-item, .result-item, .list-group-item")
        if not items:
            items = driver.find_elements(By.CSS_SELECTOR, "[class*='result']")

        for item in items[:max_results]:
            try:
                # Extract title
                title_el = item.find_elements(By.CSS_SELECTOR, "h3, h4, .title, a")
                title = title_el[0].text.strip() if title_el else ""

                # Extract sutra ID
                sutra_el = item.find_elements(By.CSS_SELECTOR, ".sutra-id, .text-muted, small")
                sutra_id = sutra_el[0].text.strip() if sutra_el else ""

                # Extract snippet
                snippet_el = item.find_elements(By.CSS_SELECTOR, ".snippet, .context, p")
                snippet = snippet_el[0].text.strip() if snippet_el else item.text.strip()

                if title or snippet:
                    results.append(CBETAResult(
                        title=title,
                        sutra_id=sutra_id,
                        snippet=snippet,
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
