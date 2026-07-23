from __future__ import annotations

import re
from math import ceil
from time import monotonic

from crawler.models import DynamicTrace
from crawler.parsers import normalized_person_profile_urls


_LOAD_MORE_LABELS = (
    "load more",
    "load more people",
    "show more",
    "show more people",
    "show more profiles",
    "view more people",
    "display more",
    "display more people",
    "加载更多",
    "显示更多",
)


_DYNAMIC_ACTION_SCRIPT = r"""
(action) => {
  const normalizeText = (value) => (value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const challengeText = normalizeText(`${document.title || ''} ${document.body?.innerText || ''}`);
  const challengeMarkers = [
    'verify you are human',
    'security check',
    'just a moment',
    'captcha',
    'turnstile'
  ];
  if (challengeMarkers.some((marker) => challengeText.includes(marker))) {
    return {acted: false, kind: 'verification_required'};
  }

  const profileHints = new Set([
    'people', 'person', 'profile', 'profiles', 'faculty', 'staff',
    'academic-staff', 'academic_staff', 'employees', 'employee', 'directory'
  ]);
  const nonIdentityQueryKeys = new Set([
    'page', 'paged', 'pagenum', 'page_num', 'page-number', 'offset', 'start',
    'limit', 'sort', 'sortby', 'sort_by', 'order', 'orderby', 'order_by',
    'search', 'q', 'query', 'keyword', 'filter', 'filters', 'department',
    'faculty', 'school', 'college', 'unit', 'category', 'role', 'type', 'letter'
  ]);
  const identityQueryKeys = new Set([
    'id', 'key', 'page_id', 'personid', 'profileid', 'staffid', 'stref', 'investigadorid'
  ]);
  const organizationalSegments = new Set([
    'departments', 'faculties', 'institutes', 'research-groups', 'centres', 'schools'
  ]);
  const genericLastSegments = new Set([
    'directory', 'employees', 'faculty', 'people', 'person', 'profiles', 'profile', 'search', 'staff'
  ]);
  const queryProfileEndpoints = new Set([
    'person', 'persons', 'profile', 'profiles', 'people', 'employee', 'employees',
    'staff', 'faculty', 'directory', 'academic-staff', 'academic_staff'
  ]);
  const baseUrl = /^https?:/i.test(document.baseURI) ? document.baseURI : 'https://local.invalid/';
  const baseOrigin = new URL(baseUrl).origin;

  const parsedProfileUrl = (anchor) => {
    const href = anchor.getAttribute('href') || '';
    if (!href || href.startsWith('#') || /^(mailto|tel|javascript):/i.test(href)) return null;
    let url;
    try {
      url = new URL(href, baseUrl);
    } catch (_) {
      return null;
    }
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== baseOrigin) return null;
    const segments = url.pathname.toLowerCase().split('/').filter(Boolean);
    if (segments.some((segment) => organizationalSegments.has(segment))) return null;
    if (segments.some((segment) => /^(privacy|cookies?)(-(policy|notice|preferences?|settings?|options?))?$/.test(segment))) return null;

    const lastSegment = segments[segments.length - 1] || '';
    const hintedPath = segments.some((segment, index) => profileHints.has(segment) && index < segments.length - 1);
    const localeProfile = segments.length === 3 && segments[1] === 'p' && /^[a-z]{2,3}(-[a-z0-9]{2,8})*$/.test(segments[0]);
    const facProfile = segments.length === 2 && segments[0] === 'fac';
    const personDetail = url.pathname.toLowerCase().includes('person-detail');
    const pathProfile = !genericLastSegments.has(lastSegment) && (hintedPath || localeProfile || facProfile || personDetail);
    const usableQueryPairs = Array.from(url.searchParams.entries()).filter(([key, value]) => {
      const normalizedKey = key.toLowerCase();
      return value.trim() && !normalizedKey.startsWith('utm_') &&
        !['fbclid', 'gclid'].includes(normalizedKey) && !nonIdentityQueryKeys.has(normalizedKey);
    });
    const identityQuery = usableQueryPairs.length > 0 && (
      queryProfileEndpoints.has(lastSegment) ||
      usableQueryPairs.some(([key]) => identityQueryKeys.has(key.toLowerCase()))
    );
    if (!pathProfile && !identityQuery) return null;
    url.hash = '';
    for (const [key, value] of Array.from(url.searchParams.entries())) {
      const normalizedKey = key.toLowerCase();
      if (!value.trim() || normalizedKey.startsWith('utm_') || normalizedKey === 'fbclid' || normalizedKey === 'gclid' || nonIdentityQueryKeys.has(normalizedKey)) {
        url.searchParams.delete(key);
      }
    }
    url.searchParams.sort();
    url.pathname = url.pathname.replace(/\/+$/, '') || '/';
    return url.toString().toLowerCase();
  };

  const peopleUrls = (root) => new Set(
    Array.from(root.querySelectorAll('a[href]'))
      .map(parsedProfileUrl)
      .filter(Boolean)
  );
  const peopleSemanticsPattern = /(^|[\s_-])(people|person|faculty|staff|directory)([\s_-]|$)/i;
  const boundaryPattern = /(^|[\s_-])(result|results|list|listing|grid|cards)([\s_-]|$)/i;
  const elementIdentity = (element) => [
    element.id,
    element.className,
    element.getAttribute('role'),
    element.getAttribute('aria-label')
  ].filter((value) => typeof value === 'string').join(' ');
  const isTrustedPeopleScope = (scope) => {
    if (!scope || scope.matches('main, body, html')) return false;
    const identity = elementIdentity(scope);
    const role = normalizeText(scope.getAttribute('role'));
    const tag = scope.tagName.toLowerCase();
    const bounded = ['section', 'article', 'ul', 'ol', 'table', 'tbody'].includes(tag) ||
      tag.includes('-') || ['list', 'listbox', 'feed', 'region', 'grid'].includes(role) ||
      boundaryPattern.test(identity) || peopleSemanticsPattern.test(identity);
    if (!bounded) return false;
    const profileCount = peopleUrls(scope).size;
    const linkCount = scope.querySelectorAll('a[href]').length;
    const highProfileDensity = linkCount > 0 && profileCount / linkCount >= 0.5;
    return profileCount >= 2 && (peopleSemanticsPattern.test(identity) || highProfileDensity);
  };
  const observationState = window.__facultyCrawlerDynamicState || {
    control: null,
    scope: null,
    baselineProfiles: ''
  };
  observationState.currentProfiles = () => Array.from(peopleUrls(document)).sort().join('\n');
  window.__facultyCrawlerDynamicState = observationState;
  const beginObservation = (control, scope) => {
    observationState.control = control;
    observationState.scope = scope;
    observationState.baselineProfiles = observationState.currentProfiles();
  };

  const forbiddenPattern = /(^|[\s_-])(news|course|privacy|cookie|consent|navigation|nav)([\s_-]|$)/i;
  const tryLoadMoreControl = (control) => {
    const ariaDisabled = normalizeText(control.getAttribute('aria-disabled')) === 'true';
    if (control.matches(':disabled') || ariaDisabled) return {acted: false, kind: 'load_more'};
    let scope = control.parentElement;
    let forbidden = false;
    while (scope && !scope.matches('main, body, html')) {
      const scopeIdentity = elementIdentity(scope);
      if (scope.matches('nav, header, footer') || forbiddenPattern.test(scopeIdentity)) forbidden = true;
      if (!forbidden && isTrustedPeopleScope(scope)) {
        beginObservation(control, scope);
        control.click();
        return {acted: true, kind: 'load_more'};
      }
      scope = scope.parentElement;
    }
    return {acted: false, kind: 'load_more'};
  };
  window.__facultyCrawlerTryLoadMore = tryLoadMoreControl;

  if (action === 'prepare_load_more') {
    return {acted: false, kind: 'load_more'};
  }

  if (action === 'load_more') {
    const labels = new Set([
      'load more', 'load more people', 'show more', 'show more people',
      'show more profiles', 'view more people', 'display more',
      'display more people', '加载更多', '显示更多'
    ]);
    const accessibleName = (control) => {
      const labelledBy = (control.getAttribute('aria-labelledby') || '').trim().split(/\s+/).filter(Boolean);
      const referencedText = labelledBy.map((id) => {
        const referenced = document.getElementById(id);
        return referenced ? (referenced.innerText || referenced.textContent || '') : '';
      }).join(' ');
      if (normalizeText(referencedText)) return normalizeText(referencedText);
      const ariaLabel = control.getAttribute('aria-label') || '';
      if (normalizeText(ariaLabel)) return normalizeText(ariaLabel);
      return normalizeText(control.innerText || control.textContent || control.title || '');
    };
    const controls = document.querySelectorAll('button, [role="button"], a[href]');
    for (const control of controls) {
      const label = accessibleName(control);
      if (!labels.has(label)) continue;
      const result = tryLoadMoreControl(control);
      if (result.acted) return result;
    }
    return {acted: false, kind: 'load_more'};
  }

  if (action === 'scroll') {
    const candidates = Array.from(document.querySelectorAll('*'));
    const elementDepth = (element) => {
      let depth = 0;
      for (let current = element; current; current = current.parentElement) depth += 1;
      return depth;
    };
    const scrollablePeopleList = candidates.filter((element) => {
      const style = window.getComputedStyle(element);
      const remainingRange = element.scrollHeight - element.clientHeight - element.scrollTop;
      const scrollable = ['auto', 'scroll'].includes(style.overflowY) && remainingRange > 1;
      return scrollable && element.clientHeight > 0 && isTrustedPeopleScope(element);
    }).sort((left, right) => elementDepth(right) - elementDepth(left))[0];
    if (scrollablePeopleList) {
      beginObservation(null, scrollablePeopleList);
      scrollablePeopleList.scrollBy({
        top: Math.max(1, Math.floor(scrollablePeopleList.clientHeight * 0.8)),
        behavior: 'auto'
      });
      return {acted: true, kind: 'internal_scroll'};
    }

    const root = document.scrollingElement || document.documentElement;
    const viewportHeight = root.clientHeight || window.innerHeight;
    const remainingWindowRange = root.scrollHeight - viewportHeight - root.scrollTop;
    if (remainingWindowRange > 1) {
      beginObservation(null, root);
      window.scrollBy({top: Math.max(1, Math.floor(window.innerHeight * 0.8)), behavior: 'auto'});
      return {acted: true, kind: 'window_scroll'};
    }
    return {acted: false, kind: 'window_scroll'};
  }

  return {acted: false, kind: action};
}
"""


_LOAD_MORE_CANDIDATE_SCRIPT = r"""
(control) => window.__facultyCrawlerTryLoadMore(control)
"""


_DYNAMIC_OBSERVATION_SCRIPT = r"""
() => {
  const normalizeText = (value) => (value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const challengeText = normalizeText(`${document.title || ''} ${document.body?.innerText || ''}`);
  const challengeMarkers = [
    'verify you are human',
    'security check',
    'just a moment',
    'captcha',
    'turnstile'
  ];
  const challenge = challengeMarkers.some((marker) => challengeText.includes(marker));
  const state = window.__facultyCrawlerDynamicState;
  if (!state) return {challenge, settled: true};
  const control = state.control;
  const scope = state.scope;
  const busy = Boolean(scope && scope.isConnected && (
    scope.matches('[aria-busy="true"]') ||
    scope.querySelector('[aria-busy="true"], [role="progressbar"], .loading, .spinner')
  ));
  const terminalLabels = new Set([
    'all people loaded', 'all profiles loaded', 'all results loaded',
    'end of results', 'no more people', 'no more profiles', 'no more results'
  ]);
  const controlLabel = control && normalizeText(
    control.getAttribute('aria-label') || control.innerText || control.textContent || control.title || ''
  );
  const ariaDisabled = control && normalizeText(control.getAttribute('aria-disabled')) === 'true';
  const nativelyDisabled = Boolean(control && control.matches(':disabled'));
  const confirmedTerminal = Boolean(
    control && control.isConnected && !busy && (nativelyDisabled || ariaDisabled) && terminalLabels.has(controlLabel)
  );
  const profilesChanged = state.currentProfiles() !== state.baselineProfiles;
  return {challenge, settled: challenge || profilesChanged || confirmedTerminal};
}
"""


class _PlaywrightDynamicAdapter:
    def __init__(self, page: object, *, timeout_ms: int = 1000) -> None:
        self.page = page
        self.timeout_ms = timeout_ms

    def dynamic_step(
        self,
        action: str,
        *,
        deadline: float | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[str, str] | None:
        has_global_deadline = deadline is not None
        wait_budget_ms = max(0, self.timeout_ms if timeout_ms is None else timeout_ms)
        round_deadline = monotonic() + wait_budget_ms / 1000
        deadline = round_deadline if deadline is None else min(deadline, round_deadline)
        if action == "load_more" and hasattr(self.page, "get_by_role"):
            result = self._standard_load_more_action(
                deadline, enforce_deadline=has_global_deadline
            )
        else:
            result = self.page.evaluate(_DYNAMIC_ACTION_SCRIPT, action)
        kind = result.get("kind", action)
        if kind == "verification_required":
            return kind, self.page.content()
        if not result.get("acted"):
            return None
        while True:
            observation = self.page.evaluate(_DYNAMIC_OBSERVATION_SCRIPT)
            if observation.get("challenge"):
                return "verification_required", self.page.content()
            if observation.get("settled"):
                break
            remaining_ms = ceil((deadline - monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            self.page.wait_for_timeout(min(50, remaining_ms))
        return kind, self.page.content()

    def _standard_load_more_action(
        self, deadline: float, *, enforce_deadline: bool
    ) -> dict[str, object]:
        prepared = self.page.evaluate(_DYNAMIC_ACTION_SCRIPT, "prepare_load_more")
        if prepared.get("kind") == "verification_required":
            return prepared
        for role in ("button", "link"):
            for label in _LOAD_MORE_LABELS:
                candidate_pattern = re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)
                candidates = self.page.get_by_role(role, name=candidate_pattern)
                for index in range(candidates.count()):
                    if enforce_deadline and monotonic() >= deadline:
                        return {"acted": False, "kind": "load_more"}
                    result = candidates.nth(index).evaluate(_LOAD_MORE_CANDIDATE_SCRIPT)
                    if result.get("acted"):
                        return result
        return {"acted": False, "kind": "load_more"}


def collect_dynamic_snapshots(
    page: object,
    base_url: str,
    initial_html: str,
    *,
    max_clicks: int = 50,
    max_scrolls: int = 50,
    timeout_ms: int = 30000,
) -> tuple[list[str], list[DynamicTrace]]:
    deadline = monotonic() + max(0, timeout_ms) / 1000
    seen = normalized_person_profile_urls(initial_html, base_url)
    snapshots: list[str] = []
    traces: list[DynamicTrace] = []
    stop_all_actions = False

    for action, limit, unchanged_limit in (
        ("load_more", max_clicks, 2),
        ("scroll", max_scrolls, 3),
    ):
        additions: list[int] = []
        unchanged = 0
        stop_reason = "round_limit"
        for _ in range(max(0, limit)):
            if monotonic() >= deadline:
                stop_reason = "timeout"
                stop_all_actions = True
                break

            if isinstance(page, _PlaywrightDynamicAdapter):
                event = page.dynamic_step(action, deadline=deadline)
            else:
                event = page.dynamic_step(action)
            if event is None:
                if monotonic() >= deadline:
                    stop_reason = "timeout"
                    stop_all_actions = True
                else:
                    stop_reason = "control_exhausted"
                break

            kind, html = event
            if kind == "verification_required":
                stop_reason = "verification_required"
                stop_all_actions = True
                break

            urls = normalized_person_profile_urls(html, base_url)
            new_count = len(urls - seen)
            additions.append(new_count)
            if new_count:
                snapshots.append(html)
                seen.update(urls)
                unchanged = 0
            else:
                unchanged += 1

            if monotonic() >= deadline:
                stop_reason = "timeout"
                stop_all_actions = True
                break

            if unchanged >= unchanged_limit:
                stop_reason = (
                    "two_unchanged_clicks"
                    if action == "load_more"
                    else "three_unchanged_scrolls"
                )
                break

        traces.append(DynamicTrace(action, len(additions), tuple(additions), stop_reason))
        if stop_all_actions:
            break

    return snapshots, traces
