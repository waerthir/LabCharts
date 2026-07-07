import argparse
import csv
import sys
from pathlib import Path


REQUIRED_COLUMNS = {"word", "count", "doc_count"}


def read_remove_words_file(path):
    words = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            word = line.rstrip("\r\n")
            if not word or word.startswith("#"):
                continue
            words.append(word)
    return words


def collect_remove_words(args):
    words = []
    if args.remove_words:
        words.extend([word for word in args.remove_words.split(",") if word])
    if args.remove_words_file:
        words.extend(read_remove_words_file(args.remove_words_file))
    return set(words)


def read_word_freq(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("input csv has no header")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError("input csv missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    return rows


def sort_rows(rows):
    return sorted(rows, key=lambda row: (-int(row["count"]), row["word"]))


def write_word_freq(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "word", "count", "doc_count"])
        for rank, row in enumerate(sort_rows(rows), start=1):
            writer.writerow([rank, row["word"], row["count"], row["doc_count"]])


def parse_args():
    parser = argparse.ArgumentParser(description="Filter selected words from word_freq.csv.")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--remove-words")
    parser.add_argument("--remove-words-file")
    return parser.parse_args()


def main():
    args = parse_args()
    remove_words = collect_remove_words(args)
    rows = read_word_freq(args.input_csv)
    kept_rows = [row for row in rows if row["word"] not in remove_words]
    removed_count = len(rows) - len(kept_rows)

    write_word_freq(args.output_csv, kept_rows)

    print(f"input csv: {args.input_csv}")
    print(f"output csv: {args.output_csv}")
    print(f"input rows: {len(rows)}")
    print(f"remove words: {len(remove_words)}")
    print(f"removed rows: {removed_count}")
    print(f"output rows: {len(kept_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
