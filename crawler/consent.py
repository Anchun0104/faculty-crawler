from __future__ import annotations


_DISMISS_SCRIPT = r"""
() => {
  const labels = ['accept necessary', 'necessary only', 'reject all', 'continue without accepting'];
  const scopes = '[class*="cookie" i], [id*="cookie" i], [class*="consent" i], [id*="consent" i], [aria-label*="cookie" i], [aria-label*="consent" i], [data-consent], [data-consent-dialog], [data-cookie], [data-cookie-banner]';
  for (const root of document.querySelectorAll(scopes)) {
    for (const button of root.querySelectorAll('button, [role="button"]')) {
      const ariaLabel = (button.getAttribute('aria-label') || '').trim();
      const label = ariaLabel || (button.innerText || button.textContent || '').trim();
      const normalized = label.toLowerCase().replace(/\s+/g, ' ');
      const ariaDisabled = (button.getAttribute('aria-disabled') || '').trim().toLowerCase() === 'true';
      if (labels.includes(normalized) && !button.disabled && !ariaDisabled) { button.click(); return label; }
    }
  }
  return null;
}
"""


def dismiss_cookie_overlay(page: object) -> str | None:
    return page.evaluate(_DISMISS_SCRIPT)
