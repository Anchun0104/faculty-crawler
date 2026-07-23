# CODEX_PARSER_RULES.md

## Purpose

These are non-negotiable engineering rules for all changes to the university faculty-directory crawler.

Every parser change must expand generic structural support while preserving all previously successful behavior.

---

## 1. Backward compatibility is mandatory

Do not:

- delete a working parser strategy;
- disable an existing fallback;
- weaken validation without explicit approval;
- replace an old rule only to make a new fixture pass;
- reduce output for previously passing fixtures without a tested and documented reason.

A change may optimize or replace an old implementation only when:

1. all previous tests still pass;
2. previous successful fixtures retain equivalent expected behavior;
3. regression tests cover both the old and new structures;
4. the change report identifies what was replaced and why compatibility is preserved.

A fix is incomplete if any previous successful fixture regresses.

---

## 2. New support must be additive or behaviorally equivalent

Preserve support for:

- card parsing;
- table parsing;
- DataTables/responsive-table parsing;
- heading-based parsing;
- heading-name + generic-profile-link parsing;
- role-grouped personnel parsing;
- legacy linked-list parsing;
- wrapper link segmentation;
- adjacent profile-link recovery;
- section-aware filtering;
- deduplication;
- output-quality checks.

Add a new bounded strategy or safely extend an existing strategy.

A fallback should normally run only when:

- existing parsing returns zero valid records; or
- coverage is clearly abnormal relative to strong person signals.

A fallback must not overwrite records already parsed correctly.

---

## 3. No page-specific patches

Forbidden unless explicitly approved:

- university-specific CSS selectors;
- domain-specific parser branches;
- hard-coded names;
- hard-coded profile URLs;
- one-off exceptions tied to the supplied URL.

The failing page may be a fixture, but implementation must target a generic DOM structure.

Do not use:

```python
if domain == "example.edu":
    ...
```

to solve a structural parser issue.

---

## 4. Keep parser stages separated

Maintain this pipeline:

```text
fetch/render
→ page-structure detection
→ candidate creation
→ field extraction
→ record validation
→ section/title filtering
→ deduplication
→ output-quality validation
→ export
```

Do not place broad filtering inside candidate creation if that prevents valid records from being examined.

Do not treat parsed count alone as success.

---

## 5. Record contract

Required:

- `Name`
- `Title`
- `Profile_URL`

Optional:

- `Email`

Rules:

- Missing Email must never drop a valid record.
- Email must never replace Profile_URL.
- Never require `Profile_URL AND Email`.
- Do not silently add or remove export columns.
- Do not infer Department, School, affiliation or membership from URL patterns, search results or common knowledge.

Expected validation:

```python
valid_record = valid_name and valid_title and valid_profile_url
```

---

## 6. Name extraction

Never use generic action/navigation text as Name:

- Profile Detail
- View Profile
- Profile
- Detail
- ver perfil
- Read more
- More
- Find People
- People Search
- Staff Search
- Directory Search

Never use image alt text as Name when it contains:

- photo
- headshot
- portrait
- image
- no photo
- this person has no photo

Role headings, section headings, filters and table headers must not become Name.

A generic profile link may provide Profile_URL, but its text must not become Name.

---

## 7. Title extraction

- Strip a duplicated full Name prefix from Title.
- Never use the next person's name as the current person's Title.
- Prefer title text inside the current bounded person block.
- A valid role-group heading may be inherited by rows beneath it.
- Preserve official non-English academic titles.
- Do not replace a stronger academic title with a programme/administrative role.

Examples of valid titles include:

- Professor
- Associate Professor
- Assistant Professor
- Reader
- Lecturer
- Senior Lecturer
- Research Fellow
- Research Associate
- Visiting Professor
- Docente
- Professora Associada
- Professora Auxiliar
- Professore Ordinario
- Professore Associato
- Lecturer I / II / III

---

## 8. Profile URL

Profile_URL is required.

Valid sources may include:

1. same-site person profile;
2. same path with a meaningful unique query parameter;
3. trusted external academic profile inside the current bounded person block:
   - Ciência Vitae;
   - ORCID;
   - official institutional research portal;
   - Pure / Elsevier research profile.

Do not:

- accept arbitrary external links;
- search the whole page and assign URLs by loose proximity;
- crawl arbitrary same-site pages as fallback;
- search a generic portal by person name;
- infer department membership from URL patterns.

Adjacent recovery order:

1. search inside current person card/block;
2. if absent, inspect bounded following siblings;
3. stop at the next person record or major structural section.

---

## 9. Email

Email is optional.

- Extract only when clearly associated with the same person block.
- Missing Email must not affect acceptance.
- Do not crawl profile pages for Email unless explicitly requested.
- Reject script fragments, ROT13 artifacts and invalid domains.
- Email alone is insufficient for export.

---

## 10. Section-aware filtering

Do not globally exclude neutral headings:

- Staff
- Our Staff
- People
- Faculty and Staff
- All Faculty & Staff
- Directory

Use structure and individual-title evidence.

Explicit sections that may be excluded:

- Administrative Staff
- Professional Services Staff
- Support Staff
- Operations Staff
- Emeritus Faculty
- Emeritus Professor
- Retired Faculty

Mandatory regression rule:

```text
Staff != Administrative Staff
```

Examples:

- Loughborough: standalone `Staff` is neutral.
- Colorado Law: `Staff` is a separate section parallel to `Resident Faculty`, so it may be excluded.

Section headings must come from outside the repeated person card/row.

Do not use office, contact, phone, location or research-area labels inside a card as section headings.

---

## 11. Candidate boundaries

Never export an entire list, table, wrapper or role section as one person.

When strong person links are numerous but candidate count is abnormally low:

- create one bounded block per unique person link;
- start at the current person link;
- stop at the next person link or section boundary.

Likewise:

- one table → one candidate per person row;
- one role group → one candidate per person row;
- one heading list → one candidate per person heading.

---

## 12. Pagination scope

Do not add or modify pagination during an unrelated parser fix.

Pagination is a separate feature and requires separate tests.

When explicitly requested:

- follow explicit next-page links;
- stay within the intended directory;
- prevent revisits;
- stop when no next page exists;
- merge results;
- deduplicate by normalized Profile_URL.

---

## 13. Deduplication

Preferred order:

1. normalized Profile_URL;
2. normalized Name + Title only when URL is unavailable and this fallback is explicitly valid.

Keep the most complete record and merge optional fields.

Do not deduplicate by Name alone when one person may have multiple valid roles.

---

## 14. Source-content limitations

Do not force parser changes when the source lacks required evidence.

### Empty directory

```text
Failure stage: source_content
Failure reason: directory_page_contains_no_person_records
```

### People listed without individual profile URLs

```text
Failure stage: source_content
Failure reason: directory_person_records_have_no_individual_profile_urls
```

In both cases:

- keep output empty;
- do not infer records;
- do not crawl arbitrary pages;
- do not use Email as a replacement for Profile_URL.

---

## 15. Tests required for every change

Every modification must add:

1. one positive test for the new failing structure;
2. one regression test proving an existing supported structure still works;
3. one negative test proving navigation, administrative or generic content is not newly accepted.

When changing a rule that previously caused a regression, test both sides.

Required examples include:

- standalone `Staff` remains neutral;
- `Administrative Staff` remains excluded;
- `Emeritus Faculty` remains excluded;
- `Profile Detail` may provide URL but not Name;
- photo/headshot alt is never Name;
- same-path unique-query URL may be a valid profile;
- Email remains optional;
- a wrapper with many person links is split into separate records;
- a DataTable is parsed row by row.

Run the full test suite.

Do not report completion if:

- any existing test fails;
- a previous fixture loses records unexpectedly;
- a required field becomes optional;
- an optional field becomes required;
- export schema changes silently.

---

## 16. Required pre-change analysis

Before coding, report briefly:

- structural cause;
- responsible parser stage;
- safest generic strategy;
- existing behaviors at risk;
- tests that will protect old behavior.

---

## 17. Required post-change report

After coding, report:

- files/functions changed;
- whether any old rule was removed, weakened or replaced;
- tests added;
- full test results;
- effect on existing strategies;
- before/after parsed counts for the supplied fixture when relevant.

If an old rule was weakened or removed, do not claim completion without explaining why all old behavior remains protected.

---

## 18. Scope discipline

During a focused fix, do not add unrelated features.

Examples:

- do not add pagination while fixing current-page card detection;
- do not add Email extraction while fixing Name/Profile_URL;
- do not expand trusted domains beyond the current generic need;
- do not start profile-page crawling;
- do not refactor unrelated modules;
- do not modify export schema.

If a safe generic fix conflicts with existing behavior, stop and report the conflict instead of breaking the old behavior.

---

## 19. Regression fixture matrix

| Fixture | Required behavior |
|---|---|
| ITU | `Profile Detail` is not Name; href may be Profile_URL |
| Colorado Law | Ignore photo/headshot alt; split Name/Title; exclude explicit Staff and Emeritus sections |
| UGM Sociology | Heading-based people under DOSEN; person links not required for detection |
| Loughborough | Standalone Staff heading is neutral |
| ISCSP ULisboa | Trusted external profile; bounded adjacent-link recovery; no card-internal section heading |
| Massey | Name profile link + adjacent title |
| Unicamp | Name heading + generic `ver perfil` link |
| Padova | Role-group rows; same path with unique query parameter is valid profile |
| HKBU | Split many people inside one large wrapper |
| Vanderbilt | Low-coverage wrapper link segmentation |
| UCC | DataTables row parsing; exclude Emeritus and Administrative sections |
| AUB SOAM | Empty source content; no arbitrary fallback crawling |
| Taylor's | Name/Title/Email but no individual Profile_URL; keep output empty |

---

## 20. Definition of done

A parser change is complete only when it:

- solves the supplied failing case;
- adds generic structural capability;
- preserves all existing passing fixtures;
- includes regression tests;
- does not use a university-specific extraction branch;
- does not weaken the record contract;
- does not introduce unrelated features;
- reports all changed behavior explicitly.
