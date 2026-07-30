from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import Counter

from crawler.parsers import find_linked_directory_sources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("task")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    review_reasons = connection.execute(
        """SELECT s.name AS school, c.review_reason, COUNT(*) AS count
           FROM candidates c JOIN schools s ON s.id = c.school_id
           WHERE c.task_id = ? AND c.status = 'review'
           GROUP BY s.name, c.review_reason ORDER BY s.name, count DESC""",
        (args.task,),
    ).fetchall()
    accepted_names = [
        row["name"] for row in connection.execute(
            "SELECT name FROM candidates WHERE task_id = ? AND status = 'accepted' ORDER BY name",
            (args.task,),
        ).fetchall()
    ]
    source_states = connection.execute(
        """SELECT s.name AS school, so.source_type, so.fetch_state,
                  so.failure_reason, so.stop_reason, COUNT(*) AS count
           FROM sources so JOIN schools s ON s.id = so.school_id
           WHERE so.task_id = ?
           GROUP BY s.name, so.source_type, so.fetch_state, so.failure_reason, so.stop_reason
           ORDER BY s.name, so.source_type, so.fetch_state""",
        (args.task,),
    ).fetchall()
    directory_snapshots = [
        dict(row) for row in connection.execute(
            """SELECT url, final_url, snapshot_path FROM sources
               WHERE task_id = ? AND source_type = 'faculty_directory'""",
            (args.task,),
        ).fetchall()
    ]
    profile_sources = connection.execute(
        """SELECT s.name AS school, s.official_domain, so.final_url, so.snapshot_path
           FROM sources so JOIN schools s ON s.id = so.school_id
           WHERE so.task_id = ? AND so.source_type = 'person_profile'
             AND so.snapshot_path != ''""",
        (args.task,),
    ).fetchall()
    linked_sources = []
    for source in profile_sources:
        try:
            with gzip.open(source["snapshot_path"], "rb") as handle:
                html = handle.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for url, source_type in find_linked_directory_sources(
            html, source["final_url"], source["official_domain"]
        ):
            linked_sources.append({
                "school": source["school"],
                "profile": source["final_url"],
                "url": url,
                "source_type": source_type,
            })
    print(json.dumps({
        "review_reasons": [dict(row) for row in review_reasons],
        "accepted_names": accepted_names,
        "source_states": [dict(row) for row in source_states],
        "directory_snapshots": directory_snapshots,
        "profile_linked_source_counts": dict(Counter(
            item["school"] for item in linked_sources
        )),
        "profile_linked_source_samples": linked_sources[:20],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
