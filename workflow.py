from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.ai_settings import ProviderConfiguration
from faculty_workflow.models import DisciplinePolicy
from faculty_workflow.providers import DeepSeekProvider, OpenAICompatibleProvider
from faculty_workflow.service import WorkflowService


DEFAULT_DATABASE = "workflow_data/workflow.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-first professional faculty collection workflow using DeepSeek")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help=f"SQLite database. Default: {DEFAULT_DATABASE}")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ai-provider", choices=("local", "deepseek", "compatible"), default="local")
    parser.add_argument("--ai-base-url", default="", help="HTTPS API base URL; required for compatible providers")
    parser.add_argument("--ai-model", default="", help="Model for a compatible provider")
    parser.add_argument("--ai-key-env", default="FACULTY_CRAWLER_API_KEY", help="Environment variable containing the API key")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="Create a task and draft its discipline policy")
    new.add_argument(
        "--schools",
        required=True,
        help="CSV/XLSX school list; every school requires a verified directory_url",
    )
    new.add_argument("--discipline", required=True)
    new.add_argument("--output-dir", required=True)
    new.add_argument("--budget-usd", type=float, default=20.0)
    new.add_argument("--history", action="append", default=[], help="Historical CSV/XLSX/JSON; repeatable")
    new.add_argument("--processed-schools", action="append", default=[], help="Processed-school file; repeatable")
    new.add_argument("--no-ai-policy", action="store_true", help="Create a local draft without calling DeepSeek")
    new.add_argument("--no-model", action="store_true", help="Never call DeepSeek; use only supplied directory URLs and local rules")
    new.add_argument("--routine-model", default="deepseek-v4-flash")
    new.add_argument("--escalation-model", default="deepseek-v4-pro")

    direct = commands.add_parser("url", help="Create and run an evidence-first task from one or more verified directory URLs")
    direct.add_argument("directory_urls", nargs="+", help="Verified faculty or staff directory URLs")
    direct.add_argument("--output-dir", required=True)
    direct.add_argument("--school", default="", help="Optional school name; available when one URL is supplied")
    direct.add_argument("--discipline", default="General Faculty")
    direct.add_argument("--budget-usd", type=float, default=20.0)
    direct.add_argument("--use-ai", action="store_true", help="Use the explicitly configured model only for supplied-page extraction")
    direct.add_argument("--routine-model", default="deepseek-v4-flash")
    direct.add_argument("--escalation-model", default="deepseek-v4-pro")

    policy = commands.add_parser("policy", help="Show or confirm a task policy")
    policy.add_argument("--task", required=True)
    policy.add_argument("--file", help="Confirmed policy JSON")
    policy.add_argument("--confirm", action="store_true")

    run = commands.add_parser("run", help="Run or resume a confirmed task")
    run.add_argument("--task", required=True)

    reprocess_reviews = commands.add_parser(
        "reprocess-reviews",
        help="Start or resume a review-only generation; completed rows are preserved",
    )
    reprocess_reviews.add_argument("--task", required=True)

    reopen_unresolved = commands.add_parser(
        "reopen-unresolved",
        help="Explicitly reopen unresolved rows after a rule, source, or access change",
    )
    reopen_unresolved.add_argument("--task", required=True)
    reopen_unresolved.add_argument("--candidate", type=int, nargs="+", required=True)
    reopen_unresolved.add_argument("--reason", required=True)

    status = commands.add_parser("status", help="Print task status")
    status.add_argument("--task", required=True)

    export = commands.add_parser("export", help="Export final, review, and audit files")
    export.add_argument("--task", required=True)
    export.add_argument("--output-dir")

    review = commands.add_parser("review", help="List or decide review candidates")
    review.add_argument("--task", required=True)
    review.add_argument("--candidate", type=int)
    review.add_argument("--decision", choices=("accepted", "rejected", "review"))
    review.add_argument("--note", default="")
    review.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")

    budget = commands.add_parser("budget", help="Increase or replace a task budget")
    budget.add_argument("--task", required=True)
    budget.add_argument("--budget-usd", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    database = WorkflowDatabase(args.database)
    service = WorkflowService(database, provider=provider_from_args(args) or DeepSeekProvider(api_key=""))
    try:
        if args.command == "new":
            ai_enabled = args.ai_provider != "local" and not args.no_model
            routine_model = args.ai_model or args.routine_model
            escalation_model = args.ai_model or args.escalation_model
            task_id = service.create_task(
                schools_path=args.schools,
                discipline=args.discipline,
                output_dir=args.output_dir,
                budget_usd=args.budget_usd,
                history_paths=args.history,
                processed_school_paths=args.processed_schools,
                generate_ai_policy=ai_enabled and not args.no_ai_policy,
                routine_model=routine_model if ai_enabled else "local-only",
                escalation_model=escalation_model if ai_enabled else "local-only",
            )
            _print({"task_id": task_id, "policy": json.loads(database.get_policy(task_id).to_json()), "status": database.summary(task_id)})
        elif args.command == "url":
            if args.use_ai and args.ai_provider == "local":
                raise ValueError("--use-ai requires --ai-provider deepseek or compatible")
            task_id = service.create_direct_url_task(
                directory_urls=args.directory_urls,
                output_dir=args.output_dir,
                school_name=args.school,
                discipline=args.discipline,
                use_ai=args.use_ai,
                routine_model=args.ai_model or args.routine_model,
                escalation_model=args.ai_model or args.escalation_model,
                budget_usd=args.budget_usd,
            )
            _print(service.run_task(task_id))
        elif args.command == "policy":
            if args.confirm:
                if not args.file:
                    raise ValueError("--file is required with --confirm")
                policy = DisciplinePolicy.from_json(Path(args.file).read_text(encoding="utf-8-sig"))
                service.confirm_policy(args.task, policy)
            _print({"task_id": args.task, "policy": json.loads(database.get_policy(args.task).to_json()), "status": database.summary(args.task)})
        elif args.command == "run":
            _print(service.run_task(args.task))
        elif args.command == "reprocess-reviews":
            _print(service.run_review_generation(args.task))
        elif args.command == "reopen-unresolved":
            _print(service.reopen_unresolved(
                args.task, candidate_ids=args.candidate, reason=args.reason
            ))
        elif args.command == "status":
            _print(database.summary(args.task))
        elif args.command == "export":
            _print({key: str(value) for key, value in service.export(args.task, args.output_dir).items()})
        elif args.command == "review":
            if args.candidate is None:
                _print([dict(row) for row in database.list_candidates(args.task, ["review", "candidate"])])
            else:
                if not args.decision:
                    raise ValueError("--decision is required with --candidate")
                database.decide_candidate(
                    args.candidate,
                    args.decision,
                    note=args.note,
                    edits=_parse_edits(args.set),
                )
                _print({"candidate": args.candidate, "decision": args.decision})
        elif args.command == "budget":
            database.set_budget(args.task, args.budget_usd)
            _print(database.summary(args.task))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1
    return 0


def provider_from_args(args: argparse.Namespace):
    if args.ai_provider == "local":
        return None
    api_key = os.environ.get(args.ai_key_env, "")
    if args.ai_provider == "deepseek":
        config = (
            ProviderConfiguration(True, "deepseek", args.ai_base_url, args.ai_model or "deepseek-v4-flash")
            if args.ai_base_url else ProviderConfiguration.deepseek(model=args.ai_model or "deepseek-v4-flash")
        )
        return DeepSeekProvider(api_key=api_key, endpoint=config.endpoint)
    config = ProviderConfiguration(True, "compatible", args.ai_base_url, args.ai_model)
    return OpenAICompatibleProvider(api_key=api_key, endpoint=config.endpoint)


def _parse_edits(values: list[str]) -> dict[str, str]:
    edits: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Edit must use FIELD=VALUE: {value}")
        field, content = value.split("=", 1)
        edits[field.strip()] = content.strip()
    return edits


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
