from __future__ import annotations

import gzip
import hashlib
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from faculty_workflow.adapters import AdapterRegistry
from faculty_workflow.pdf_documents import PdfDocumentError, extract_pdf_text
from faculty_workflow.session_store import ProtectedSessionStore, SessionProtectionError


USER_AGENT = "FacultyResearchCollector/1.0 (+public-academic-directory-research)"
CAPTCHA_MARKERS = (
    "verify you are human",
    "checking your browser",
    "captcha",
    "access denied",
    "cf-chl-",
)


class FetchError(RuntimeError):
    pass


class RobotsDeniedError(FetchError):
    pass


class AccessBlockedError(FetchError):
    def __init__(self, message: str, *, url: str = "") -> None:
        super().__init__(message)
        self.url = url


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    http_status: int | None
    title: str
    html: str
    text: str
    content_hash: str
    snapshot_path: Path
    dynamic_actions: tuple[str, ...] = ()


@dataclass
class InteractiveVerification:
    hostname: str
    url: str
    playwright: object
    browser: object
    context: object
    page: object


class PageFetcher:
    def __init__(
        self,
        *,
        timeout_ms: int = 30000,
        min_domain_interval: float = 1.0,
        max_snapshot_bytes: int = 5_000_000,
        max_pdf_bytes: int = 20_000_000,
        headless: bool = True,
        max_attempts: int = 3,
        max_dynamic_clicks: int = 20,
        max_dynamic_scrolls: int = 20,
        robots_factory: type[RobotFileParser] = RobotFileParser,
        adapter_registry: AdapterRegistry | None = None,
        session_store: ProtectedSessionStore | None = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.min_domain_interval = min_domain_interval
        self.max_snapshot_bytes = max_snapshot_bytes
        self.max_pdf_bytes = max(1, max_pdf_bytes)
        self.headless = headless
        self.max_attempts = max(1, max_attempts)
        self.max_dynamic_clicks = max(0, max_dynamic_clicks)
        self.max_dynamic_scrolls = max(0, max_dynamic_scrolls)
        self.robots_factory = robots_factory
        self.adapter_registry = adapter_registry or AdapterRegistry()
        self.session_store = session_store
        self._last_request: dict[str, float] = {}
        self._interactive: InteractiveVerification | None = None

    def fetch(
        self,
        url: str,
        snapshot_dir: str | Path,
        *,
        expand_directory: bool = False,
    ) -> FetchedPage:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise FetchError(f"Invalid URL: {url}")
        self._check_robots(url)
        self._throttle(parsed.hostname or parsed.netloc)
        if parsed.path.casefold().endswith(".pdf"):
            return self._fetch_pdf(url, snapshot_dir)

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FetchError("Playwright is not installed") from exc

        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                with sync_playwright() as playwright:
                    browser = self._launch_browser(playwright, headless=self.headless)
                    context = None
                    try:
                        storage_state = self._load_session(parsed.hostname or parsed.netloc)
                        context = browser.new_context(user_agent=USER_AGENT, storage_state=storage_state)
                        page = context.new_page()
                        page.set_default_timeout(self.timeout_ms)
                        response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        try:
                            # Directory pages may populate cards asynchronously and need the
                            # longer settling window. Personal pages are already usable after
                            # DOMContentLoaded; analytics requests otherwise make every profile
                            # pay the full ten-second timeout on some university portals.
                            idle_timeout = 10000 if expand_directory else 2500
                            page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, idle_timeout))
                        except PlaywrightTimeoutError:
                            pass
                        page.wait_for_timeout(500)
                        dynamic_actions = self._expand_directory(page) if expand_directory else ()
                        html = self.adapter_registry.preprocess_html(page.url, page.content())
                        title = page.title()
                        final_url = page.url
                        status = response.status if response else None
                    finally:
                        if context is not None:
                            context.close()
                        browser.close()
            except PlaywrightError as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts:
                    time.sleep(retry_delay_seconds(attempt))
                    continue
                raise FetchError(str(exc)) from exc

            lowered = html.casefold()
            if any(marker in lowered for marker in CAPTCHA_MARKERS):
                raise AccessBlockedError("Page requires human verification or denies access", url=url)
            if status is not None and status >= 500 and attempt + 1 < self.max_attempts:
                time.sleep(retry_delay_seconds(attempt))
                continue
            break
        else:  # defensive: the loop always returns or breaks above
            raise FetchError(str(last_error or "Unable to fetch page"))

        if status is not None and status >= 400:
            raise FetchError(f"HTTP {status}")

        raw = html.encode("utf-8", errors="replace")
        digest = hashlib.sha256(raw).hexdigest()
        snapshot_root = Path(snapshot_dir)
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_root / f"{digest}.html.gz"
        if not snapshot_path.exists():
            with gzip.open(snapshot_path, "wb") as handle:
                handle.write(raw[: self.max_snapshot_bytes])
        return FetchedPage(
            requested_url=url,
            final_url=final_url,
            http_status=status,
            title=title,
            html=html,
            text=html_to_text(html),
            content_hash=digest,
            snapshot_path=snapshot_path,
            dynamic_actions=dynamic_actions,
        )

    def _fetch_pdf(self, url: str, snapshot_dir: str | Path) -> FetchedPage:
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
        )
        try:
            with urlopen(request, timeout=max(1.0, self.timeout_ms / 1000)) as response:
                status = int(getattr(response, "status", 200) or 200)
                final_url = str(response.geturl())
                content_type = str(response.headers.get("Content-Type", "")).casefold()
                data = response.read(self.max_pdf_bytes + 1)
        except HTTPError as exc:
            raise FetchError(f"HTTP {exc.code}") from exc
        except (OSError, URLError) as exc:
            raise FetchError(f"PDF download failed: {exc}") from exc
        if not 200 <= status < 300:
            raise FetchError(f"HTTP {status}")
        if len(data) > self.max_pdf_bytes:
            raise FetchError("PDF exceeds maximum size")
        if "application/pdf" not in content_type and not data.startswith(b"%PDF-"):
            raise FetchError("Response is not a PDF")
        try:
            metadata_title, text = extract_pdf_text(data)
        except PdfDocumentError as exc:
            raise FetchError(str(exc)) from exc
        digest = hashlib.sha256(data).hexdigest()
        snapshot_root = Path(snapshot_dir)
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_root / f"{digest}.pdf"
        if not snapshot_path.exists():
            snapshot_path.write_bytes(data)
        fallback_title = Path(urlparse(final_url).path).name or "PDF"
        return FetchedPage(
            requested_url=url,
            final_url=final_url,
            http_status=status,
            title=metadata_title or fallback_title,
            html="",
            text=text,
            content_hash=digest,
            snapshot_path=snapshot_path,
        )

    def _expand_directory(self, page: object) -> tuple[str, ...]:
        """Expand only bounded, user-visible directory controls in the active page.

        The actions intentionally do not follow arbitrary links or bypass access controls.
        Each step must add a person-like link; otherwise it stops after a small number
        of unchanged rounds.
        """
        actions: list[str] = []
        unchanged = 0
        for _ in range(self.max_dynamic_clicks):
            result = page.evaluate(_LOAD_MORE_SCRIPT)
            if result.get("blocked"):
                raise AccessBlockedError("Directory requires human verification", url=str(getattr(page, "url", "")))
            if not result.get("acted"):
                break
            page.wait_for_timeout(500)
            if page.evaluate(_PERSON_LINK_COUNT_SCRIPT) > int(result.get("profile_count", 0)):
                actions.append("load_more")
                unchanged = 0
            else:
                unchanged += 1
            if unchanged >= 2:
                break

        unchanged = 0
        for _ in range(self.max_dynamic_scrolls):
            result = page.evaluate(_SCROLL_SCRIPT)
            if result.get("blocked"):
                raise AccessBlockedError("Directory requires human verification", url=str(getattr(page, "url", "")))
            if not result.get("acted"):
                break
            page.wait_for_timeout(400)
            if page.evaluate(_PERSON_LINK_COUNT_SCRIPT) > int(result.get("profile_count", 0)):
                actions.append(str(result.get("kind") or "scroll"))
                unchanged = 0
            else:
                unchanged += 1
            if unchanged >= 3:
                break
        return tuple(actions)

    def begin_interactive_verification(self, url: str) -> None:
        """Open one visible browser for a user to complete lawful site verification."""
        if self._interactive is not None:
            raise FetchError("A verification browser is already open")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise FetchError("Invalid verification URL")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FetchError("Playwright is not installed") from exc
        runtime = sync_playwright().start()
        browser = self._launch_browser(runtime, headless=False)
        context = browser.new_context(
            user_agent=USER_AGENT,
            storage_state=self._load_session(parsed.hostname),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._interactive = InteractiveVerification(parsed.hostname, url, runtime, browser, context, page)

    def finish_interactive_verification(self) -> str:
        """Save the state only when the visible page is no longer a challenge page."""
        active = self._interactive
        if active is None:
            raise FetchError("No verification browser is open")
        try:
            html = active.page.content()
            if any(marker in html.casefold() for marker in CAPTCHA_MARKERS):
                raise AccessBlockedError("Verification is still required", url=active.page.url)
            if self.session_store is None:
                raise SessionProtectionError("Encrypted session storage is not configured")
            self.session_store.save(active.hostname, active.context.storage_state())
            return str(active.page.url)
        finally:
            active.context.close()
            active.browser.close()
            active.playwright.stop()
            self._interactive = None

    def cancel_interactive_verification(self) -> None:
        active = self._interactive
        if active is None:
            return
        active.context.close()
        active.browser.close()
        active.playwright.stop()
        self._interactive = None

    def _load_session(self, hostname: str) -> dict | None:
        if self.session_store is None:
            return None
        return self.session_store.load(hostname)

    @staticmethod
    def _launch_browser(playwright: object, *, headless: bool) -> object:
        """Prefer Playwright Chromium; use installed Edge only if it is absent."""
        try:
            return playwright.chromium.launch(headless=headless)
        except Exception as chromium_error:
            if "Executable doesn't exist" not in str(chromium_error):
                raise
            try:
                return playwright.chromium.launch(headless=headless, channel="msedge")
            except Exception:
                raise chromium_error

    def _check_robots(self, url: str) -> None:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = self.robots_factory()
        parser.set_url(robots_url)
        try:
            parser.read()
        except OSError:
            return
        if not parser.can_fetch(USER_AGENT, url):
            raise RobotsDeniedError(f"robots.txt disallows this URL: {url}")

    def _throttle(self, domain: str) -> None:
        now = time.monotonic()
        remaining = self.min_domain_interval - (now - self._last_request.get(domain, 0.0))
        if remaining > 0:
            time.sleep(remaining)
        self._last_request[domain] = time.monotonic()


def retry_delay_seconds(attempt: int) -> float:
    """Bounded exponential backoff for transient browser and 5xx errors."""
    return float(min(8, 2 ** max(0, attempt)))


_LOAD_MORE_SCRIPT = r"""
() => {
  const text = (node) => (node.getAttribute('aria-label') || node.innerText || node.textContent || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const body = `${document.title || ''} ${document.body?.innerText || ''}`.toLowerCase();
  if (['captcha', 'verify you are human', 'security check', 'turnstile'].some(marker => body.includes(marker))) return {blocked: true};
  const profileCount = (root = document) => [...root.querySelectorAll('a[href]')].filter(link => {
    try { return /\/(people|person|profile|faculty|staff|employees?|researchers?)(\/|$)/i.test(new URL(link.href, document.baseURI).pathname); }
    catch (_) { return false; }
  }).length;
  const before = profileCount();
  const labels = new Set(['load more', 'load more people', 'show more', 'show more people', 'view more people', 'display more', '加载更多', '显示更多']);
  for (const control of document.querySelectorAll('button, [role="button"], a[href]')) {
    if (!labels.has(text(control)) || control.disabled || control.getAttribute('aria-disabled') === 'true') continue;
    let scope = control.parentElement;
    while (scope && scope !== document.body) {
      if (profileCount(scope) >= 2 || /people|faculty|staff|directory|results|listing/i.test(`${scope.id} ${scope.className}`)) break;
      scope = scope.parentElement;
    }
    if (!scope || scope === document.body) continue;
    control.click();
    return {acted: true, profile_count: before};
  }
  return {acted: false};
}
"""


_SCROLL_SCRIPT = r"""
() => {
  const body = `${document.title || ''} ${document.body?.innerText || ''}`.toLowerCase();
  if (['captcha', 'verify you are human', 'security check', 'turnstile'].some(marker => body.includes(marker))) return {blocked: true};
  const profileCount = () => [...document.querySelectorAll('a[href]')].filter(link => {
    try { return /\/(people|person|profile|faculty|staff|employees?|researchers?)(\/|$)/i.test(new URL(link.href, document.baseURI).pathname); }
    catch (_) { return false; }
  }).length;
  const before = profileCount();
  const scrollable = [...document.querySelectorAll('*')].find(node => {
    const style = getComputedStyle(node);
    return ['auto', 'scroll'].includes(style.overflowY) && node.scrollHeight > node.clientHeight + 4 && /people|faculty|staff|directory|results|listing/i.test(`${node.id} ${node.className}`);
  });
  if (scrollable) {
    const oldTop = scrollable.scrollTop;
    scrollable.scrollBy(0, Math.max(1, Math.floor(scrollable.clientHeight * 0.8)));
    return {acted: scrollable.scrollTop !== oldTop, profile_count: before, kind: 'internal_scroll'};
  }
  const root = document.scrollingElement || document.documentElement;
  if (root.scrollTop + root.clientHeight >= root.scrollHeight - 4) return {acted: false};
  const oldTop = root.scrollTop;
  window.scrollBy(0, Math.max(1, Math.floor(window.innerHeight * 0.8)));
  return {acted: root.scrollTop !== oldTop, profile_count: before, kind: 'window_scroll'};
}
"""


_PERSON_LINK_COUNT_SCRIPT = r"""
() => [...document.querySelectorAll('a[href]')].filter(link => {
  try { return /\/(people|person|profile|faculty|staff|employees?|researchers?)(\/|$)/i.test(new URL(link.href, document.baseURI).pathname); }
  catch (_) { return false; }
}).length
"""


class _VisibleTextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html or "")
    return re.sub(r"\s+", " ", "\n".join(parser.parts)).strip()


def url_is_on_domain(url: str, domain: str) -> bool:
    hostname = (urlparse(url).hostname or "").casefold().rstrip(".")
    expected = (domain or "").casefold().strip().rstrip(".")
    return bool(expected and (hostname == expected or hostname.endswith(f".{expected}")))
