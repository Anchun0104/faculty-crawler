from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook

from crawler.parsers import FacultyRecord


EXPORT_COLUMNS = (
    "name",
    "title",
    "title_translated",
    "title_language",
    "translation_status",
    "translation_engine",
    "staff_classification",
    "academic_track",
    "affiliation_status",
    "classification_reason",
    "matched_rule",
    "confidence_tier",
    "source_url",
    "profile_url",
    "email",
    "classification_rules_version",
)


def export_records(
    records: Iterable[FacultyRecord],
    path: str | Path,
    format: str | None = None,
) -> Path:
    output_path = Path(path)
    output_format = _resolve_format(output_path, format)
    record_list = list(records)
    if output_format == "csv":
        _write_csv(record_list, output_path)
    else:
        _write_xlsx(record_list, output_path)
    return output_path


def _resolve_format(path: Path, explicit_format: str | None) -> str:
    value = explicit_format.lower().lstrip(".") if explicit_format else path.suffix.lower().lstrip(".")
    if value not in {"csv", "xlsx"}:
        raise ValueError("format must be csv or xlsx")
    return value


def _row(record: FacultyRecord) -> dict[str, str]:
    return {column: str(getattr(record, column, "")) for column in EXPORT_COLUMNS}


def _write_csv(records: list[FacultyRecord], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(_row(record) for record in records)


def _write_xlsx(records: list[FacultyRecord], path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(list(EXPORT_COLUMNS))
    for record in records:
        row = _row(record)
        worksheet.append([row[column] for column in EXPORT_COLUMNS])
    workbook.save(path)
