import argparse
import html
import json
import math
import re
import sys
from pathlib import Path


DEFAULT_FIGURE = {
    "width": 14,
    "height": 14,
    "dpi": 300,
    "background_color": "white",
}

DEFAULT_STYLE = {
    "start_angle": 90,
    "inner_radius": 0.68,
    "inner_width": 0.28,
    "outer_radius": 1.0,
    "outer_width": 0.28,
    "edge_color": "white",
    "edge_width": 1.2,
    "font_family": "Arial, sans-serif",
}

DEFAULT_LABELS = {
    "title": {
        "enabled": True,
        "font_size": 76,
        "fill": "#222222",
        "y": 0.32,
    },
    "inner": {
        "enabled": True,
        "font_size": 54,
        "fill": "#222222",
        "radius": 0.52,
    },
    "outer_inside": {
        "enabled": True,
        "font_size": 40,
        "fill": "#222222",
        "radius": 0.86,
    },
    "outer_outside": {
        "enabled": True,
        "font_size": 34,
        "fill": "#222222",
        "radius": 1.16,
        "rotation": "radial",
        "keep_upright": True,
        "leader_line": False,
        "leader_line_color": "#999999",
        "leader_line_width": 1.0,
    },
}


def load_config(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def merge_dict(defaults, values):
    result = dict(defaults)
    result.update(values or {})
    return result


def get_label_options(config, name):
    return merge_dict(DEFAULT_LABELS[name], config.get("labels", {}).get(name, {}))


def hex_to_rgb(color):
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"unsupported color: {color}")
    return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def blend_with_white(color, amount):
    rgb = hex_to_rgb(color)
    blended = tuple(round(channel + (255 - channel) * amount) for channel in rgb)
    return rgb_to_hex(blended)


def blend_with_black(color, amount):
    rgb = hex_to_rgb(color)
    blended = tuple(round(channel * (1 - amount)) for channel in rgb)
    return rgb_to_hex(blended)


def child_colors(parent_color, children):
    if not children:
        return []
    if len(children) == 1:
        return [blend_with_white(parent_color, 0.18)]

    colors = []
    for index, child in enumerate(children):
        if "color" in child:
            colors.append(child["color"])
            continue
        amount = 0.12 + 0.48 * index / (len(children) - 1)
        colors.append(blend_with_white(parent_color, amount))
    return colors


def safe_id(value):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip())
    return value.strip("-") or "item"


def point_on_circle(cx, cy, radius, angle_deg):
    angle = math.radians(angle_deg)
    return cx + radius * math.cos(angle), cy - radius * math.sin(angle)


def annular_segment_path(cx, cy, outer_radius, inner_radius, start_deg, end_deg):
    span = abs(start_deg - end_deg)
    steps = max(2, int(math.ceil(span / 4)))
    outer_points = [
        point_on_circle(cx, cy, outer_radius, start_deg + (end_deg - start_deg) * i / steps)
        for i in range(steps + 1)
    ]
    inner_points = [
        point_on_circle(cx, cy, inner_radius, end_deg + (start_deg - end_deg) * i / steps)
        for i in range(steps + 1)
    ]
    points = outer_points + inner_points
    commands = [f"M {points[0][0]:.3f} {points[0][1]:.3f}"]
    commands.extend(f"L {x:.3f} {y:.3f}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def normalize_rotation(angle):
    angle = ((angle + 180) % 360) - 180
    if angle == -180:
        return 180
    return angle


def radial_text_rotation(angle_deg, keep_upright):
    rotation = normalize_rotation(-angle_deg)
    if keep_upright and (rotation > 90 or rotation < -90):
        rotation = normalize_rotation(rotation + 180)
    return rotation


def svg_text_elements(text, x, y, label_options, font_family, element_id, rotation=None, anchor="middle"):
    if not text:
        return []

    font_size = float(label_options["font_size"])
    fill = label_options.get("fill", "#222222")
    dx = float(label_options.get("dx", 0))
    dy = float(label_options.get("dy", 0))
    x += dx
    y += dy

    lines = str(text).split("\n")
    line_height = font_size * 1.15
    first_y = y - line_height * (len(lines) - 1) / 2
    transform = ""
    if rotation is not None:
        transform = f' transform="rotate({rotation:.3f} {x:.3f} {y:.3f})"'

    elements = []
    for index, line in enumerate(lines):
        line_y = first_y + line_height * index
        line_id = f"{element_id}-line-{index + 1}"
        elements.append(
            f'<text id="{html.escape(line_id)}" x="{x:.3f}" y="{line_y:.3f}" '
            f'text-anchor="{anchor}"{transform} font-family="{html.escape(font_family)}" '
            f'font-size="{font_size}" fill="{fill}">{html.escape(line)}</text>'
        )
    return elements


def svg_line(x1, y1, x2, y2, color, width):
    return (
        f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
        f'stroke="{color}" stroke-width="{width}" />'
    )


def label_entries(item):
    labels = item.get("labels")
    if isinstance(labels, list):
        return [label for label in labels if isinstance(label, dict)]

    label = item.get("label")
    if isinstance(label, dict):
        return [label]
    return []


def total_value(items):
    return sum(float(item["value"]) for item in items)


def collect_data(config):
    inner = []
    outer = []
    warnings = []

    for parent in config.get("data", []):
        parent_id = parent.get("id", parent["label"]["text"] if isinstance(parent.get("label"), dict) else parent.get("name", "parent"))
        parent_color = parent.get("color", "#cccccc")
        children = parent.get("children", [])
        inner.append(
            {
                "id": safe_id(parent_id),
                "value": float(parent["value"]),
                "color": parent_color,
                "parent_color": parent_color,
                "label": parent.get("label", {}),
                "labels": parent.get("labels"),
            }
        )

        children_total = total_value(children)
        parent_value = float(parent["value"])
        if children and abs(children_total - parent_value) > 1e-9:
            warnings.append(
                f"{parent_id}: parent value is {parent_value:g}, children total is {children_total:g}"
            )

        for child, child_color in zip(children, child_colors(parent_color, children)):
            child_id = child.get("id", child.get("name", child.get("label", {}).get("text", "child")))
            outer.append(
                {
                    "id": safe_id(child_id),
                    "value": float(child["value"]),
                    "color": child.get("color", child_color),
                    "parent_color": parent_color,
                    "label": child.get("label", {}),
                    "labels": child.get("labels"),
                }
            )

    return inner, outer, warnings


def draw_ring(items, cx, cy, max_radius, radius, width, start_angle, style, ring_name):
    total = total_value(items)
    current = start_angle
    slices = []
    slice_meta = []

    for item in items:
        value = float(item["value"])
        span = 0 if total == 0 else 360 * value / total
        next_angle = current - span
        outer_radius = max_radius * radius
        inner_radius = max_radius * (radius - width)
        path = annular_segment_path(cx, cy, outer_radius, inner_radius, current, next_angle)
        item_id = safe_id(item["id"])
        slices.append(
            f'<path id="slice-{ring_name}-{item_id}" d="{path}" fill="{item["color"]}" '
            f'stroke="{style["edge_color"]}" stroke-width="{style["edge_width"]}" />'
        )
        slice_meta.append(
            {
                "item": item,
                "middle_angle": (current + next_angle) / 2,
                "outer_radius": outer_radius,
                "inner_radius": inner_radius,
            }
        )
        current = next_angle

    return slices, slice_meta


def draw_labels(slice_meta, config, style, cx, cy, max_radius):
    font_family = style["font_family"]
    labels = []
    leaders = []

    for meta in slice_meta:
        item = meta["item"]
        item_id = safe_id(item["id"])
        for label_index, label in enumerate(label_entries(item), start=1):
            text = label.get("text", "")
            position = label.get("position", "none")
            if not text or position == "none":
                continue
            if position not in DEFAULT_LABELS:
                continue

            base_options = get_label_options(config, position)
            if not base_options.get("enabled", True):
                continue
            overrides = {
                key: value for key, value in label.items() if key not in {"text", "position"}
            }
            options = merge_dict(base_options, overrides)
            radius = max_radius * float(options["radius"])
            angle = meta["middle_angle"]
            x, y = point_on_circle(cx, cy, radius, angle)

            rotation = None
            if options.get("rotation") == "radial":
                rotation = radial_text_rotation(angle, bool(options.get("keep_upright", True)))

            if position == "outer_outside":
                if "fill" not in label:
                    options["fill"] = blend_with_black(item.get("parent_color", item["color"]), 0.42)
                if options.get("leader_line"):
                    line_start = point_on_circle(cx, cy, meta["outer_radius"], angle)
                    line_end = point_on_circle(cx, cy, radius * 0.96, angle)
                    leaders.append(
                        svg_line(
                            line_start[0],
                            line_start[1],
                            line_end[0],
                            line_end[1],
                            options.get("leader_line_color", "#999999"),
                            options.get("leader_line_width", 1.0),
                        )
                    )
            label_id = f"text-{position}-{item_id}-{label_index}"
            labels.extend(
                svg_text_elements(
                    text,
                    x,
                    y,
                    options,
                    font_family,
                    label_id,
                    rotation=rotation,
                )
            )

    return leaders, labels


def render_nested_donut(config, output_image):
    figure = merge_dict(DEFAULT_FIGURE, config.get("figure", {}))
    style = merge_dict(DEFAULT_STYLE, config.get("style", {}))
    inner, outer, warnings = collect_data(config)

    if not inner:
        raise ValueError("config data is empty")
    if not outer:
        raise ValueError("nested_donut requires child data")

    scale = float(figure["dpi"])
    width = float(figure["width"]) * scale
    height = float(figure["height"]) * scale
    cx = width / 2
    cy = height / 2
    max_radius = min(width, height) * 0.36

    outer_slices, outer_meta = draw_ring(
        outer,
        cx,
        cy,
        max_radius,
        float(style["outer_radius"]),
        float(style["outer_width"]),
        float(style["start_angle"]),
        style,
        "outer",
    )
    inner_slices, inner_meta = draw_ring(
        inner,
        cx,
        cy,
        max_radius,
        float(style["inner_radius"]),
        float(style["inner_width"]),
        float(style["start_angle"]),
        style,
        "inner",
    )

    leaders, labels = draw_labels(inner_meta + outer_meta, config, style, cx, cy, max_radius)

    title = []
    title_options = get_label_options(config, "title")
    if title_options.get("enabled", True) and config.get("title"):
        title_y = scale * float(title_options.get("y", 0.32))
        title = svg_text_elements(
            config["title"],
            cx,
            title_y,
            title_options,
            style["font_family"],
            "text-title",
        )

    svg = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{figure["width"]}in" '
            f'height="{figure["height"]}in" viewBox="0 0 {width:.0f} {height:.0f}">',
            f'<rect width="100%" height="100%" fill="{figure["background_color"]}" />',
            *title,
            '<g id="outer-ring">',
            *outer_slices,
            "</g>",
            '<g id="inner-ring">',
            *inner_slices,
            "</g>",
            '<g id="leader-lines">',
            *leaders,
            "</g>",
            *labels,
            "</svg>",
        ]
    )

    Path(output_image).parent.mkdir(parents=True, exist_ok=True)
    with open(output_image, "w", encoding="utf-8") as f:
        f.write(svg)

    for warning in warnings:
        print(f"warning: {warning}")
    print(f"output image: {output_image}")
    print("chart type: nested_donut")
    print(f"inner slices: {len(inner)}")
    print(f"outer slices: {len(outer)}")


def parse_args():
    parser = argparse.ArgumentParser(description="Create a configurable SVG pie chart.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-image")
    parser.add_argument("--dpi", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)
    chart_type = config.get("chart_type")
    output_image = args.output_image or config.get("output_image")
    if not output_image:
        raise SystemExit("--output-image is required when config has no output_image")
    if Path(output_image).suffix.lower() != ".svg":
        raise SystemExit("this renderer currently supports SVG output only")
    if args.dpi is not None:
        config.setdefault("figure", {})["dpi"] = args.dpi

    if chart_type == "nested_donut":
        render_nested_donut(config, output_image)
    else:
        raise SystemExit(f"unsupported chart_type: {chart_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
