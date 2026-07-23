from __future__ import annotations

import argparse
import logging
import sys
from urllib.parse import urlparse

from crawler.faculty_crawler import FacultyCrawler, export_title_pending_to_excel, export_to_excel
from crawler.models import CrawlOutcome, TaskStatus
from crawler.privacy import safe_exception_message


DEFAULT_OUTPUT = "output/faculty_data.xlsx"
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect faculty directory data and export it to Excel.")
    parser.add_argument("url", help="Faculty directory URL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Excel output path. Default: {DEFAULT_OUTPUT}")
    parser.add_argument("--timeout", type=int, default=30000, help="Browser timeout in milliseconds.")
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not is_valid_url(args.url):
        print("Invalid URL: please provide a full http:// or https:// faculty directory URL.", file=sys.stderr)
        return 2

    try:
        crawler = FacultyCrawler(timeout=args.timeout)
        outcome_method = getattr(type(crawler), "crawl_outcome", None)
        if callable(outcome_method):
            outcome = outcome_method(crawler, args.url)
        else:
            legacy_records = crawler.crawl(args.url)
            legacy_diagnostics = getattr(crawler, "last_diagnostics", {})
            if not isinstance(legacy_diagnostics, dict):
                legacy_diagnostics = {}
            outcome = CrawlOutcome(
                TaskStatus.SUCCEEDED if legacy_records else TaskStatus.FAILED,
                tuple(legacy_records),
                tuple(crawler.title_pending_records),
                dict(legacy_diagnostics),
            )
        if outcome.status not in {
            TaskStatus.SUCCEEDED,
            TaskStatus.REVIEW_RECOMMENDED,
        }:
            reason = outcome.diagnostics.get("Failure reason") or "No faculty records were parsed"
            raise RuntimeError(str(reason))
        records = list(outcome.records)
        export_to_excel(records, args.output)
        pending_records = list(outcome.pending_titles)
        pending_path = export_title_pending_to_excel(pending_records, args.output)
    except Exception as exc:
        logging.error("%s", safe_exception_message(exc))
        return 1

    logger.info("Title pending records: %s", len(pending_records))
    if pending_path is not None:
        logger.info("Title pending output: %s", pending_path)
    if outcome.status == TaskStatus.REVIEW_RECOMMENDED:
        logger.warning(
            "Review recommended: exported %s records to %s; inspect the result before use.",
            len(records),
            args.output,
        )
    logging.info("Done. Wrote %s records to %s.", len(records), args.output)
    return 0


def is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


if __name__ == "__main__":
    raise SystemExit(main())
