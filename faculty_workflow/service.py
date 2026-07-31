from __future__ import annotations

import json
import logging
import gzip
import inspect
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from crawler.faculty_crawler import FacultyCrawler
from crawler.parsers import (
    FacultyRecord,
    TitlePendingRecord,
    find_linked_directory_sources,
    find_next_directory_page_url,
)
from crawler.title_classifier import TitleClassifier
from crawler.title_pipeline import TitlePipeline
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.directory_adapters import DirectoryRecord, UniversalDirectoryAdapter
from faculty_workflow.discovery import (
    DiscoveryLimits,
    DiscoveryProvider,
    EmptyDiscoveryProvider,
    OfficialSourceGraph,
)
from faculty_workflow.email_resolver import EmailResolution, OfficialEmailResolver
from faculty_workflow.exporter import export_task
from faculty_workflow.fetcher import (
    AccessBlockedError,
    FetchError,
    FetchPolicy,
    FetchedPage,
    PageFetcher,
    RobotsDeniedError,
    html_to_text,
    url_is_on_domain,
)
from faculty_workflow.importers import import_history, import_processed_schools, load_schools
from faculty_workflow.models import (
    CandidateExtraction,
    DisciplinePolicy,
    Evidence,
    SchoolInput,
    normalize_email,
    normalize_key,
    normalize_url,
)
from faculty_workflow.pdf_documents import PdfDocumentError, extract_pdf_text
from faculty_workflow.providers import (
    DeepSeekProvider,
    ModelProvider,
    ProviderResult,
    MissingAPIKeyError,
    extraction_from_result,
    policy_from_result,
)
from faculty_workflow.quality import QualityDecision, evaluate_candidate
from faculty_workflow.session_store import ProtectedSessionStore


logger = logging.getLogger(__name__)
LOCAL_ONLY_MODEL = "local-only"


class BudgetExceededError(RuntimeError):
    pass


class PolicyNotConfirmedError(RuntimeError):
    pass


class WorkflowService:
    def __init__(
        self,
        database: WorkflowDatabase,
        *,
        provider: ModelProvider | None = None,
        fetcher: PageFetcher | None = None,
        crawler_factory: Callable[[int], FacultyCrawler] | None = None,
        email_resolver: OfficialEmailResolver | None = None,
        directory_adapter: UniversalDirectoryAdapter | None = None,
        title_pipeline: TitlePipeline | None = None,
        discovery_provider: DiscoveryProvider | None = None,
        timeout_ms: int = 30000,
    ) -> None:
        self.database = database
        self.provider = provider or DeepSeekProvider()
        self.fetcher = fetcher or PageFetcher(
            timeout_ms=timeout_ms,
            session_store=ProtectedSessionStore(database.path.parent / "sessions"),
        )
        self.crawler_factory = crawler_factory or (lambda timeout: FacultyCrawler(timeout=timeout))
        self.email_resolver = email_resolver or OfficialEmailResolver()
        self.directory_adapter = directory_adapter or UniversalDirectoryAdapter()
        self.title_pipeline = title_pipeline or TitlePipeline(TitleClassifier())
        self.discovery_provider = discovery_provider or EmptyDiscoveryProvider()
        self.timeout_ms = timeout_ms

    def create_task(
        self,
        *,
        schools_path: str | Path,
        discipline: str,
        output_dir: str | Path,
        budget_usd: float = 20.0,
        history_paths: Iterable[str | Path] = (),
        processed_school_paths: Iterable[str | Path] = (),
        generate_ai_policy: bool = True,
        routine_model: str = "deepseek-v4-flash",
        escalation_model: str = "deepseek-v4-pro",
    ) -> str:
        schools = load_schools(schools_path)
        return self.create_task_from_schools(
            schools=schools,
            discipline=discipline,
            output_dir=output_dir,
            budget_usd=budget_usd,
            history_paths=history_paths,
            processed_school_paths=processed_school_paths,
            generate_ai_policy=generate_ai_policy,
            routine_model=routine_model,
            escalation_model=escalation_model,
        )

    def create_task_from_schools(
        self,
        *,
        schools: Iterable[SchoolInput],
        discipline: str,
        output_dir: str | Path,
        budget_usd: float = 20.0,
        history_paths: Iterable[str | Path] = (),
        processed_school_paths: Iterable[str | Path] = (),
        generate_ai_policy: bool = True,
        routine_model: str = "deepseek-v4-flash",
        escalation_model: str = "deepseek-v4-pro",
        policy_confirmed: bool = False,
    ) -> str:
        school_rows = list(schools)
        if not school_rows:
            raise ValueError("At least one verified directory URL is required")
        draft = DisciplinePolicy(
            discipline=discipline.strip(),
            include_topics=(discipline.strip(),),
            exclude_topics=(),
        )
        task_id = self.database.create_task(
            draft,
            school_rows,
            output_dir=output_dir,
            budget_usd=budget_usd,
            routine_model=routine_model,
            escalation_model=escalation_model,
            policy_confirmed=policy_confirmed,
        )
        import_history(self.database, task_id, history_paths)
        import_processed_schools(self.database, task_id, processed_school_paths)
        if generate_ai_policy:
            try:
                result = self._provider_call(
                    task_id,
                    operation="generate_policy",
                    model=escalation_model,
                    input_characters=len(discipline) + 500,
                    max_output_tokens=2000,
                    call=lambda: self.provider.generate_policy(discipline, escalation_model),
                )
                policy = policy_from_result(result)
                self.database.update_task(task_id, policy_json=policy.to_json(), discipline=policy.discipline)
            except Exception as exc:
                self.database.update_task(
                    task_id,
                    warning=f"AI policy draft unavailable; edit and confirm the local draft: {exc}",
                )
        return task_id

    def create_direct_url_task(
        self,
        *,
        directory_urls: Iterable[str],
        output_dir: str | Path,
        school_name: str = "",
        discipline: str = "General Faculty",
        use_ai: bool = False,
        routine_model: str = "deepseek-v4-flash",
        escalation_model: str = "deepseek-v4-pro",
        budget_usd: float = 20.0,
    ) -> str:
        urls = [normalize_url(value) for value in directory_urls]
        urls = list(dict.fromkeys(value for value in urls if value))
        if not urls:
            raise ValueError("At least one valid directory URL is required")
        if school_name.strip() and len(urls) != 1:
            raise ValueError("A school name override can only be used with one directory URL")
        schools = [
            SchoolInput(
                name=school_name.strip() or _school_identifier_from_url(url),
                official_domain=(urlparse(url).hostname or "").lower(),
                directory_url=url,
            )
            for url in urls
        ]
        policy = DisciplinePolicy(
            discipline=discipline.strip() or "General Faculty",
            include_topics=("faculty", "academic staff", "teaching staff"),
            exclude_topics=(),
        )
        return self.database.create_task(
            policy,
            schools,
            output_dir=output_dir,
            budget_usd=budget_usd,
            routine_model=routine_model if use_ai else LOCAL_ONLY_MODEL,
            escalation_model=escalation_model if use_ai else LOCAL_ONLY_MODEL,
            policy_confirmed=True,
        )

    def confirm_policy(self, task_id: str, policy: DisciplinePolicy) -> None:
        self.database.confirm_policy(task_id, policy)

    def run_task(
        self,
        task_id: str,
        *,
        school_ids: Iterable[int] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.database.recover_interrupted_task(task_id)
        task = self.database.get_task(task_id)
        if not task["policy_confirmed"]:
            raise PolicyNotConfirmedError("The discipline policy must be confirmed before running")
        if task["routine_model"] != LOCAL_ONLY_MODEL and isinstance(self.provider, DeepSeekProvider) and not self.provider.api_key:
            raise MissingAPIKeyError("DEEPSEEK_API_KEY is not configured; no school was started")
        policy = self.database.get_policy(task_id)
        self.database.update_task(task_id, status="running", error="")
        selected_school_ids = None if school_ids is None else {int(value) for value in school_ids}
        try:
            schools = self.database.list_schools(
                task_id,
                ["pending", "failed"],
            )
            if selected_school_ids is not None:
                schools = [school for school in schools if int(school["id"]) in selected_school_ids]
            for school in schools:
                self._emit(on_progress, task_id, school_id=school["id"], message="school_started")
                if self.database.is_processed_school(task_id, school["name"]):
                    self.database.update_school(school["id"], status="skipped_processed")
                    continue
                try:
                    self._run_school(task_id, school, policy, on_progress)
                except BudgetExceededError:
                    self.database.update_task(task_id, status="paused_budget")
                    return self.database.summary(task_id)
                except RobotsDeniedError as exc:
                    self.database.update_school(school["id"], status="blocked_robots", failure_reason=str(exc))
                except AccessBlockedError as exc:
                    self.database.update_school(school["id"], status="blocked_access", failure_reason=str(exc))
                    self.database.create_access_review(
                        task_id,
                        int(school["id"]),
                        getattr(exc, "url", "") or str(school["directory_url"]),
                        str(exc),
                    )
                except Exception as exc:
                    logger.exception("School workflow failed: %s", school["name"])
                    self.database.update_school(school["id"], status="failed", failure_reason=str(exc)[:500])
                self._emit(on_progress, task_id, school_id=school["id"], message="school_finished")
        except Exception as exc:
            self.database.update_task(task_id, status="failed", error=str(exc)[:500])
            raise
        self.database.update_task(task_id, status="completed")
        return self.database.summary(task_id)

    def export(self, task_id: str, output_dir: str | Path | None = None) -> dict[str, Path]:
        return export_task(self.database, task_id, output_dir)

    def run_review_generation(
        self,
        task_id: str,
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Start or resume only active review rows; never default to a whole-task rerun."""
        generation = self.database.begin_review_generation(task_id)
        if generation["status"] == "running":
            school_ids = tuple(int(value) for value in json.loads(generation["requeued_school_ids"]))
            summary = (
                self.run_task(task_id, school_ids=school_ids, on_progress=on_progress)
                if on_progress is not None else self.run_task(task_id, school_ids=school_ids)
            )
            self.database.complete_review_generation(str(generation["id"]), summary)
            generation = self.database.list_review_generations(task_id)[-1]
        else:
            summary = self.database.summary(task_id)
        return {"generation": dict(generation), "summary": summary}

    def begin_access_verification(self, review_id: int) -> None:
        review = self._access_review(review_id)
        self.fetcher.begin_interactive_verification(str(review["url"]))

    def finish_access_verification(self, review_id: int) -> None:
        self._access_review(review_id)
        self.fetcher.finish_interactive_verification()
        self.database.resolve_access_review(review_id, retry=True)

    def cancel_access_verification(self) -> None:
        self.fetcher.cancel_interactive_verification()

    def _access_review(self, review_id: int) -> Any:
        return self.database.get_access_review(review_id)

    def _run_school(
        self,
        task_id: str,
        school: Any,
        policy: DisciplinePolicy,
        on_progress: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        school_id = int(school["id"])
        official_domain = str(school["official_domain"] or "")
        directory_url = str(school["directory_url"] or "")
        if directory_url:
            official_domain = official_domain or (urlparse(directory_url).hostname or "")
            trusted_source_domain = urlparse(directory_url).hostname or official_domain
            self.database.update_school(
                school_id,
                status="discovering",
                official_domain=official_domain,
            )
            self.database.add_source(
                task_id,
                school_id,
                directory_url,
                "faculty_directory",
                official=True,
                official_boundary="official",
            )
        else:
            self.database.update_school(
                school_id,
                status="review",
                failure_reason="missing_directory_url",
            )
            return

        all_sources = self.database.list_sources(task_id, school_id)
        # Persisted pagination/profile sources are audit records, not new crawl roots.
        # Starting from them again makes page 2 traverse pages 3..N repeatedly and,
        # on later reruns, can even parse every saved person profile as a directory.
        sources = [
            source for source in all_sources
            if source["source_type"] in {"faculty_directory", "research_portal", "research_unit"}
        ]
        if not sources:
            self.database.update_school(school_id, status="review", failure_reason="no_directory_source_found")
            return

        snapshot_dir = Path(self.database.get_task(task_id)["output_dir"]) / "snapshots" / str(school_id)
        seeds: dict[str, dict[str, str]] = {}
        self.database.update_school(school_id, status="crawling")
        source_graph = OfficialSourceGraph(
            trusted_source_domain,
            DiscoveryLimits(max_depth=2, max_pages=50),
        )
        for source in sources:
            source_graph.enqueue(
                str(source["url"]),
                str(source["source_type"]),
                str(source["discovered_from"] or ""),
                int(source["depth"] or 0),
            )
        last_source_id: int | None = None
        while True:
            node = source_graph.pop()
            if node is None:
                break
            source_id = self.database.add_source(
                task_id,
                school_id,
                node.url,
                node.source_type,
                official=True,
                discovered_from=node.discovered_from,
                depth=node.depth,
                official_boundary="official",
                fetch_state="queued",
            )
            last_source_id = source_id
            source = self.database.get_source(source_id)
            discovered = self._collect_directory_seeds(
                task_id, school_id, source, snapshot_dir, seeds, trusted_source_domain
            )
            for url, source_type in discovered:
                if source_graph.enqueue(
                    url,
                    source_type,
                    discovered_from=node.url,
                    depth=node.depth + 1,
                ):
                    self.database.add_source(
                        task_id,
                        school_id,
                        url,
                        source_type,
                        official=True,
                        discovered_from=node.url,
                        depth=node.depth + 1,
                        official_boundary="official",
                        fetch_state="queued",
                    )
        if last_source_id is not None and source_graph.stop_reason:
            self.database.update_source(last_source_id, stop_reason=source_graph.stop_reason)

        if not seeds:
            self.database.update_school(school_id, status="review", failure_reason="no_person_profile_urls_found")
            return

        # Personal pages often contain the only official links to laboratories,
        # centres, or institutional research portals. Discover those links before
        # candidate decisions so their exact-name facts can merge into the baseline.
        profile_failures: dict[str, str] = {}
        for seed in list(seeds.values()):
            name = str(seed.get("name") or "")
            profile_url = str(seed.get("profile_url") or "")
            directory_fast_path = _directory_fast_path_candidate(
                self.database,
                task_id,
                school_id,
                str(school["name"]),
                seed,
                policy,
                trusted_source_domain,
                official_domain,
                self.title_pipeline,
            )
            if (
                not profile_url
                or directory_fast_path is not None
                or self.database.has_accepted_candidate_name(task_id, school_id, name)
            ):
                continue
            try:
                cached_source = self.database.find_source(task_id, profile_url)
                profile_page = (
                    _load_cached_source_page(cached_source, profile_url)
                    if cached_source is not None else None
                )
                if profile_page is None:
                    profile_page = self._fetch_with_policy(
                        profile_url, snapshot_dir, FetchPolicy.person_profile()
                    )
            except (AccessBlockedError, RobotsDeniedError, FetchError) as exc:
                profile_failures[profile_url] = str(exc)
                continue
            profile_source_id = self.database.add_source(
                task_id,
                school_id,
                profile_page.final_url,
                "person_profile",
                official=url_is_on_domain(profile_page.final_url, trusted_source_domain),
                discovered_from=str(seed.get("directory_url") or ""),
                depth=1,
                official_boundary=(
                    "official" if url_is_on_domain(profile_page.final_url, trusted_source_domain)
                    else "outside_official_domain"
                ),
            )
            self._record_fetched_source(profile_source_id, profile_page)
            if not url_is_on_domain(profile_page.final_url, trusted_source_domain):
                continue
            for url, source_type in find_linked_directory_sources(
                profile_page.html, profile_page.final_url, trusted_source_domain
            ):
                if source_graph.enqueue(
                    url,
                    source_type,
                    discovered_from=profile_page.final_url,
                    depth=1,
                ):
                    self.database.add_source(
                        task_id,
                        school_id,
                        url,
                        source_type,
                        official=True,
                        discovered_from=profile_page.final_url,
                        depth=1,
                        official_boundary="official",
                    )

        while True:
            node = source_graph.pop()
            if node is None:
                break
            source_id = self.database.add_source(
                task_id,
                school_id,
                node.url,
                node.source_type,
                official=True,
                discovered_from=node.discovered_from,
                depth=node.depth,
                official_boundary="official",
            )
            source = self.database.get_source(source_id)
            discovered = self._collect_directory_seeds(
                task_id, school_id, source, snapshot_dir, seeds, trusted_source_domain
            )
            for url, source_type in discovered:
                if source_graph.enqueue(
                    url,
                    source_type,
                    discovered_from=node.url,
                    depth=node.depth + 1,
                ):
                    self.database.add_source(
                        task_id,
                        school_id,
                        url,
                        source_type,
                        official=True,
                        discovered_from=node.url,
                        depth=node.depth + 1,
                        official_boundary="official",
                    )

        self.database.update_school(school_id, status="extracting")
        for _, seed in seeds.items():
            seed = dict(seed)
            profile_url = str(seed.get("profile_url") or "")
            directory_url = str(seed.get("directory_url") or "")
            if self.database.has_accepted_candidate_name(
                task_id, school_id, str(seed.get("name") or "")
            ):
                continue
            if profile_url and self.database.has_candidate_homepage(task_id, school_id, profile_url):
                continue
            exclusion = _hard_exclusion(seed)
            if exclusion:
                self.database.add_candidate(
                    task_id,
                    school_id,
                    CandidateExtraction(
                        name=_clean_local_name(str(seed.get("name") or ""), policy),
                        title_raw=seed.get("title", ""),
                        homepage=profile_url,
                        professional_relevance="irrelevant",
                        failure_reasons=(exclusion,),
                    ),
                    direction=policy.discipline,
                    source_url=profile_url,
                    status="rejected",
                    review_reason=exclusion,
                )
                continue
            directory_fast_path = _directory_fast_path_candidate(
                self.database,
                task_id,
                school_id,
                str(school["name"]),
                seed,
                policy,
                trusted_source_domain,
                official_domain,
                self.title_pipeline,
            )
            if directory_fast_path is not None:
                extraction, decision = directory_fast_path
                self.database.add_candidate(
                    task_id,
                    school_id,
                    extraction,
                    direction=policy.discipline,
                    source_url=directory_url,
                    status=decision.status,
                    review_reason=";".join(decision.reasons),
                )
                self._emit(on_progress, task_id, school_id=school_id, message="directory_candidate_saved")
                continue
            if profile_url and profile_url in profile_failures:
                self._save_profile_fetch_review(
                    task_id, school_id, policy, profile_url, seed, profile_failures[profile_url]
                )
                self._emit(on_progress, task_id, school_id=school_id, message="profile_fetch_review")
                continue
            discovered_page: FetchedPage | None = None
            if not profile_url:
                discovered_page = self._discover_official_profile_page(
                    task_id,
                    school_id,
                    str(school["name"]),
                    trusted_source_domain,
                    seed,
                    snapshot_dir,
                )
                if discovered_page is not None:
                    profile_url = discovered_page.final_url
                    seed["profile_url"] = profile_url
            if not profile_url:
                extraction = _directory_only_extraction(seed, policy)
                extraction = _apply_title_pipeline(
                    extraction,
                    self.title_pipeline,
                    policy,
                )
                extraction = replace(
                    extraction,
                    official_source=bool(
                        trusted_source_domain and url_is_on_domain(directory_url, trusted_source_domain)
                    ),
                )
                decision = evaluate_candidate(
                    self.database,
                    task_id,
                    school_id,
                    school["name"],
                    extraction,
                    policy,
                    official_domain=official_domain,
                )
                self.database.add_candidate(
                    task_id,
                    school_id,
                    extraction,
                    direction=policy.discipline,
                    source_url=directory_url,
                    status=decision.status,
                    review_reason=";".join(decision.reasons),
                )
                self._emit(on_progress, task_id, school_id=school_id, message="directory_candidate_saved")
                continue
            if discovered_page is None:
                try:
                    cached_source = self.database.find_source(task_id, profile_url)
                    page = (
                        _load_cached_source_page(cached_source, profile_url)
                        if cached_source is not None else None
                    )
                    if page is None:
                        page = self._fetch_with_policy(
                            profile_url, snapshot_dir, FetchPolicy.person_profile()
                        )
                except (AccessBlockedError, RobotsDeniedError, FetchError) as exc:
                    self._save_profile_fetch_review(
                        task_id, school_id, policy, profile_url, seed, str(exc)
                    )
                    self._emit(on_progress, task_id, school_id=school_id, message="profile_fetch_review")
                    continue
            else:
                page = discovered_page
            profile_source_id = self.database.add_source(
                task_id, school_id, page.final_url, "person_profile", official=True
            )
            self._record_fetched_source(profile_source_id, page)
            extraction = self._extract_with_escalation(task_id, school, policy, page, seed)
            deterministic_official = bool(
                trusted_source_domain
                and url_is_on_domain(page.final_url, trusted_source_domain)
                and url_is_on_domain(extraction.homepage or page.final_url, trusted_source_domain)
            )
            if not extraction.homepage:
                extraction = replace(extraction, homepage=page.final_url)
            extraction = _merge_directory_card_evidence(extraction, seed, policy)
            extraction = _apply_title_pipeline(
                extraction,
                self.title_pipeline,
                policy,
                language_hint=_page_language_hint(page),
            )
            email_pages: list[FetchedPage] = []

            def fetch_email_source(url: str) -> FetchedPage:
                cached_source = self.database.find_source(task_id, url)
                cached_page = (
                    _load_cached_source_page(cached_source, url)
                    if cached_source is not None else None
                )
                if cached_page is not None:
                    return cached_page
                fetched = self._fetch_with_policy(url, snapshot_dir, FetchPolicy.person_profile())
                email_pages.append(fetched)
                return fetched

            resolution = self.email_resolver.resolve(
                name=extraction.name or str(seed.get("name") or ""),
                page=page,
                official_domain=official_domain,
                fetch_page=fetch_email_source,
            )
            if resolution is not None:
                extraction = _merge_official_email_resolution(extraction, resolution)
            for followup in email_pages:
                source_id = self.database.add_source(
                    task_id, school_id, followup.final_url, "official_email_source", official=True
                )
                self._record_fetched_source(source_id, followup)
            extraction = _apply_relevance_rule(extraction, page, policy)
            extraction = replace(extraction, official_source=deterministic_official)
            decision = evaluate_candidate(
                self.database,
                task_id,
                school_id,
                school["name"],
                extraction,
                policy,
                official_domain=official_domain,
            )
            self.database.add_candidate(
                task_id,
                school_id,
                extraction,
                direction=policy.discipline,
                source_url=page.final_url,
                status=decision.status,
                review_reason=";".join(decision.reasons),
            )
            self._emit(on_progress, task_id, school_id=school_id, message="candidate_saved")

        candidate_rows = self.database.list_candidates(task_id)
        school_rows = [row for row in candidate_rows if row["school_id"] == school_id]
        final_status = "review" if any(row["status"] == "review" for row in school_rows) else "completed"
        self.database.update_school(school_id, status=final_status)

    def _discover_official_profile_page(
        self,
        task_id: str,
        school_id: int,
        school_name: str,
        official_domain: str,
        seed: dict[str, str],
        snapshot_dir: Path,
    ) -> FetchedPage | None:
        """Treat search output as URL hints and trust only a re-fetched official page."""
        name = str(seed.get("name") or "").strip()
        if not name or not official_domain:
            return None
        try:
            hints = self.discovery_provider.discover(
                name=name,
                school=school_name,
                official_domain=official_domain,
            )
        except Exception as exc:
            logger.warning("Official profile discovery failed for %s: %s", name, exc)
            return None
        for hint in hints:
            if not url_is_on_domain(hint.url, official_domain):
                continue
            source_id = self.database.add_source(
                task_id,
                school_id,
                hint.url,
                "person_profile",
                official=True,
                discovered_from=str(seed.get("directory_url") or ""),
                depth=1,
                official_boundary="official",
                fetch_state="queued",
            )
            try:
                page = self._fetch_with_policy(
                    hint.url, snapshot_dir, FetchPolicy.person_profile()
                )
            except (AccessBlockedError, RobotsDeniedError, FetchError) as exc:
                self.database.update_source(
                    source_id,
                    fetch_state="failed",
                    failure_reason=str(exc)[:500],
                )
                continue
            if not url_is_on_domain(page.final_url, official_domain):
                self.database.update_source(
                    source_id,
                    official=False,
                    official_boundary="redirected_outside_official_domain",
                    fetch_state="rejected",
                )
                continue
            self._record_fetched_source(source_id, page)
            if normalize_key(name) not in normalize_key(page.text):
                self.database.update_source(
                    source_id,
                    fetch_state="rejected",
                    stop_reason="person_name_not_found",
                )
                continue
            return page
        return None

    def _fetch_with_policy(
        self,
        url: str,
        snapshot_dir: Path,
        policy: FetchPolicy,
    ) -> FetchedPage:
        """Use source-aware fetch settings while preserving injected fetcher compatibility."""
        try:
            parameters = inspect.signature(self.fetcher.fetch).parameters.values()
            supports_policy = any(
                parameter.name == "policy" or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_policy = True
        if supports_policy:
            return self.fetcher.fetch(url, snapshot_dir, policy=policy)
        return self.fetcher.fetch(
            url, snapshot_dir, expand_directory=policy.expand_directory
        )

    def _collect_directory_seeds(
        self,
        task_id: str,
        school_id: int,
        source: Any,
        snapshot_dir: Path,
        seeds: dict[str, dict[str, str]],
        official_domain: str,
    ) -> list[tuple[str, str]]:
        """Fetch bounded ordinary pagination through the workflow access policy.

        Directory pagination must not fall back to the legacy crawler's independent
        browser session: that would lose page expansion and bypass the workflow's
        robots check, rate limit, snapshots, and retry policy.
        """
        next_url = str(source["url"])
        source_id = int(source["id"])
        current_source = source
        visited: set[str] = set()
        discovered_sources: dict[str, tuple[str, str]] = {}
        for _ in range(100):
            normalized = next_url.casefold().split("#", 1)[0]
            if normalized in visited:
                return list(discovered_sources.values())
            visited.add(normalized)
            try:
                page = _load_cached_source_page(current_source, next_url)
                if page is None:
                    page = self._fetch_with_policy(
                        next_url, snapshot_dir, FetchPolicy.directory()
                    )
            except (AccessBlockedError, RobotsDeniedError) as exc:
                self.database.update_source(
                    source_id, failure_reason=str(exc)[:500], fetch_state="failed"
                )
                raise
            except FetchError as exc:
                # Preserve records found on earlier pages. A later page timing out
                # should not discard an otherwise usable directory or fail a school.
                self.database.update_source(
                    source_id, failure_reason=str(exc)[:500], fetch_state="failed"
                )
                return list(discovered_sources.values())
            except Exception as exc:
                # Keep only the classified error message; snapshots, cookies and page
                # bodies are deliberately never copied into the database diagnostic.
                self.database.update_source(
                    source_id, failure_reason=str(exc)[:500], fetch_state="failed"
                )
                raise
            self._record_fetched_source(source_id, page)
            crawler = self.crawler_factory(self.timeout_ms)
            parser = getattr(crawler, "parse_fetched_directory", None)
            records = (
                parser(page.final_url, page.html, page.http_status)
                if callable(parser)
                else crawler.crawl(page.final_url)
            )
            universal = self.directory_adapter.extract(page.html, page.final_url)
            if universal.authoritative:
                for record in universal.records:
                    seed = _directory_adapter_seed(record, page.final_url)
                    _store_directory_seed(seeds, seed)
            else:
                for record in records:
                    if record.name:
                        seed = _faculty_seed(record, page.final_url)
                        _store_directory_seed(seeds, seed)
                for record in universal.records:
                    seed = _directory_adapter_seed(record, page.final_url)
                    _store_directory_seed(seeds, seed)
                for pending in getattr(crawler, "title_pending_records", []):
                    if pending.name:
                        seed = _pending_seed(pending, page.final_url)
                        _store_directory_seed(seeds, seed)

            for discovered_url, discovered_type in find_linked_directory_sources(
                page.html, page.final_url, official_domain
            ):
                discovered_sources.setdefault(
                    normalize_url(discovered_url), (discovered_url, discovered_type)
                )
            candidate = find_next_directory_page_url(page.html, page.final_url)
            if not candidate or (official_domain and not url_is_on_domain(candidate, official_domain)):
                return list(discovered_sources.values())
            next_url = candidate
            source_id = self.database.add_source(
                task_id,
                school_id,
                next_url,
                "directory_page",
                official=True,
                discovered_from=page.final_url,
                official_boundary="official",
            )
            current_source = self.database.get_source(source_id)
        return list(discovered_sources.values())

    def _extract_with_escalation(
        self,
        task_id: str,
        school: Any,
        policy: DisciplinePolicy,
        page: FetchedPage,
        seed: dict[str, str],
    ) -> CandidateExtraction:
        task = self.database.get_task(task_id)
        routine_model = task["routine_model"]
        if routine_model == LOCAL_ONLY_MODEL:
            return _local_profile_extraction(page, seed, policy)
        profile_text = _profile_excerpt(page.text, seed)
        result = self._provider_call(
            task_id,
            operation="extract_profile",
            model=routine_model,
            school_id=school["id"],
            input_characters=len(profile_text),
            max_output_tokens=4000,
            call=lambda: self.provider.extract_profile(
                school=school["name"],
                policy=policy,
                profile_url=page.final_url,
                page_title=page.title,
                page_text=profile_text,
                seed=seed,
                model=routine_model,
            ),
        )
        extraction = extraction_from_result(result)
        if _needs_escalation(extraction) and task["escalation_model"] != routine_model:
            escalation_model = task["escalation_model"]
            result = self._provider_call(
                task_id,
                operation="extract_profile_escalation",
                model=escalation_model,
                school_id=school["id"],
            input_characters=len(profile_text),
                max_output_tokens=4000,
                call=lambda: self.provider.extract_profile(
                    school=school["name"],
                    policy=policy,
                    profile_url=page.final_url,
                    page_title=page.title,
                page_text=profile_text,
                    seed=seed,
                    model=escalation_model,
                ),
            )
            extraction = extraction_from_result(result)
        return _ground_extraction(extraction, page)

    def _provider_call(
        self,
        task_id: str,
        *,
        operation: str,
        model: str,
        input_characters: int,
        max_output_tokens: int,
        call: Callable[[], ProviderResult],
        school_id: int | None = None,
    ) -> ProviderResult:
        task = self.database.get_task(task_id)
        reserve = self.provider.estimate_request_cost(model, input_characters, max_output_tokens)
        if float(task["spent_usd"]) + reserve > float(task["budget_usd"]):
            self.database.update_task(
                task_id,
                status="paused_budget",
                warning=f"Budget paused before {operation}; add budget to continue",
            )
            raise BudgetExceededError("Task API budget has been reached")
        try:
            result = call()
        except Exception as exc:
            self.database.record_api_call(
                task_id,
                school_id=school_id,
                operation=operation,
                model=model,
                estimated_cost_usd=0,
                status="failed",
                error=str(exc)[:500],
            )
            raise
        self.database.record_api_call(
            task_id,
            school_id=school_id,
            operation=operation,
            model=result.model,
            response_id=result.response_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tool_calls=result.tool_calls,
            estimated_cost_usd=result.estimated_cost_usd,
            status="succeeded",
        )
        refreshed = self.database.get_task(task_id)
        ratio = float(refreshed["spent_usd"]) / float(refreshed["budget_usd"])
        if ratio >= 0.8:
            self.database.update_task(task_id, warning=f"API budget usage is {ratio:.0%}")
        return result

    def _record_fetched_source(self, source_id: int, page: FetchedPage) -> None:
        self.database.update_source(
            source_id,
            final_url=page.final_url,
            http_status=page.http_status,
            content_hash=page.content_hash,
            snapshot_path=str(page.snapshot_path),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            failure_reason="",
            fetch_state="fetched",
        )

    def _save_profile_fetch_review(
        self,
        task_id: str,
        school_id: int,
        policy: DisciplinePolicy,
        profile_url: str,
        seed: dict[str, str],
        error: str,
    ) -> None:
        """Keep a single inaccessible profile reviewable without failing its school."""
        extraction = CandidateExtraction(
            name=str(seed.get("name") or ""),
            email=str(seed.get("email") or ""),
            title_raw=str(seed.get("title") or ""),
            homepage=profile_url,
            failure_reasons=("profile_fetch_failed",),
        )
        self.database.add_candidate(
            task_id,
            school_id,
            extraction,
            direction=policy.discipline,
            source_url=profile_url,
            status="review",
            review_reason=f"profile_fetch_failed;{error[:300]}",
        )

    def _emit(
        self,
        callback: Callable[[dict[str, Any]], None] | None,
        task_id: str,
        **event: Any,
    ) -> None:
        if callback:
            callback({"task_id": task_id, **event, "summary": self.database.summary(task_id)})


def _needs_escalation(extraction: CandidateExtraction) -> bool:
    """Reserve the expensive model for near-pass professional-boundary disputes.

    Missing evidence, uncertain ownership, group pages, and obvious irrelevance cannot
    become exportable through a second model opinion; they go to review instead.
    """
    return bool(
        extraction.professional_relevance == "uncertain"
        and extraction.email_ownership == "verified"
        and extraction.homepage_identity == "verified"
        and not extraction.group_homepage
        and all((
            extraction.name,
            extraction.email,
            extraction.normalized_title,
            extraction.department,
            extraction.homepage,
        ))
    )


def _hard_exclusion(seed: dict[str, str]) -> str:
    """Reject only directory titles that are unambiguously outside the policy."""
    if normalize_key(str(seed.get("name") or "")) in {
        "platformcollaboration", "projectpartners",
    }:
        return "directory_entry_is_not_person"
    title = " ".join((seed.get("title", ""), seed.get("name", ""))).casefold()
    if not title:
        return ""
    # "doctoral researcher" is a substring of "postdoctoral researcher".
    # Postdocs are now an in-scope role, so handle that distinction before
    # applying the student/doctoral-candidate exclusion below.
    if "postdoctoral" in title or "postdoc" in title:
        return ""
    allowed_exception = "assistant professor" in title
    excluded = (
        "doctoral researcher", "phd candidate", "ph.d. candidate", "student",
        "emeritus", "retired", "administration",
        "administrative staff", "technical staff", "technician",
    )
    if any(marker in title for marker in excluded):
        return "directory_title_outside_confirmed_policy"
    if "assistant" in title and not allowed_exception:
        return "directory_title_outside_confirmed_policy"
    return ""


def _profile_excerpt(page_text: str, seed: dict[str, str], *, max_characters: int = 9_000) -> str:
    """Send a bounded, identity-centred slice rather than an entire profile page."""
    text = " ".join((page_text or "").split())
    if len(text) <= max_characters:
        return text
    identity = (seed.get("name") or "").strip()
    position = text.casefold().find(identity.casefold()) if identity else -1
    if position < 0:
        return text[:max_characters]
    start = max(0, position - 1_500)
    end = min(len(text), start + max_characters)
    start = max(0, end - max_characters)
    return text[start:end]


def _merge_directory_card_evidence(
    extraction: CandidateExtraction,
    seed: dict[str, str],
    policy: DisciplinePolicy,
) -> CandidateExtraction:
    """Merge fields parsed from an official directory card with its linked profile.

    A directory card is the primary source for the card's name, title and email;
    the personal page remains the primary source for the profile-specific fields.
    This avoids making the model rediscover a title that was already extracted
    deterministically from an official source.
    """
    directory_evidence = _seed_directory_evidence(seed)
    if not directory_evidence:
        return extraction

    name = extraction.name or str(seed.get("name") or "")
    title_raw = str(seed.get("title") or "") or extraction.title_raw
    normalized_title = _normalize_directory_title(title_raw, policy) or extraction.normalized_title
    seed_email = str(seed.get("email") or "").strip().casefold()
    email = extraction.email or seed_email
    evidence = list(extraction.evidence)
    existing = {(item.field, item.source_url, item.quote) for item in evidence}
    for item in directory_evidence:
        directory_url = str(item.get("source_url") or "")
        quote = str(item.get("quote") or "")
        extraction_method = str(item.get("extraction_method") or "directory_card")
        if not directory_url or not quote:
            continue
        for field, value in (("name", name), ("title", title_raw), ("email", seed_email)):
            if field == "email" and value.casefold() not in quote.casefold():
                continue
            key = (field, directory_url, quote)
            if value and key not in existing:
                evidence.append(Evidence(field, quote, directory_url, extraction_method, "supported"))
                existing.add(key)

    email_ownership = extraction.email_ownership
    homepage_identity = extraction.homepage_identity
    failure_reasons = list(extraction.failure_reasons)
    if seed_email and email.casefold() == seed_email:
        email_ownership = "verified"
        failure_reasons = [reason for reason in failure_reasons if reason != "email_not_present_in_profile_page"]
    if name and seed.get("profile_url") and str(seed.get("profile_url")) == extraction.homepage:
        homepage_identity = "verified"
        failure_reasons = [reason for reason in failure_reasons if reason != "name_not_present_in_profile_page"]
    return replace(
        extraction,
        name=name,
        title_raw=title_raw,
        normalized_title=normalized_title,
        email=email,
        email_ownership=email_ownership,
        homepage_identity=homepage_identity,
        evidence=tuple(evidence),
        failure_reasons=tuple(dict.fromkeys(failure_reasons)),
    )


def _directory_only_extraction(
    seed: dict[str, str],
    policy: DisciplinePolicy,
) -> CandidateExtraction:
    """Build a grounded candidate from a paired directory card without inventing a homepage."""
    name = _clean_local_name(str(seed.get("name") or ""), policy)
    title_raw = str(seed.get("title") or "").strip()
    extraction = CandidateExtraction(
        name=name,
        email=str(seed.get("email") or "").strip().casefold(),
        last_name=_local_last_name(name),
        title_raw=title_raw,
        normalized_title=_normalize_directory_title(title_raw, policy),
        homepage="",
        email_ownership="uncertain",
        homepage_identity="not_found",
    )
    return _merge_directory_card_evidence(extraction, seed, policy)


def _directory_fast_path_candidate(
    database: WorkflowDatabase,
    task_id: str,
    school_id: int,
    school_name: str,
    seed: dict[str, str],
    policy: DisciplinePolicy,
    trusted_source_domain: str,
    official_domain: str,
    title_pipeline: TitlePipeline,
) -> tuple[CandidateExtraction, QualityDecision] | None:
    """Return a complete official directory candidate without requiring its optional profile."""
    if _hard_exclusion(seed):
        return None
    directory_url = str(seed.get("directory_url") or "")
    extraction = _apply_title_pipeline(
        _directory_only_extraction(seed, policy),
        title_pipeline,
        policy,
    )
    extraction = replace(
        extraction,
        official_source=bool(
            trusted_source_domain and url_is_on_domain(directory_url, trusted_source_domain)
        ),
    )
    decision = evaluate_candidate(
        database,
        task_id,
        school_id,
        school_name,
        extraction,
        policy,
        official_domain=official_domain,
    )
    return (extraction, decision) if decision.status == "accepted" else None


def _school_identifier_from_url(value: str) -> str:
    host = (urlparse(value).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _merge_official_email_resolution(
    extraction: CandidateExtraction,
    resolution: EmailResolution,
) -> CandidateExtraction:
    """Replace an uncertain address with a printed, name-matched official address."""
    evidence = [
        item for item in extraction.evidence
        if item.field != "email" or resolution.email.casefold() in item.quote.casefold()
    ]
    if not any(
        item.field == "email"
        and item.source_url == resolution.source_url
        and resolution.email.casefold() in item.quote.casefold()
        for item in evidence
    ):
        evidence.append(Evidence(
            "email",
            resolution.quote,
            resolution.source_url,
            resolution.extraction_method,
            "supported",
        ))
    failures = tuple(
        reason for reason in extraction.failure_reasons
        if reason not in {"email_not_present_in_profile_page", "email_ownership_uncertain"}
    )
    return replace(
        extraction,
        email=resolution.email,
        email_ownership="verified",
        evidence=tuple(evidence),
        failure_reasons=failures,
    )


def _normalize_directory_title(title: str, policy: DisciplinePolicy) -> str:
    """Map a card title without asking the model to infer a known rank."""
    raw = " ".join((title or "").casefold().split())
    if not raw:
        return ""
    mappings = {key.casefold(): value for key, value in policy.title_mappings.items()}
    candidates = list(mappings.items()) + [(item.casefold(), item) for item in policy.allowed_titles]
    for source, normalized in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        if source and source in raw and normalized in policy.allowed_titles:
            return normalized
    return ""


def _apply_title_pipeline(
    extraction: CandidateExtraction,
    title_pipeline: TitlePipeline,
    policy: DisciplinePolicy,
    *,
    language_hint: str = "",
) -> CandidateExtraction:
    """Attach local translation/classification metadata without changing official evidence."""
    processed = title_pipeline.process(extraction.title_raw, language_hint=language_hint)
    classification_value = getattr(processed.classification.classification, "value", "")
    normalized_title = extraction.normalized_title
    if not normalized_title and classification_value == "include":
        normalized_title = _normalize_directory_title(
            processed.title_translated or processed.title_original,
            policy,
        )
    return replace(
        extraction,
        title_raw=processed.title_original,
        normalized_title=normalized_title,
        title_translated=processed.title_translated,
        title_language=processed.title_language,
        translation_status=processed.translation_status,
        translation_engine=processed.translation_engine,
        classification_rules_version=processed.rules_version,
    )


def _page_language_hint(page: FetchedPage) -> str:
    match = re.search(r"<html\b[^>]*\blang\s*=\s*['\"]?([^\s'\">]+)", page.html or "", re.IGNORECASE)
    return match.group(1) if match else ""


def _load_cached_source_page(source: Any, requested_url: str) -> FetchedPage | None:
    """Rehydrate a successful persisted HTML or PDF snapshot for deterministic reprocessing."""
    try:
        if str(source["fetch_state"] or "") != "fetched":
            return None
        snapshot_path = Path(str(source["snapshot_path"] or ""))
        if not snapshot_path.is_file():
            return None
        if snapshot_path.suffix.casefold() == ".pdf":
            if snapshot_path.stat().st_size > 20_000_000:
                return None
            title, text = extract_pdf_text(snapshot_path.read_bytes())
            return FetchedPage(
                requested_url=requested_url,
                final_url=str(source["final_url"] or requested_url),
                http_status=source["http_status"],
                title=title or snapshot_path.name,
                html="",
                text=text,
                content_hash=str(source["content_hash"] or ""),
                snapshot_path=snapshot_path,
            )
        with gzip.open(snapshot_path, "rb") as handle:
            html = handle.read().decode("utf-8", errors="replace")
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = html_to_text(title_match.group(1)) if title_match else ""
        return FetchedPage(
            requested_url=requested_url,
            final_url=str(source["final_url"] or requested_url),
            http_status=source["http_status"],
            title=title,
            html=html,
            text=html_to_text(html),
            content_hash=str(source["content_hash"] or ""),
            snapshot_path=snapshot_path,
        )
    except (KeyError, OSError, PdfDocumentError):
        return None


def _apply_relevance_rule(
    extraction: CandidateExtraction,
    page: FetchedPage,
    policy: DisciplinePolicy,
) -> CandidateExtraction:
    """Use explicit discipline/unit terminology before a model's broad judgement."""
    searchable = " ".join((page.title or "", page.text or ""))
    phrases = [policy.discipline, *policy.include_topics, *_discipline_aliases(policy.discipline)]
    for phrase in sorted({item.strip() for item in phrases if item.strip()}, key=len, reverse=True):
        match = re.search(re.escape(phrase), searchable, flags=re.IGNORECASE)
        if not match:
            continue
        quote = searchable[match.start():match.end()]
        evidence = list(extraction.evidence)
        if not any(item.field == "professional_relevance" and item.status == "supported" for item in evidence):
            evidence.append(Evidence("professional_relevance", quote, page.final_url, "discipline_rule", "supported"))
        return replace(extraction, professional_relevance="relevant", evidence=tuple(evidence))
    return extraction


def _discipline_aliases(discipline: str) -> tuple[str, ...]:
    """Small, evidence-only multilingual aliases for common discipline names."""
    aliases = {"physics": ("physik", "física", "fisica", "физика")}
    return aliases.get((discipline or "").strip().casefold(), ())


def _local_profile_extraction(
    page: FetchedPage,
    seed: dict[str, str],
    policy: DisciplinePolicy,
) -> CandidateExtraction:
    """Extract only literal, low-risk fields when a task has model use disabled."""
    text = page.text or ""
    profile_record: DirectoryRecord | None = None
    profile_path = urlparse(page.final_url).path.casefold()
    if any(marker in profile_path for marker in (
        "/people/", "/person/", "/persons/", "/profile/", "/profiles/",
        "/employee/", "/employees/", "/userprofile/",
    )):
        parsed_profile = UniversalDirectoryAdapter().extract(page.html, page.final_url)
        if len(parsed_profile.records) == 1:
            profile_record = parsed_profile.records[0]
    department_match = re.search(
        r"\b(?:department|school|institute|faculty|centre|center|laboratory|lab)\s+(?:of|for)\s+[^\n,.;:]{2,100}"
        r"|\b(?:(?:[ivx]+\.\s*)?physikalisches\s+institut|institut\s+für|fachbereich|departamento\s+de|instituto\s+de|кафедра)(?:\s+[^\n,.;:]{1,100})?",
        text,
        flags=re.IGNORECASE,
    )
    name = _clean_local_name(
        profile_record.name if profile_record is not None else str(seed.get("name") or ""),
        policy,
    )
    # Directory-card addresses remain useful, but profile-page addresses are selected
    # later by OfficialEmailResolver rather than taking the first address on the page.
    email = str(
        (profile_record.email if profile_record is not None else "")
        or seed.get("email")
        or ""
    ).strip().casefold()
    department = department_match.group(0).strip() if department_match else ""
    title_raw = str(
        (profile_record.title if profile_record is not None else "")
        or seed.get("title")
        or ""
    ).strip()
    if not title_raw:
        title_raw = _local_title_from_page(text, policy)
    normalized_title = _normalize_directory_title(title_raw, policy)
    evidence: list[Evidence] = []
    if department:
        evidence.append(Evidence("department", department, page.final_url, "local_pattern", "supported"))
    if title_raw:
        evidence.append(Evidence("title", title_raw, page.final_url, "local_pattern", "supported"))
    if profile_record is not None:
        if name:
            evidence.append(Evidence(
                "name", profile_record.quote or name, page.final_url,
                profile_record.extraction_method, "supported",
            ))
        if email:
            evidence.append(Evidence(
                "email", profile_record.quote or email, page.final_url,
                profile_record.extraction_method, "supported",
            ))
    return CandidateExtraction(
        name=name,
        email=email,
        last_name=_local_last_name(name),
        title_raw=title_raw,
        normalized_title=normalized_title,
        department=department,
        homepage=page.final_url,
        professional_relevance="uncertain",
        email_ownership="verified" if profile_record is not None and email else "uncertain",
        homepage_identity="verified" if profile_record is not None and name else "uncertain",
        evidence=tuple(evidence),
    )


def _local_last_name(name: str) -> str:
    if "," in name:
        return name.split(",", 1)[0].strip()
    parts = [part for part in re.split(r"\s+", name.strip()) if part]
    return parts[-1] if len(parts) >= 2 else ""


def _clean_local_name(name: str, policy: DisciplinePolicy) -> str:
    """Remove a directory role appended to a person's display name, never inner text."""
    result = " ".join((name or "").split()).strip(" ,|")
    suffixes = {
        *policy.allowed_titles,
        *policy.title_mappings.keys(),
        "Academy Research Fellow",
        "Full Professor",
        "Postdoctoral Fellow",
        "University Lecturer",
        "University Teacher",
    }
    changed = True
    while changed and result:
        changed = False
        for suffix in sorted((item.strip() for item in suffixes if item.strip()), key=len, reverse=True):
            updated = re.sub(rf"(?:\s+|,\s*){re.escape(suffix)}\s*$", "", result, flags=re.IGNORECASE).strip(" ,|")
            if updated != result:
                result = updated
                changed = True
                break
    return result


def _local_title_from_page(text: str, policy: DisciplinePolicy) -> str:
    """Return only an explicitly printed in-scope title from a profile page."""
    candidates = [*policy.title_mappings.keys(), *policy.allowed_titles]
    for title in sorted({item for item in candidates if item}, key=len, reverse=True):
        match = re.search(re.escape(title), text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _ground_extraction(extraction: CandidateExtraction, page: FetchedPage) -> CandidateExtraction:
    """Downgrade model claims that are not literally grounded in the fetched page."""
    normalized_text = _normalize_evidence_text(page.text)
    grounded: list[Evidence] = []
    for item in extraction.evidence:
        quote_present = bool(
            item.quote
            and _normalize_evidence_text(item.quote) in normalized_text
            and item.source_url in {page.final_url, page.requested_url}
        )
        if item.extraction_method == "model" and item.status == "supported" and not quote_present:
            grounded.append(replace(item, status="ambiguous"))
        else:
            grounded.append(item)

    failure_reasons = list(extraction.failure_reasons)
    email_ownership = extraction.email_ownership
    if extraction.email and extraction.email.casefold() not in page.text.casefold():
        email_ownership = "uncertain"
        failure_reasons.append("email_not_present_in_profile_page")

    homepage_identity = extraction.homepage_identity
    if extraction.name and _normalize_evidence_text(extraction.name) not in normalized_text:
        homepage_identity = "uncertain"
        failure_reasons.append("name_not_present_in_profile_page")

    return replace(
        extraction,
        evidence=tuple(grounded),
        email_ownership=email_ownership,
        homepage_identity=homepage_identity,
        failure_reasons=tuple(dict.fromkeys(failure_reasons)),
    )


def _normalize_evidence_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _faculty_seed(record: FacultyRecord, directory_url: str) -> dict[str, str]:
    return {
        "name": record.name,
        "title": record.title,
        "profile_url": record.profile_url,
        "email": record.email,
        "directory_url": directory_url,
        "directory_quote": " | ".join(part for part in (record.name, record.title, record.email) if part),
        "extraction_method": "legacy_directory_parser",
    }


def _pending_seed(record: TitlePendingRecord, directory_url: str) -> dict[str, str]:
    return {
        "name": record.name,
        "title": record.directory_title,
        "profile_url": record.profile_url,
        "email": record.email,
        "directory_url": directory_url,
        "directory_quote": " | ".join(part for part in (record.name, record.directory_title, record.email) if part),
        "extraction_method": "legacy_directory_pending",
    }


def _directory_adapter_seed(record: DirectoryRecord, directory_url: str) -> dict[str, str]:
    return {
        "name": record.name,
        "title": record.title,
        "profile_url": record.profile_url,
        "email": record.email,
        "directory_url": directory_url,
        "directory_quote": record.quote,
        "extraction_method": record.extraction_method,
    }


def _seed_directory_evidence(seed: dict[str, Any]) -> list[dict[str, str]]:
    values = seed.get("directory_evidence")
    if isinstance(values, list):
        return [dict(item) for item in values if isinstance(item, dict)]
    source_url = str(seed.get("directory_url") or "")
    quote = str(seed.get("directory_quote") or "")
    if not source_url or not quote:
        return []
    return [{
        "source_url": source_url,
        "quote": quote,
        "extraction_method": str(seed.get("extraction_method") or "directory_card"),
    }]


def _store_directory_seed(
    seeds: dict[str, dict[str, Any]],
    incoming: dict[str, Any],
) -> None:
    """Merge exact-name records from official secondary pages before extraction."""
    incoming = dict(incoming)
    if re.search(
        r"\b(?:lab|laboratory)\s*$",
        str(incoming.get("name") or ""),
        flags=re.IGNORECASE,
    ):
        return
    incoming["directory_evidence"] = _seed_directory_evidence(incoming)
    key = _directory_seed_key(incoming)
    existing_key = key if key in seeds else ""
    name_key = normalize_key(str(incoming.get("name") or ""))
    if existing_key and name_key:
        existing_name_key = normalize_key(str(seeds[existing_key].get("name") or ""))
        if existing_name_key and existing_name_key != name_key:
            existing_key = ""
            key = f"{key}#person={name_key}"
    if not existing_key and name_key:
        name_matches = [
            candidate_key for candidate_key, candidate in seeds.items()
            if normalize_key(str(candidate.get("name") or "")) == name_key
        ]
        if len(name_matches) == 1:
            existing_key = name_matches[0]
    if not existing_key:
        seeds[key] = incoming
        return

    existing = seeds[existing_key]
    merged = dict(existing)
    for field in ("name", "title", "profile_url", "directory_url", "directory_quote", "extraction_method"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]
    emails = {
        normalize_email(str(value or ""))
        for value in (existing.get("email"), incoming.get("email"))
        if normalize_email(str(value or ""))
    }
    merged["email"] = next(iter(emails)) if len(emails) == 1 else ""
    evidence: list[dict[str, str]] = []
    seen_evidence: set[tuple[str, str, str]] = set()
    for item in (*_seed_directory_evidence(existing), *_seed_directory_evidence(incoming)):
        evidence_key = (
            str(item.get("source_url") or ""),
            str(item.get("quote") or ""),
            str(item.get("extraction_method") or ""),
        )
        if evidence_key not in seen_evidence:
            seen_evidence.add(evidence_key)
            evidence.append(item)
    merged["directory_evidence"] = evidence
    seeds[existing_key] = merged


def _directory_seed_key(seed: dict[str, str]) -> str:
    profile_url = normalize_url(str(seed.get("profile_url") or ""))
    if profile_url:
        return profile_url
    return "directory:" + ":".join((
        normalize_key(str(seed.get("name") or "")),
        normalize_email(str(seed.get("email") or "")),
        normalize_url(str(seed.get("directory_url") or "")),
    ))


def _clean_domain(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if "://" in text:
        text = urlparse(text).hostname or ""
    return text.strip("./ ")
