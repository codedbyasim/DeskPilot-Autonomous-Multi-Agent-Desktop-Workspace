"""
DeskPilot — Web Research Tools
Provides resilient multi-engine search (DuckDuckGo, Bing, Wikipedia)
and smart article content extraction with Jina Reader AI fallback.
"""

from strands import tool
import requests
import re
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from typing import List, Dict, Optional
from backend.config.settings import MAX_RESEARCH_SOURCES, REQUEST_TIMEOUT
from backend.utils.logger import get_logger

logger = get_logger("tools.web")

# Modern browser headers with anti-bot bypass parameters
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _clean_article_text(soup: BeautifulSoup) -> str:
    """
    Intelligently extracts the primary article / content body from HTML,
    stripping navigation, footers, ads, cookie notices, and sidebar clutter.
    """
    # 1. Decompose noisy script/style/media tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                      "noscript", "iframe", "svg", "form", "button", "dialog"]):
        tag.decompose()

    # 2. Decompose common boilerplate containers (ads, cookies, shares, sidebars)
    unwanted_patterns = re.compile(
        r"cookie|banner|ad-|advertisement|popup|modal|sidebar|social-share|"
        r"share-button|newsletter|related-post|comment-section|disclaimer",
        re.I
    )
    for elem in soup.find_all(attrs={"class": unwanted_patterns}):
        elem.decompose()
    for elem in soup.find_all(attrs={"id": unwanted_patterns}):
        elem.decompose()

    # 3. Locate the primary content container
    content_candidates = [
        soup.find("article"),
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("div", id="mw-content-text"),  # Wikipedia
        soup.find("div", class_=re.compile(r"article[-_]body|post[-_]content|entry[-_]content|main[-_]content", re.I)),
        soup.find("div", id=re.compile(r"content|main|article", re.I)),
    ]

    target = None
    for cand in content_candidates:
        if cand and len(cand.get_text(strip=True)) > 250:
            target = cand
            break

    if not target:
        target = soup.body or soup

    # 4. Extract structured text blocks (headings, paragraphs, lists)
    text_blocks = []
    for elem in target.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        txt = elem.get_text(" ", strip=True)
        # Remove citation brackets like [1], [12]
        txt = re.sub(r"\[\d+\]", "", txt).strip()
        if len(txt) > 25:
            if elem.name in ["h1", "h2", "h3", "h4"]:
                text_blocks.append(f"\n### {txt}\n")
            elif elem.name == "li":
                text_blocks.append(f"• {txt}")
            elif elem.name == "blockquote":
                text_blocks.append(f"> {txt}")
            else:
                text_blocks.append(txt)

    if text_blocks and len("\n".join(text_blocks)) > 200:
        return "\n\n".join(text_blocks)

    # 5. Fallback: clean paragraph lines
    raw = target.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in raw.splitlines() if len(l.strip()) > 20]
    return "\n".join(lines)


def _search_duckduckgo_ddgs(query: str, max_results: int) -> List[Dict[str, str]]:
    """Primary search via DuckDuckGo python package."""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        logger.warning(f"DDGS search exception: {e}")
    return results


def _search_duckduckgo_html(query: str, max_results: int) -> List[Dict[str, str]]:
    """Secondary search via direct DuckDuckGo HTML endpoint."""
    results = []
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for result_div in soup.select(".web-result")[:max_results]:
                title_tag = result_div.select_one(".result__title a")
                snippet_tag = result_div.select_one(".result__snippet")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    url = title_tag.get("href", "")
                    snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                    if url and title:
                        results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as e:
        logger.warning(f"DuckDuckGo HTML fallback exception: {e}")
    return results


def _search_bing_html(query: str, max_results: int) -> List[Dict[str, str]]:
    """Tertiary search via Bing HTML."""
    results = []
    try:
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for li in soup.select("li.b_algo")[:max_results]:
                h2 = li.select_one("h2 a")
                p = li.select_one("p")
                if h2:
                    title = h2.get_text(strip=True)
                    url = h2.get("href", "")
                    snippet = p.get_text(strip=True) if p else ""
                    if title and url and url.startswith("http"):
                        results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as e:
        logger.warning(f"Bing HTML fallback exception: {e}")
    return results


def _search_wikipedia_api(query: str, max_results: int) -> List[Dict[str, str]]:
    """Quaternary fallback via Wikipedia OpenSearch API."""
    results = []
    try:
        wiki_headers = {"User-Agent": "DeskPilot/2.0 (hackathon@deskpilot.internal)"}
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": query, "limit": max_results, "format": "json"},
            headers=wiki_headers,
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 4:
                titles = data[1]
                snippets = data[2]
                urls = data[3]
                for t, s, u in zip(titles, snippets, urls):
                    if t and u:
                        results.append({"title": t, "url": u, "snippet": s or f"Wikipedia article on {t}"})
    except Exception as e:
        logger.warning(f"Wikipedia OpenSearch exception: {e}")
    return results


@tool
def search_web(query: str, max_results: int = MAX_RESEARCH_SOURCES) -> str:
    """
    Search the live web using a multi-engine fallback network (DuckDuckGo, Bing, Wikipedia).
    Returns real verified URLs, titles, and snippets.

    Args:
        query: The search query string
        max_results: Maximum number of results to return (default 5)

    Returns:
        Formatted string with titles, URLs, and snippets
    """
    clean_query = query.strip()
    logger.info(f"Searching web: '{clean_query}' (max {max_results} results)")

    # 1. Primary: DuckDuckGo DDGS
    results = _search_duckduckgo_ddgs(clean_query, max_results)

    # 2. Secondary: DuckDuckGo HTML
    if not results:
        logger.info("Trying DuckDuckGo HTML fallback...")
        results = _search_duckduckgo_html(clean_query, max_results)

    # 3. Tertiary: Bing HTML
    if not results:
        logger.info("Trying Bing HTML fallback...")
        results = _search_bing_html(clean_query, max_results)

    # 4. Quaternary: Wikipedia OpenSearch
    if not results:
        logger.info("Trying Wikipedia OpenSearch fallback...")
        results = _search_wikipedia_api(clean_query, max_results)

    if not results:
        return f"No live search results found for '{clean_query}'. Please refine query terms."

    output = f"Search Results for: '{clean_query}'\n{'='*60}\n\n"
    for i, r in enumerate(results[:max_results], 1):
        output += f"{i}. {r['title']}\n"
        output += f"   URL: {r['url']}\n"
        output += f"   {r['snippet']}\n\n"

    logger.info(f"Found {len(results)} live results for '{clean_query}'")
    return output


@tool
def read_webpage(url: str, max_chars: int = 8000) -> str:
    """
    Fetch and extract clean, readable text content from a webpage URL.
    Uses intelligent article DOM filtering with automatic Jina Reader AI fallback for JS-heavy or blocked pages.

    Args:
        url: The URL to read
        max_chars: Maximum characters to return (default 8000)

    Returns:
        Cleaned markdown / text content from the webpage
    """
    clean_url = url.strip()
    logger.info(f"Reading webpage: {clean_url}")

    extracted_content = ""

    # Strategy 1: Direct requests with article DOM extraction
    try:
        resp = requests.get(clean_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            extracted_content = _clean_article_text(soup)
    except Exception as e:
        logger.warning(f"Direct page read failed for {clean_url}: {e}")

    # Strategy 2: If direct read is blocked (403/401/429) or empty (< 250 chars due to client-side JS), use Jina Reader
    if not extracted_content or len(extracted_content) < 250:
        try:
            logger.info(f"Using Jina Reader AI fallback for: {clean_url}")
            jina_url = f"https://r.jina.ai/{clean_url}"
            jina_resp = requests.get(
                jina_url,
                headers={"User-Agent": "DeskPilot/2.0 (hackathon@deskpilot.internal)"},
                timeout=REQUEST_TIMEOUT + 5
            )
            if jina_resp.status_code == 200 and len(jina_resp.text) > 150:
                extracted_content = jina_resp.text
                logger.info(f"Jina Reader extracted {len(extracted_content)} chars from {clean_url}")
        except Exception as je:
            logger.warning(f"Jina Reader fallback failed: {je}")

    if not extracted_content:
        return f"Error: Could not extract readable content from '{clean_url}'. The page may require authentication or be unreachable."

    result = extracted_content[:max_chars]
    if len(extracted_content) > max_chars:
        result += f"\n\n[... content truncated at {max_chars} chars ...]"

    logger.info(f"Successfully read {len(result)} chars from {clean_url}")
    return f"Content from: {clean_url}\n{'='*60}\n{result}"


@tool
def search_and_read(query: str, num_sources: int = MAX_RESEARCH_SOURCES) -> str:
    """
    Execute a comprehensive research sweep: search the web and read the top authoritative sources.
    Returns structured evidence with source URLs and citations.

    Args:
        query: Research query topic
        num_sources: Number of independent sources to analyze (default 5)

    Returns:
        Combined evidence synthesis with citations
    """
    logger.info(f"Starting comprehensive research sweep: '{query}' ({num_sources} sources)")

    # 1. Run multi-engine search
    results = _search_duckduckgo_ddgs(query, num_sources)
    if not results:
        results = _search_duckduckgo_html(query, num_sources)
    if not results:
        results = _search_bing_html(query, num_sources)
    if not results:
        results = _search_wikipedia_api(query, num_sources)

    if not results:
        return f"Research sweep on '{query}': No live results found. Please check internet connection or query terms."

    combined = f"Comprehensive Web Research Evidence: '{query}'\n{'='*65}\n\n"
    sources_citation = []

    # 2. Extract content from each verified source
    valid_sources_count = 0
    for i, item in enumerate(results[:num_sources], 1):
        url = item.get("url", "")
        title = item.get("title", f"Source {i}")
        snippet = item.get("snippet", "")

        if not url:
            continue

        sources_citation.append(f"[{i}] {title} — {url}")
        combined += f"\n--- Source {i}: {title} ---\n"
        combined += f"URL: {url}\n"

        # Read full content
        content = read_webpage(url, max_chars=3500)
        # Strip header banner from read_webpage
        if "===\n" in content:
            body = content.split("===\n", 1)[1]
        else:
            body = content

        if body and not body.startswith("Error:"):
            combined += body + "\n"
            valid_sources_count += 1
        else:
            combined += f"[Note: Direct text unavailable; extracted snippet]:\n{snippet}\n"

    combined += f"\n\n{'='*65}\nAUTHORITATIVE SOURCES REFERENCED:\n"
    combined += "\n".join(sources_citation)

    logger.info(f"Research sweep complete: {valid_sources_count}/{len(results[:num_sources])} sources extracted")
    return combined
