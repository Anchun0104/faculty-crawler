from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlparse

from faculty_workflow.models import DisciplinePolicy
from faculty_workflow.quality import EMAIL_RE, GENERIC_EMAIL_LOCAL_PARTS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("task")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    policy_row = connection.execute(
        "SELECT policy_json FROM tasks WHERE id = ?", (args.task,)
    ).fetchone()
    if policy_row is None:
        raise SystemExit(f"Unknown task: {args.task}")
    policy = DisciplinePolicy.from_json(policy_row["policy_json"])
    rows = connection.execute(
        """SELECT c.*, s.official_domain
           FROM candidates c JOIN schools s ON s.id = c.school_id
           WHERE c.task_id = ? AND c.status = 'accepted' ORDER BY c.id""",
        (args.task,),
    ).fetchall()
    email_violations: list[dict[str, object]] = []
    legacy_gate_warnings: list[dict[str, object]] = []
    for row in rows:
        reasons = []
        email = str(row["email"] or "").casefold()
        domain = str(row["official_domain"] or "").casefold().removeprefix("www.")
        email_domain = email.rsplit("@", 1)[-1]
        if not EMAIL_RE.fullmatch(email):
            reasons.append("invalid_or_incomplete_email")
        if email.split("@", 1)[0] in GENERIC_EMAIL_LOCAL_PARTS:
            reasons.append("generic_email")
        if not (email_domain == domain or email_domain.endswith("." + domain)):
            reasons.append("email_outside_official_domain")
        if row["normalized_title"] not in policy.allowed_titles:
            reasons.append("role_outside_policy")
        evidence = json.loads(row["evidence_json"] or "[]")
        supported = {
            item.get("field") for item in evidence
            if item.get("status") == "supported"
            and item.get("quote") and item.get("source_url")
            and urlparse(item["source_url"]).scheme in {"http", "https"}
        }
        if not {"name", "email", "title"}.issubset(supported):
            reasons.append("missing_required_official_evidence")
        if not any(
            item.get("field") == "email" and email in str(item.get("quote") or "").casefold()
            for item in evidence
        ):
            reasons.append("email_not_printed_in_evidence")
        email_reasons = [reason for reason in reasons if reason in {
            "invalid_or_incomplete_email", "generic_email", "email_outside_official_domain",
            "email_not_printed_in_evidence",
        }]
        legacy_reasons = [reason for reason in reasons if reason not in email_reasons]
        if email_reasons:
            email_violations.append({"candidate_id": row["id"], "reasons": email_reasons})
        if legacy_reasons:
            legacy_gate_warnings.append({"candidate_id": row["id"], "reasons": legacy_reasons})
    print(json.dumps({
        "task_id": args.task,
        "accepted_rows": len(rows),
        "email_violations": email_violations,
        "preserved_legacy_gate_warnings": legacy_gate_warnings,
    }, ensure_ascii=False, indent=2))
    return 1 if email_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
