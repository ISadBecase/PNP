import json
import logging
import math
import os

import yaml
from PIL import Image


logger = logging.getLogger(__name__)


def _load_json(filename):
    with open(filename, "r", encoding="utf-8") as file:
        return json.load(file)


def _image_ratio(filename):
    if not filename or not os.path.exists(filename):
        return 1.6
    with Image.open(filename) as image:
        return image.width / image.height if image.height else 1.6


def _image_dimensions(filename):
    if not filename or not os.path.exists(filename):
        return 0, 0
    with Image.open(filename) as image:
        return image.width, image.height


def _asset_paths(asset_type, asset):
    if asset_type == "figure":
        return asset.get("pdf_path", ""), asset.get("png_path", "")
    return asset.get("tex_file", ""), asset.get("png_file", "")


def _select_panel_assets(panel):
    importance = panel.get("asset_importance", {})
    visual_assets = []
    order = 0
    for asset_type, field in (("figure", "figure_ids"), ("table", "table_ids")):
        for asset_id in panel.get(field, []):
            visual_assets.append(
                (importance.get(asset_id, 0), order, asset_type, asset_id)
            )
            order += 1

    selected = sorted(visual_assets, key=lambda item: (-item[0], item[1]))[:2]
    assets = [(asset_type, asset_id) for _, _, asset_type, asset_id in selected]
    assets.extend(
        ("equation", asset_id) for asset_id in panel.get("equation_ids", [])
    )
    return assets


def _estimate_text_height(text, column_width, config):
    text_config = config["text"]
    weighted_characters = sum(1.8 if ord(character) > 127 else 1 for character in text)
    width_scale = column_width / 17.0
    characters_per_line = max(12, text_config["estimated_chars_per_line"] * width_scale)
    explicit_lines = text.count("\n")
    lines = max(1, math.ceil(weighted_characters / characters_per_line) + explicit_lines)
    line_height = text_config["font_size"] / 72 * text_config["line_spacing"]
    return round(lines * line_height + 0.12, 3)


def _abstract_text_height(text, font_size, line_spacing, config):
    abstract = config["abstract"]
    weighted = sum(1.8 if ord(character) > 127 else 1 for character in text)
    characters_per_line = (
        abstract["estimated_chars_per_line"]
        * abstract["reference_font_size"]
        / font_size
    )
    lines = max(1, math.ceil(weighted / characters_per_line))
    height = lines * font_size / 72 * line_spacing + abstract["vertical_padding"]
    return height


def _estimate_abstract_height(text, config):
    abstract = config["abstract"]
    height = _abstract_text_height(
        text,
        abstract["max_font_size"],
        abstract["min_line_spacing"],
        config,
    )
    return round(min(max(height, abstract["min_height"]), abstract["max_height"]), 3)


def _select_abstract_typography(text, height, config):
    abstract = config["abstract"]
    selected_font = abstract["min_font_size"]
    for font_size in range(abstract["max_font_size"], abstract["min_font_size"] - 1, -1):
        if _abstract_text_height(text, font_size, abstract["min_line_spacing"], config) <= height:
            selected_font = font_size
            break

    selected_spacing = abstract["min_line_spacing"]
    spacing = abstract["max_line_spacing"]
    while spacing >= abstract["min_line_spacing"]:
        if _abstract_text_height(text, selected_font, spacing, config) <= height:
            selected_spacing = spacing
            break
        spacing = round(spacing - 0.01, 2)
    return selected_font, round(selected_spacing, 2)


def _create_asset_metric(asset_type, asset, importance, column_width, body_height, config):
    source_path, fallback_path = _asset_paths(asset_type, asset)
    width_px = asset.get("width_px") or 0
    height_px = asset.get("height_px") or 0
    if not width_px or not height_px:
        width_px, height_px = _image_dimensions(fallback_path)
    ratio = asset.get("aspect_ratio") or (width_px / height_px if height_px else _image_ratio(fallback_path))
    natural_height = column_width / ratio
    limits = config["assets"][asset_type]
    minimum = body_height * limits["min_height_ratio"]
    maximum = body_height * limits["max_height_ratio"]
    scale = config["importance_scale"][importance]
    display_height = min(max(natural_height * scale, minimum), maximum)
    return {
        "id": asset["id"],
        "type": asset_type,
        "path": os.path.normpath(fallback_path) if fallback_path else "",
        "source_path": os.path.normpath(source_path) if source_path else "",
        "fallback_path": os.path.normpath(fallback_path) if fallback_path else "",
        "is_primary_table": asset_type == "table" and importance == 5,
        "caption": asset.get("caption", ""),
        "importance": importance,
        "width_px": width_px,
        "height_px": height_px,
        "aspect_ratio": round(ratio, 4),
        "natural_height": round(natural_height, 3),
        "min_height": round(minimum, 3),
        "max_height": round(maximum, 3),
        "display_height": round(display_height, 3),
    }


def _arrange_asset_rows(assets, column_width, body_height, config):
    rows = []
    visual_assets = [asset for asset in assets if asset["type"] in ("figure", "table")]
    equations = [asset for asset in assets if asset["type"] == "equation"]
    figure_config = config["assets"]["figure"]
    table_config = config["assets"]["table"]
    consumed = set()

    for index, visual in enumerate(visual_assets):
        if visual["id"] in consumed:
            continue
        ratio = visual["aspect_ratio"]
        if ratio > figure_config["wide_ratio_threshold"]:
            width = column_width * figure_config["wide_width_ratio"]
            visual["display_width"] = round(width, 3)
            visual["display_height"] = round(width / ratio, 3)
            rows.append({"layout": "single_wide", "assets": [visual], "display_height": visual["display_height"]})
            consumed.add(visual["id"])
            continue

        candidates = []
        for candidate_index in range(index + 1, len(visual_assets)):
            candidate = visual_assets[candidate_index]
            if candidate["id"] in consumed or candidate["aspect_ratio"] > figure_config["wide_ratio_threshold"]:
                continue
            error = abs(ratio + candidate["aspect_ratio"] - figure_config["pair_target_ratio"])
            if error <= figure_config["pair_ratio_tolerance"]:
                available_width = column_width * figure_config["pair_width_ratio"] - figure_config["pair_gap"]
                height = available_width / (ratio + candidate["aspect_ratio"])
                widths = (height * ratio, height * candidate["aspect_ratio"])
                pair = (visual, candidate)
                if all(
                    item["type"] != "table"
                    or width >= column_width * table_config["pair_min_width_ratio"]
                    for item, width in zip(pair, widths)
                ):
                    candidates.append((error, candidate_index, candidate))

        if candidates:
            _, _, partner = min(candidates, key=lambda item: (item[0], item[1]))
            gap = figure_config["pair_gap"]
            available_width = column_width * figure_config["pair_width_ratio"] - gap
            height = available_width / (ratio + partner["aspect_ratio"])
            for item in (visual, partner):
                item["display_height"] = round(height, 3)
                item["display_width"] = round(height * item["aspect_ratio"], 3)
                consumed.add(item["id"])
            rows.append({"layout": "equal_height_pair", "assets": [visual, partner], "display_height": round(height, 3), "gap": gap})
            continue

        width_ratio = (
            figure_config["centered_width_ratio"]
            if visual["importance"] >= figure_config["high_importance_threshold"]
            else figure_config["secondary_width_ratio"]
        )
        if visual["type"] == "table":
            width_ratio = max(width_ratio, table_config["min_width_ratio"])
        width = column_width * width_ratio
        visual["display_width"] = round(width, 3)
        visual["display_height"] = round(width / ratio, 3)
        rows.append({"layout": "centered", "assets": [visual], "display_height": visual["display_height"]})
        consumed.add(visual["id"])

    equation_config = config["assets"]["equation"]
    equation_scale = equation_config["target_font_size"] / equation_config["source_font_size"]
    for equation in equations:
        width = equation["width_px"] / equation_config["source_dpi"] * equation_scale
        width = min(width, column_width * equation_config["max_width_ratio"])
        height = width / equation["aspect_ratio"]
        maximum_height = body_height * equation_config["max_height_ratio"]
        if height > maximum_height:
            height = maximum_height
            width = height * equation["aspect_ratio"]
        equation["display_width"] = round(width, 3)
        equation["display_height"] = round(height, 3)
        rows.append({"layout": "centered_equation", "assets": [equation], "display_height": equation["display_height"]})

    return rows


def _split_panels(panels, body_height, panel_gap=0):
    best = None
    panel_height = lambda panel: panel.get("measured_height") or panel["estimated_height"]

    for split in range(1, len(panels)):
        groups = [panels[:split], panels[split:]]
        heights = [
            sum(panel_height(panel) for panel in group) + panel_gap * max(0, len(group) - 1)
            for group in groups
        ]
        score = (
            round(max(heights) / body_height, 6),
            round(abs(heights[0] - heights[1]), 6),
        )
        if best is None or score < best[0]:
            best = score, split, groups, heights

    _, split, groups, heights = best
    return {
        "left": {
            "panel_ids": [panel["panel_id"] for panel in groups[0]],
            "estimated_height": round(heights[0], 3),
        },
        "right": {
            "panel_ids": [panel["panel_id"] for panel in groups[1]],
            "estimated_height": round(heights[1], 3),
        },
    }, [split]


def _update_dynamic_canvas(layout, config):
    poster = config["poster"]
    target = config["layout"]["target_utilization"]
    tallest = max(
        column.get("estimated_height", 0) for column in layout["columns"].values()
    )
    canvas = layout["canvas"]
    fixed_height = (
        canvas["header_height"]
        + canvas["abstract_height"]
        + 2 * canvas["section_gap"]
        + canvas["body_footer_gap"]
        + canvas["footer_height"]
    )
    body_height = max(tallest / target, poster["min_height"] - fixed_height)
    poster_height = (
        fixed_height + body_height
    )
    canvas["body_height"] = round(body_height, 3)
    canvas["height"] = round(max(poster["min_height"], poster_height), 3)
    for column in layout["columns"].values():
        column["utilization"] = round(
            column.get("estimated_height", 0) / canvas["body_height"], 4
        )
    return layout


def _create_layout(paper_id, paper_dir, evidence, config):
    panel_config = config["panels"]
    title_height = (
        panel_config["title_line_height"] / 72
        + panel_config["title_top_padding"]
        + panel_config["title_bottom_padding"]
        + 0.1
    )
    panels = evidence.get("panels", [])
    if not panel_config["min_count"] <= len(panels) <= panel_config["max_count"]:
        raise ValueError(f"Poster panels must be between 5 and 8 in {paper_id}")

    poster = config["poster"]
    header_height = poster["header_height"]
    abstract_height = _estimate_abstract_height(evidence.get("abstract", ""), config)
    abstract_font_size, abstract_line_spacing = _select_abstract_typography(
        evidence.get("abstract", ""), abstract_height, config
    )
    footer_height = poster["footer_height"]
    body_height = poster["reference_body_height"]
    poster_height = max(
        poster["min_height"],
        header_height
        + abstract_height
        + 2 * poster["section_gap"]
        + body_height
        + poster["body_footer_gap"]
        + footer_height,
    )
    column_width = (
        poster["width"] - 2 * poster["margin"] - poster["column_gap"]
    ) / 2

    asset_sources = {}
    for asset_type, filename, key in (
        ("figure", "figures.json", "figures"),
        ("table", "tables.json", "tables"),
        ("equation", "equations.json", "equations"),
    ):
        source = _load_json(os.path.join(paper_dir, filename))
        asset_sources[asset_type] = {asset["id"]: asset for asset in source[key]}

    layout_panels = []
    for order, panel in enumerate(panels, 1):
        expected_id = f"panel_{order:02d}"
        if panel.get("panel_id") != expected_id:
            raise ValueError(f"Panel IDs must be sequential in {paper_id}")

        importance = panel.get("importance")
        if not isinstance(importance, int) or not 1 <= importance <= 5:
            raise ValueError(f"Invalid panel importance in {paper_id}: {expected_id}")

        assets = []
        asset_importance = panel.get("asset_importance", {})
        for asset_type, field in (
            ("figure", "figure_ids"),
            ("table", "table_ids"),
            ("equation", "equation_ids"),
        ):
            for asset_id in panel.get(field, []):
                if asset_id not in asset_sources[asset_type]:
                    raise ValueError(f"Unknown asset ID in {paper_id}: {asset_id}")
                asset_score = asset_importance.get(asset_id)
                if not isinstance(asset_score, int) or not 1 <= asset_score <= 5:
                    raise ValueError(f"Invalid asset importance in {paper_id}: {asset_id}")

        for asset_type, asset_id in _select_panel_assets(panel):
            assets.append(
                _create_asset_metric(
                    asset_type,
                    asset_sources[asset_type][asset_id],
                    asset_importance[asset_id],
                    column_width,
                    body_height,
                    config,
                )
            )

        text_height = _estimate_text_height(panel.get("text", ""), column_width, config)
        asset_rows = _arrange_asset_rows(assets, column_width, body_height, config)
        asset_height = sum(row["display_height"] + panel_config["gap"] for row in asset_rows)
        estimated_height = (
            title_height
            + text_height
            + asset_height
            + 2 * panel_config["padding"]
            + panel_config["gap"]
        )
        layout_panels.append(
            {
                "panel_id": expected_id,
                "order": order,
                "topic": panel.get("topic", ""),
                "text": panel.get("text", ""),
                "importance": importance,
                "title_height": round(title_height, 3),
                "text_height": round(text_height, 3),
                "asset_height": round(asset_height, 3),
                "estimated_height": round(estimated_height, 3),
                "measured_height": None,
                "assets": assets,
                "asset_rows": asset_rows,
            }
        )

    columns, split_points = _split_panels(
        layout_panels, body_height, panel_config["min_gap"]
    )
    flattened = columns["left"]["panel_ids"] + columns["right"]["panel_ids"]
    if flattened != [panel["panel_id"] for panel in layout_panels]:
        raise RuntimeError(f"Panel order changed during layout in {paper_id}")

    return {
        "paper_id": paper_id,
        "canvas": {
            "width": poster["width"],
            "height": round(poster_height, 3),
            "margin": poster["margin"],
            "column_gap": poster["column_gap"],
            "content_width": round(poster["width"] - 2 * poster["margin"], 3),
            "section_gap": poster["section_gap"],
            "body_footer_gap": poster["body_footer_gap"],
            "header_height": round(header_height, 3),
            "abstract_height": round(abstract_height, 3),
            "footer_height": round(footer_height, 3),
            "body_height": round(body_height, 3),
            "column_width": round(column_width, 3),
        },
        "fonts": {
            "title_font_size": config["header"]["title_font_size"],
            "title_line_height": config["header"]["title_line_height"],
            "author_font_size": config["header"]["author_font_size"],
            "author_line_height": config["header"]["author_line_height"],
            "affiliation_font_size": config["header"]["affiliation_font_size"],
            "affiliation_line_height": config["header"]["affiliation_line_height"],
            "abstract_title_font_size": config["abstract"]["title_font_size"],
            "abstract_title_line_height": config["abstract"]["title_line_height"],
            "abstract_font_size": abstract_font_size,
            "abstract_line_spacing": abstract_line_spacing,
            "panel_title_font_size": config["panels"]["title_font_size"],
            "panel_title_line_height": config["panels"]["title_line_height"],
            "body_font_size": config["text"]["font_size"],
            "body_line_spacing": config["text"]["line_spacing"],
            "equation_font_size": config["assets"]["equation"]["target_font_size"],
        },
        "header": {
            "title": evidence.get("title", ""),
            "authors": evidence.get("authors", []),
            "affiliations": evidence.get("affiliations", []),
        },
        "abstract": evidence.get("abstract", ""),
        "panels": layout_panels,
        "columns": columns,
        "split_points": split_points,
        "iteration": 0,
    }


def create_poster_layout(args):
    with open(os.path.join("code", "config", "poster_layout.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    results = {}
    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        paper_dir = os.path.join(temp_root, paper_id)
        evidence_file = os.path.join(paper_dir, "poster_evidence.json")
        if not os.path.isfile(evidence_file):
            continue
        evidence = _load_json(evidence_file)
        sections_file = os.path.join(paper_dir, "sections.json")
        if not os.path.isfile(sections_file):
            raise FileNotFoundError(f"Missing sections.json in {paper_id}")
        evidence["abstract"] = _load_json(sections_file).get("abstract", "")
        layout = _create_layout(paper_id, paper_dir, evidence, config)
        poster_dir = os.path.join(paper_dir, "poster")
        os.makedirs(poster_dir, exist_ok=True)
        output_file = os.path.join(poster_dir, "poster_layout.json")
        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(layout, file, ensure_ascii=False, indent=2)
        results[paper_id] = layout
        logger.info(
            "     ✅ Poster layout created: %s | panels=%d | splits=%s",
            paper_id,
            len(layout["panels"]),
            layout["split_points"],
        )
    return results
