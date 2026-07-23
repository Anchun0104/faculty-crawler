# Anti-Crawler Resilience Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved local, non-AI anti-crawler recovery workflow as four independently reviewable milestones.

**Architecture:** Keep `crawler/parsers.py` as the extraction engine. Add focused modules around it for persisted task state, page classification, recovery actions, human verification, protected sessions, diagnostics, and desktop presentation.

**Tech Stack:** Python 3.11+, Playwright Chromium, Tkinter/ttk, OpenPyXL, standard-library `unittest`, Windows DPAPI, PyInstaller, Inno Setup.

## Global Constraints

- The first stage must not call AI services or require an AI account or API key.
- Never automate CAPTCHA solving, proxy rotation, fingerprint spoofing, login bypass, or access-control bypass.
- Crawl one task per site at a time and use bounded retries.
- Human verification must not block unrelated batch tasks.
- Site sessions expire after 30 days and must be removable per site or all at once.
- Reports must exclude cookies, passwords, authorization headers, tokens, Feishu credentials, and private page bodies.
- Feishu submission is assisted manual upload; no Feishu API or administrator permission.
- Keep `crawler/parsers.py` behavior backward-compatible.
- Every code task follows red-green-refactor with `python -m unittest`.

---

## Plan Order

1. [Phase 1: State, classification, persistence, and safe diagnostics](2026-07-22-anti-crawler-phase-1-foundation.md)
2. [Phase 2: Retry policy, cookie consent, and dynamic content loading](2026-07-22-anti-crawler-phase-2-resilience-dynamic-loading.md)
3. [Phase 3: Human verification queue and protected site sessions](2026-07-22-anti-crawler-phase-3-verification-sessions.md)
4. [Phase 4: Zero-knowledge desktop UI, report handoff, retention, and installer](2026-07-22-anti-crawler-phase-4-desktop-delivery.md)

Each phase ends with the full existing test suite passing and a reviewable commit. Execute the phases in order because later interfaces consume earlier models and persistence services.

## Final Release Gate

- Run `python -m unittest discover -s tests -v` and require zero failures.
- Run `python build_release.py` and verify the source archive.
- Run `powershell -ExecutionPolicy Bypass -File build_installer.ps1` on a clean Windows build host.
- Install into a clean Windows user account and complete the UI acceptance checklist in Phase 4.
- Exercise one static directory, one delayed JavaScript directory, one ordinary paginator, one `Load more` directory, one infinite-scroll directory, and one controlled verification page at conservative request rates.
- Inspect one generated problem report and confirm no session file or secret value is present.
