import argparse
import csv
import sys
from pathlib import Path


DEFAULT_OUTPUT_IMAGE = "data/output/word_cloud/word_cloud.png"


def read_frequencies(path, weight_column, max_words):
    frequencies = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("input csv has no header")
        missing = {"word", weight_column} - set(reader.fieldnames)
        if missing:
            raise ValueError("input csv missing columns: " + ", ".join(sorted(missing)))

        rows = []
        for row in reader:
            word = row["word"]
            if not word:
                continue
            weight = int(row[weight_column])
            if weight <= 0:
                continue
            rows.append((word, weight))

    rows.sort(key=lambda item: (-item[1], item[0]))
    if max_words > 0:
        rows = rows[:max_words]
    for word, weight in rows:
        frequencies[word] = weight
    return frequencies


def parse_args():
    parser = argparse.ArgumentParser(description="Create a word cloud from word_freq.csv.")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-image", default=DEFAULT_OUTPUT_IMAGE)
    parser.add_argument("--weight-column", default="count")
    parser.add_argument("--max-words", type=int, default=180)
    parser.add_argument("--width", type=int, default=1800)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--background-color", default="white")
    parser.add_argument("--colormap", default="viridis")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--prefer-horizontal", type=float, default=0.9)
    parser.add_argument("--font-path")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.max_words < 0:
        raise SystemExit("--max-words must be >= 0")
    if args.width <= 0:
        raise SystemExit("--width must be > 0")
    if args.height <= 0:
        raise SystemExit("--height must be > 0")
    if not 0 <= args.prefer_horizontal <= 1:
        raise SystemExit("--prefer-horizontal must be between 0 and 1")

    try:
        from wordcloud import WordCloud
    except ImportError as exc:
        raise SystemExit(
            "missing dependency: wordcloud. Install it with "
            "`conda install -n dag_env -c conda-forge wordcloud` "
            "or `python -m pip install wordcloud`."
        ) from exc

    frequencies = read_frequencies(args.input_csv, args.weight_column, args.max_words)
    if not frequencies:
        raise SystemExit("no words found in input csv")

    output_image = Path(args.output_image)
    output_image.parent.mkdir(parents=True, exist_ok=True)

    word_cloud = WordCloud(
        width=args.width,
        height=args.height,
        background_color=args.background_color,
        colormap=args.colormap,
        max_words=len(frequencies),
        prefer_horizontal=args.prefer_horizontal,
        random_state=args.random_state,
        collocations=False,
        font_path=args.font_path,
    )
    word_cloud.generate_from_frequencies(frequencies)
    word_cloud.to_file(str(output_image))

    print(f"input csv: {args.input_csv}")
    print(f"output image: {output_image}")
    print(f"weight column: {args.weight_column}")
    print(f"words used: {len(frequencies)}")
    print(f"image size: {args.width}x{args.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
