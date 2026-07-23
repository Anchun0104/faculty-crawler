from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from crawler.privacy import is_sensitive_key, safe_exception_message


@dataclass(frozen=True)
class DiagnosticEvent:
    run_id: str
    task_id: str
    stage: str
    category: str
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    path: Path
    created_at: datetime
    submitted_at: datetime | None


class DiagnosticRecorder:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def record(self, event: DiagnosticEvent) -> None:
        self.events.append(_safe_event(event))


def build_problem_report(
    run_id: str,
    events: list[DiagnosticEvent],
    output_path: Path,
    screenshots: tuple[Path, ...] = (),
) -> Path:
    safe_events = [asdict(_safe_event(event)) for event in events]
    summary = (
        f"批次 {_safe_text(run_id)}\n"
        f"问题任务：{len({item['task_id'] for item in safe_events})}\n"
    )
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["task_id", "stage", "category", "message"])
    writer.writerows(
        (item["task_id"], item["stage"], item["category"], item["message"])
        for item in safe_events
    )
    log_text = "\n".join(
        f"{item['task_id']} {item['stage']} {item['category']} {item['message']}"
        for item in safe_events
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("summary.txt", summary)
        archive.writestr(
            "diagnostics.json",
            json.dumps(safe_events, ensure_ascii=False, indent=2),
        )
        archive.writestr("failed-tasks.csv", csv_buffer.getvalue())
        archive.writestr("application.log", log_text)
        for screenshot in screenshots:
            archive.write(screenshot, f"screenshots/{screenshot.name}")
    write_report_metadata(
        ReportRecord(
            output_path.stem,
            output_path,
            datetime.now(timezone.utc),
            None,
        )
    )
    return output_path


def report_metadata_path(path: Path) -> Path:
    return Path(path).with_suffix(Path(path).suffix + ".json")


def write_report_metadata(record: ReportRecord) -> Path:
    _validate_report_record(record)
    target = report_metadata_path(record.path)
    _atomic_json_write(target, _report_metadata_payload(record))
    return target


def _report_metadata_payload(record: ReportRecord) -> dict[str, object]:
    return {
        "report_id": record.report_id,
        "path": str(record.path),
        "created_at": _timestamp(record.created_at),
        "submitted_at": (
            _timestamp(record.submitted_at) if record.submitted_at is not None else None
        ),
    }


def load_report_metadata(
    path: Path,
    *,
    expected_report_id: str | None = None,
) -> ReportRecord:
    requested_path = Path(path)
    metadata_path = report_metadata_path(requested_path)
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("report metadata is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "report_id", "path", "created_at", "submitted_at"
    }:
        raise ValueError("report metadata is invalid")
    try:
        created_at = datetime.fromisoformat(payload["created_at"])
        submitted_at = (
            datetime.fromisoformat(payload["submitted_at"])
            if payload["submitted_at"] is not None
            else None
        )
        record = ReportRecord(
            payload["report_id"], Path(payload["path"]), created_at, submitted_at
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("report metadata is invalid") from exc
    _validate_report_record(record)
    if record.path != requested_path or (
        expected_report_id is not None
        and record.report_id != expected_report_id
    ):
        raise ValueError("report metadata identity does not match request")
    return record


def mark_report_submitted(
    record: ReportRecord,
    submitted_at: datetime | None = None,
) -> ReportRecord:
    _validate_report_record(record)
    target = report_metadata_path(record.path)
    if target.exists():
        current = load_report_metadata(
            record.path,
            expected_report_id=record.report_id,
        )
    else:
        current = record
    marked = replace(
        current,
        submitted_at=submitted_at or datetime.now(timezone.utc),
    )
    _atomic_json_write(target, _report_metadata_payload(marked))
    return marked


def _validate_report_record(record: ReportRecord) -> None:
    if not isinstance(record.report_id, str) or not record.report_id:
        raise ValueError("report_id must be non-empty")
    if not isinstance(record.path, Path):
        raise TypeError("report path must be a Path")
    _timestamp(record.created_at)
    if record.submitted_at is not None:
        _timestamp(record.submitted_at)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("report timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _atomic_json_write(target: Path, payload: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _safe_event(event: DiagnosticEvent) -> DiagnosticEvent:
    return DiagnosticEvent(
        _safe_text(event.run_id),
        _safe_text(event.task_id),
        _safe_text(event.stage),
        _safe_text(event.category),
        _safe_text(event.message),
        _safe_detail_mapping(event.details),
    )


def _safe_text(value: str) -> str:
    return safe_exception_message(RuntimeError(value))


def _safe_detail_mapping(value: Mapping[object, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, item in value.items():
        key_text = str(key)
        if not is_sensitive_key(key_text):
            safe[_safe_text(key_text)] = _safe_detail_value(item)
    return safe


def _safe_detail_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _safe_detail_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_detail_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value if isinstance(value, str) else str(value))
