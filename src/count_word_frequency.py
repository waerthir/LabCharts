import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path


DEFAULT_MANIFEST = "data/ref/selected_manifest.json"
DEFAULT_REMOTE_PREFIX = "/home/lijingyue/LiangEnRui"
DEFAULT_LOCAL_ROOT = "data/download/cloud_items"
DEFAULT_OUTPUT_DIR = "data/output/word_frequency"
QUESTION_FIELD = ("ready3_open_rewrite", "resolved_question_text")

STOPWORDS = {
    "about",
    "above",
    "according",
    "after",
    "again",
    "against",
    "all",
    "also",
    "among",
    "and",
    "another",
    "any",
    "are",
    "area",
    "areas",
    "around",
    "based",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "can",
    "cannot",
    "could",
    "describe",
    "does",
    "each",
    "following",
    "for",
    "from",
    "given",
    "has",
    "have",
    "how",
    "into",
    "its",
    "most",
    "not",
    "now",
    "one",
    "only",
    "other",
    "part",
    "parts",
    "point",
    "points",
    "same",
    "several",
    "shown",
    "shows",
    "such",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "through",
    "using",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}


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


def get_question_text(item):
    value = item
    for key in QUESTION_FIELD:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def normalize_text(text):
    text = text.lower()
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\$+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text


def tokenize(text, min_length):
    tokens = []
    for token in normalize_text(text).split():
        if len(token) < min_length:
            continue
        if token.isdigit():
            continue
        if token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def write_word_freq(path, word_counts, doc_counts):
    rows = sorted(word_counts.items(), key=lambda item: (-item[1], item[0]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "word", "count", "doc_count"])
        for rank, (word, count) in enumerate(rows, start=1):
            writer.writerow([rank, word, count, doc_counts[word]])


def write_report(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "manifest_index",
                "sample_id",
                "problem_id",
                "subject_dir",
                "dataset_slug",
                "item_path",
                "local_path",
                "status",
                "text_length",
                "token_count",
                "error",
            ]
        )
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Count word frequencies from ready3 resolved question text."
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--local-root", default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--remote-prefix", default=DEFAULT_REMOTE_PREFIX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-length", type=int, default=3)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.min_length < 1:
        raise SystemExit("--min-length must be >= 1")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    word_freq_path = output_dir / "word_freq.csv"
    report_path = output_dir / "extraction_report.csv"
    summary_path = output_dir / "summary.json"

    entries = read_manifest(args.manifest)
    word_counts = Counter()
    doc_counts = Counter()
    report_rows = []
    status_counts = Counter()
    total_tokens = 0

    for index, entry in enumerate(entries):
        item_path = entry.get("item_path") or ""
        sample_id = entry.get("sample_id", "")
        problem_id = entry.get("problem_id", "")
        subject_dir = entry.get("subject_dir", "")
        dataset_slug = entry.get("dataset_slug", "")
        local_path = ""
        text_length = 0
        token_count = 0
        error = ""

        try:
            local_path_obj = remote_to_local_path(
                item_path, args.remote_prefix, args.local_root
            )
            local_path = str(local_path_obj)
        except ValueError as exc:
            status = "bad_path"
            error = str(exc)
            status_counts[status] += 1
            report_rows.append(
                [
                    index,
                    sample_id,
                    problem_id,
                    subject_dir,
                    dataset_slug,
                    item_path,
                    local_path,
                    status,
                    text_length,
                    token_count,
                    error,
                ]
            )
            continue

        if not local_path_obj.exists():
            status = "missing_file"
            error = "local file is missing"
        else:
            try:
                with open(local_path_obj, "r", encoding="utf-8") as f:
                    item = json.load(f)
                question_text = get_question_text(item)
                if question_text is None:
                    status = "no_text"
                    error = ".".join(QUESTION_FIELD) + " is missing or empty"
                else:
                    tokens = tokenize(question_text, args.min_length)
                    word_counts.update(tokens)
                    doc_counts.update(set(tokens))
                    text_length = len(question_text)
                    token_count = len(tokens)
                    total_tokens += token_count
                    status = "success"
            except json.JSONDecodeError as exc:
                status = "json_error"
                error = str(exc)
            except OSError as exc:
                status = "read_error"
                error = str(exc)

        status_counts[status] += 1
        report_rows.append(
            [
                index,
                sample_id,
                problem_id,
                subject_dir,
                dataset_slug,
                item_path,
                local_path,
                status,
                text_length,
                token_count,
                error,
            ]
        )

    write_word_freq(word_freq_path, word_counts, doc_counts)
    write_report(report_path, report_rows)

    summary = {
        "manifest": args.manifest,
        "local_root": args.local_root,
        "remote_prefix": args.remote_prefix,
        "question_field": ".".join(QUESTION_FIELD),
        "min_length": args.min_length,
        "manifest_rows": len(entries),
        "status_counts": dict(status_counts),
        "total_tokens": total_tokens,
        "unique_words": len(word_counts),
        "word_freq_csv": str(word_freq_path),
        "extraction_report_csv": str(report_path),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"manifest rows: {len(entries)}")
    print(f"status counts: {dict(status_counts)}")
    print(f"total tokens: {total_tokens}")
    print(f"unique words: {len(word_counts)}")
    print(f"word frequency: {word_freq_path}")
    print(f"extraction report: {report_path}")
    print(f"summary: {summary_path}")

    if status_counts.get("success", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
