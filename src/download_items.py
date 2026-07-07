import argparse
import csv
import getpass
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MANIFEST = "data/ref/selected_manifest.json"
DEFAULT_REMOTE_PREFIX = "/home/lijingyue/LiangEnRui"
DEFAULT_LOCAL_ROOT = "data/download/cloud_items"
DEFAULT_DB_NAME = "sqlite/download_state.sqlite"

STATUS_PENDING = "pending"
STATUS_DOWNLOADED = "downloaded"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON list")
    return data


def remote_to_local_path(remote_path, remote_prefix, local_root):
    prefix = remote_prefix.rstrip("/")
    if not remote_path.startswith(prefix + "/"):
        raise ValueError(f"remote path is not under prefix: {remote_path}")

    relative = remote_path[len(prefix) :].lstrip("/")
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError(f"bad remote path: {remote_path}")

    return Path(local_root).joinpath(*parts)


def collect_tasks(entries, include_source, remote_prefix, local_root):
    fields = ["item_path"]
    if include_source:
        fields.append("source_item_path")

    tasks = {}
    invalid = []
    for index, entry in enumerate(entries):
        for field in fields:
            remote_path = entry.get(field)
            if not remote_path:
                continue
            try:
                local_path = remote_to_local_path(remote_path, remote_prefix, local_root)
            except ValueError as exc:
                invalid.append((index, field, remote_path, str(exc)))
                continue
            tasks[remote_path] = str(local_path)
    return tasks, invalid


def connect_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            remote_path TEXT PRIMARY KEY,
            local_path TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_round INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            local_size INTEGER,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def init_tasks(conn, tasks):
    now = utc_now()
    rows = [
        (remote_path, local_path, STATUS_PENDING, now)
        for remote_path, local_path in tasks.items()
    ]
    conn.executemany(
        """
        INSERT INTO downloads (remote_path, local_path, status, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(remote_path) DO UPDATE SET
            local_path = excluded.local_path,
            status = CASE
                WHEN downloads.local_path = excluded.local_path
                THEN downloads.status
                ELSE excluded.status
            END,
            attempts = CASE
                WHEN downloads.local_path = excluded.local_path
                THEN downloads.attempts
                ELSE 0
            END,
            last_round = CASE
                WHEN downloads.local_path = excluded.local_path
                THEN downloads.last_round
                ELSE 0
            END,
            last_error = CASE
                WHEN downloads.local_path = excluded.local_path
                THEN downloads.last_error
                ELSE NULL
            END,
            local_size = CASE
                WHEN downloads.local_path = excluded.local_path
                THEN downloads.local_size
                ELSE NULL
            END,
            updated_at = excluded.updated_at
        """,
        rows,
    )
    conn.commit()


def prune_stale_tasks(conn, remote_paths):
    conn.execute("CREATE TEMP TABLE current_tasks (remote_path TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO current_tasks (remote_path) VALUES (?)",
        [(remote_path,) for remote_path in remote_paths],
    )
    conn.execute(
        """
        DELETE FROM downloads
        WHERE remote_path NOT IN (SELECT remote_path FROM current_tasks)
        """
    )
    conn.execute("DROP TABLE current_tasks")
    conn.commit()


def status_counts(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM downloads GROUP BY status"
    ).fetchall()
    counts = {row["status"]: row["count"] for row in rows}
    return {
        STATUS_PENDING: counts.get(STATUS_PENDING, 0),
        STATUS_DOWNLOADED: counts.get(STATUS_DOWNLOADED, 0),
        STATUS_SUCCESS: counts.get(STATUS_SUCCESS, 0),
        STATUS_FAILED: counts.get(STATUS_FAILED, 0),
    }


def validate_json_file(path):
    local_path = Path(path)
    if not local_path.exists():
        return False, "local file is missing", None
    size = local_path.stat().st_size
    if size <= 0:
        return False, "local file is empty", size
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception as exc:
        return False, f"json parse failed: {exc}", size
    return True, None, size


def check_downloaded_files(conn):
    rows = conn.execute(
        "SELECT remote_path, local_path, status FROM downloads WHERE status != ?",
        (STATUS_SUCCESS,),
    ).fetchall()

    checked = 0
    passed = 0
    failed = 0
    now = utc_now()
    for row in rows:
        ok, error, size = validate_json_file(row["local_path"])
        checked += 1
        if ok:
            conn.execute(
                """
                UPDATE downloads
                SET status = ?, last_error = NULL, local_size = ?, updated_at = ?
                WHERE remote_path = ?
                """,
                (STATUS_SUCCESS, size, now, row["remote_path"]),
            )
            passed += 1
        elif row["status"] == STATUS_DOWNLOADED:
            conn.execute(
                """
                UPDATE downloads
                SET status = ?, last_error = ?, local_size = ?, updated_at = ?
                WHERE remote_path = ?
                """,
                (STATUS_FAILED, error, size, now, row["remote_path"]),
            )
            failed += 1
    conn.commit()
    return checked, passed, failed


def rows_to_download(conn, max_attempts):
    return conn.execute(
        """
        SELECT remote_path, local_path, attempts
        FROM downloads
        WHERE status != ? AND attempts < ?
        ORDER BY remote_path
        """,
        (STATUS_SUCCESS, max_attempts),
    ).fetchall()


def mark_downloaded(conn, remote_path, local_path, round_number):
    size = Path(local_path).stat().st_size
    conn.execute(
        """
        UPDATE downloads
        SET status = ?,
            attempts = attempts + 1,
            last_round = ?,
            last_error = NULL,
            local_size = ?,
            updated_at = ?
        WHERE remote_path = ?
        """,
        (STATUS_DOWNLOADED, round_number, size, utc_now(), remote_path),
    )


def mark_download_failed(conn, remote_path, error, round_number):
    conn.execute(
        """
        UPDATE downloads
        SET status = ?,
            attempts = attempts + 1,
            last_round = ?,
            last_error = ?,
            updated_at = ?
        WHERE remote_path = ?
        """,
        (STATUS_FAILED, round_number, str(error), utc_now(), remote_path),
    )


def open_sftp(args):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required for downloading") from exc

    password = None
    if args.password_env:
        password = os.environ.get(args.password_env)
    if args.ask_password:
        password = getpass.getpass("SSH password: ")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=args.host,
        port=args.port,
        username=args.username or getpass.getuser(),
        key_filename=args.key_file,
        password=password,
        timeout=args.connect_timeout,
        allow_agent=True,
        look_for_keys=True,
    )
    return client, client.open_sftp()


def download_one(sftp, remote_path, local_path):
    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    part_path = Path(str(local) + ".part")
    if part_path.exists():
        part_path.unlink()
    sftp.get(remote_path, str(part_path))
    os.replace(part_path, local)


def download_round(conn, sftp, rows, round_number, progress_every):
    total = len(rows)
    ok_count = 0
    failed_count = 0
    for index, row in enumerate(rows, start=1):
        try:
            download_one(sftp, row["remote_path"], row["local_path"])
            mark_downloaded(conn, row["remote_path"], row["local_path"], round_number)
            ok_count += 1
        except Exception as exc:
            part_path = Path(str(row["local_path"]) + ".part")
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass
            mark_download_failed(conn, row["remote_path"], exc, round_number)
            failed_count += 1

        if index % progress_every == 0 or index == total:
            conn.commit()
            print(
                f"round {round_number}: {index}/{total} tried, "
                f"{ok_count} downloaded, {failed_count} failed"
            )
    conn.commit()
    return ok_count, failed_count


def export_failed(conn, path):
    rows = conn.execute(
        """
        SELECT remote_path, local_path, status, attempts, last_round, last_error
        FROM downloads
        WHERE status != ?
        ORDER BY remote_path
        """,
        (STATUS_SUCCESS,),
    ).fetchall()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["remote_path", "local_path", "status", "attempts", "last_round", "last_error"]
        )
        for row in rows:
            writer.writerow(
                [
                    row["remote_path"],
                    row["local_path"],
                    row["status"],
                    row["attempts"],
                    row["last_round"],
                    row["last_error"],
                ]
            )
    return len(rows)


def print_counts(label, counts):
    print(
        f"{label}: pending={counts[STATUS_PENDING]}, "
        f"downloaded={counts[STATUS_DOWNLOADED]}, "
        f"success={counts[STATUS_SUCCESS]}, failed={counts[STATUS_FAILED]}"
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download manifest item JSON files through SFTP with SQLite state."
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--username")
    parser.add_argument("--key-file")
    parser.add_argument("--password-env")
    parser.add_argument("--ask-password", action="store_true")
    parser.add_argument("--connect-timeout", type=float, default=20.0)
    parser.add_argument("--remote-prefix", default=DEFAULT_REMOTE_PREFIX)
    parser.add_argument("--local-root", default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--db-path")
    parser.add_argument("--failed-report")
    parser.add_argument("--include-source", action="store_true")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=200)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")
    if args.progress_every <= 0:
        raise SystemExit("--progress-every must be > 0")

    local_root = Path(args.local_root)
    db_path = Path(args.db_path) if args.db_path else local_root / DEFAULT_DB_NAME
    failed_report = (
        Path(args.failed_report) if args.failed_report else local_root / "failed_items.csv"
    )

    entries = read_manifest(args.manifest)
    tasks, invalid = collect_tasks(
        entries,
        include_source=args.include_source,
        remote_prefix=args.remote_prefix,
        local_root=local_root,
    )

    conn = connect_db(db_path)
    init_tasks(conn, tasks)
    prune_stale_tasks(conn, tasks.keys())

    print(f"manifest rows: {len(entries)}")
    print(f"download tasks: {len(tasks)}")
    print(f"local root: {local_root}")
    print(f"sqlite db: {db_path}")
    if invalid:
        print(f"invalid paths skipped: {len(invalid)}")

    checked, passed, failed = check_downloaded_files(conn)
    print(f"initial check: {checked} checked, {passed} passed, {failed} failed")
    print_counts("initial status", status_counts(conn))

    max_attempts = 1 + args.max_retries
    if status_counts(conn)[STATUS_SUCCESS] < len(tasks):
        client, sftp = open_sftp(args)
        try:
            for round_number in range(1, max_attempts + 1):
                rows = rows_to_download(conn, max_attempts)
                if not rows:
                    break
                print(f"round {round_number}: {len(rows)} files to try")
                download_round(conn, sftp, rows, round_number, args.progress_every)
                checked, passed, failed = check_downloaded_files(conn)
                print(
                    f"round {round_number} check: "
                    f"{checked} checked, {passed} passed, {failed} failed"
                )
                print_counts(f"round {round_number} status", status_counts(conn))

                counts = status_counts(conn)
                if counts[STATUS_SUCCESS] == len(tasks):
                    break
        finally:
            sftp.close()
            client.close()

    failed_count = export_failed(conn, failed_report)
    counts = status_counts(conn)
    print_counts("final status", counts)
    print(f"failed report: {failed_report}")

    if invalid:
        invalid_report = local_root / "invalid_paths.csv"
        invalid_report.parent.mkdir(parents=True, exist_ok=True)
        with open(invalid_report, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["manifest_index", "field", "remote_path", "error"])
            writer.writerows(invalid)
        print(f"invalid path report: {invalid_report}")

    conn.close()

    if failed_count or invalid:
        print("download finished with remaining failed items")
        return 1

    print("download completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
