# Chinese README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the English README with a complete Chinese guide covering supported page structures, implemented functions, limitations, pending work, installation, testing, and GitHub collaboration.

**Architecture:** Keep all reader-facing project orientation in `README.md` so users and maintainers can understand the tool from the repository landing page. Preserve exact build filenames required by release tests and describe planned AI integration as future work rather than an existing feature.

**Tech Stack:** Markdown, Python `unittest`, Git.

## Global Constraints

- Modify documentation only; do not change crawler behavior.
- Keep `requirements-build.txt` and `build_installer.ps1` in the README.
- Do not claim that AI integration, CAPTCHA solving, WAF bypass, or universal parsing already exists.
- Keep generated Excel files, browser runtimes, installers, logs, and sessions out of Git.

---

### Task 1: Replace and verify the repository README

**Files:**
- Modify: `README.md`
- Test: `tests/test_release.py`
- Create: `docs/superpowers/plans/2026-07-23-chinese-readme.md`

**Interfaces:**
- Consumes: implemented behavior documented by `crawler/`, `ui/`, and `tests/`.
- Produces: a Chinese repository landing page for users and maintainers.

- [ ] **Step 1: Replace the README**

Write Chinese sections for project positioning, implemented capabilities, supported structures, anti-crawler handling, desktop workflows, installation, development, limitations, roadmap, compliance boundaries, and GitHub collaboration.

- [ ] **Step 2: Verify required release references**

Run:

```powershell
python -m unittest tests.test_release.ReleasePackageTests.test_build_and_user_documentation_cover_zero_knowledge_workflow -v
```

Expected: the test passes and confirms that `requirements-build.txt` and `build_installer.ps1` remain documented.

- [ ] **Step 3: Run the full suite**

Run:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="<verified bundled browser path>"
python -m unittest discover -s tests -v
```

Expected: `Ran 433 tests` followed by `OK`.

- [ ] **Step 4: Commit and push**

```powershell
git add README.md docs/superpowers/plans/2026-07-23-chinese-readme.md
git commit -m "docs: add comprehensive Chinese README"
git push origin main
```

Expected: `main` is updated on `Anchun0104/faculty-crawler`.
