# Release History Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create reliable semantic-version records for 1.0.0 and 2.0.0, migrate 2.0.0 release assets, then remove the old mismatched record only after verification.

**Architecture:** Git tags are the immutable source anchors. GitHub Releases describe the user-facing artifact history. The old `FacultyCrawler` Release is treated as the verified asset source for 2.0.0; each downloaded asset is checked locally and against GitHub's server-side SHA-256 digest after upload before the legacy record is deleted.

**Tech Stack:** Git, GitHub CLI (`gh`), PowerShell SHA-256 (`Get-FileHash`), GitHub Releases API.

## Global Constraints

- Repository: `Anchun0104/faculty-crawler`.
- `v1.0.0` must target `cf93c7e859b4695a1625bc19738b319524d63dfc`.
- `v2.0.0` must target `5e04a28`.
- Do not claim a historical 1.0.0 installer exists; release notes must say it is source-only.
- Preserve bytes and names of 2.0.0 assets while migrating them.
- Delete `FacultyCrawler` Release and tag only after all new `v2.0.0` asset names and SHA-256 digests match their originals.

### Task 1: Verify anchors and create semantic tags

**Files:**
- Read: `VERSION` at `cf93c7e`
- Remote refs: `v1.0.0`, `v2.0.0`

- [ ] **Step 1: Verify version anchors and absence of semantic tags**

Run:

```powershell
git -C D:\updatecrawler show cf93c7e:VERSION
git -C D:\updatecrawler show -s --format='%H %s' 5e04a28
git -C D:\updatecrawler ls-remote --tags origin refs/tags/v1.0.0 refs/tags/v2.0.0
```

Expected: `VERSION` is `1.0.0`, the second command identifies the 2.0.0 merge state, and neither semantic tag exists.

- [ ] **Step 2: Create annotated tags locally**

Run:

```powershell
git -C D:\updatecrawler tag -a v1.0.0 cf93c7e859b4695a1625bc19738b319524d63dfc -m 'Release 1.0.0 source history'
git -C D:\updatecrawler tag -a v2.0.0 5e04a28 -m 'Release 2.0.0 offline multilingual title classification'
git -C D:\updatecrawler tag -v v1.0.0
git -C D:\updatecrawler tag -v v2.0.0
```

Expected: both tags resolve to the required commits. The `-v` output may report unsigned tags; the commit target must still be inspected with `git rev-list -n 1`.

- [ ] **Step 3: Push and verify tags remotely**

Run:

```powershell
git -C D:\updatecrawler push origin refs/tags/v1.0.0 refs/tags/v2.0.0
git -C D:\updatecrawler ls-remote --tags origin refs/tags/v1.0.0 refs/tags/v2.0.0
```

Expected: each remote tag resolves to its intended annotated tag object and commit.

### Task 2: Create the source-only 1.0.0 Release

**Remote object:** GitHub Release `v1.0.0`

- [ ] **Step 1: Confirm no existing Release uses `v1.0.0`**

Run:

```powershell
gh release view v1.0.0 --repo Anchun0104/faculty-crawler
```

Expected: not found.

- [ ] **Step 2: Create release with precise historical scope**

Release title: `FacultyCrawler 1.0.0 (source history)`.

Release body must state: source is pinned to `cf93c7e`; no historical installer was retained; use the tag to inspect, rebuild, or branch from the old source; it is not a binary download release.

- [ ] **Step 3: Verify Release metadata**

Run:

```powershell
gh release view v1.0.0 --repo Anchun0104/faculty-crawler --json tagName,targetCommitish,isDraft,isPrerelease,assets
```

Expected: `tagName` is `v1.0.0`, target is the 1.0.0 commit, `assets` is empty, and the release is published.

### Task 3: Migrate and verify 2.0.0 assets

**Remote objects:** legacy Release `FacultyCrawler`, new Release `v2.0.0`.

- [ ] **Step 1: Read legacy asset metadata before download**

Run:

```powershell
gh release view FacultyCrawler --repo Anchun0104/faculty-crawler --json name,tagName,assets
```

Expected assets: `FacultyCrawler-Setup-2.0.0.exe`, its SHA-256 text file, `faculty-crawler-windows.zip`, and its SHA-256 text file.

- [ ] **Step 2: Download all four legacy assets to a unique temporary directory**

Run `gh release download FacultyCrawler` with exact asset patterns and preserve names. Do not overwrite an existing local build artifact.

- [ ] **Step 3: Validate local assets before upload**

Use `Get-FileHash -Algorithm SHA256` for EXE and ZIP, then compare exact hexadecimal values with their downloaded `.sha256.txt` files. Abort if either differs.

- [ ] **Step 4: Create and upload the new v2.0.0 Release**

Release title: `FacultyCrawler 2.0.0`.

Release body must state that it is the canonical 2.0.0 release, identifies commit `5e04a28`, lists the two SHA-256 values, and notes that it replaces the legacy `FacultyCrawler` tag/release.

Upload exactly the verified four original files without renaming them.

- [ ] **Step 5: Verify server-side asset records**

Run:

```powershell
gh release view v2.0.0 --repo Anchun0104/faculty-crawler --json tagName,targetCommitish,assets
```

Expected: correct tag and target, exactly four assets with original names and sizes, and GitHub API `digest` values matching the local SHA-256 values for EXE and ZIP.

### Task 4: Retire the mismatched legacy record

**Remote objects:** legacy Release and tag `FacultyCrawler`.

- [ ] **Step 1: Re-run final guard checks**

Confirm both semantic tags and releases are present. Confirm `v2.0.0` assets are complete and checksums match. Confirm the old release is still available before deletion.

- [ ] **Step 2: Delete only the legacy release**

Run:

```powershell
gh release delete FacultyCrawler --repo Anchun0104/faculty-crawler --yes
```

- [ ] **Step 3: Delete only the legacy remote tag**

Run:

```powershell
git -C D:\updatecrawler push origin :refs/tags/FacultyCrawler
```

- [ ] **Step 4: Verify final public state**

Run:

```powershell
git -C D:\updatecrawler ls-remote --tags origin refs/tags/v1.0.0 refs/tags/v2.0.0 refs/tags/FacultyCrawler
gh release view v1.0.0 --repo Anchun0104/faculty-crawler --json tagName,assets
gh release view v2.0.0 --repo Anchun0104/faculty-crawler --json tagName,assets
```

Expected: `v1.0.0` and `v2.0.0` remain; `FacultyCrawler` is absent; the 1.0.0 Release is source-only and the 2.0.0 Release carries the four verified assets.
