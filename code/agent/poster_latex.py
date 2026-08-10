import json
import logging
import os
import re
import shutil
import subprocess

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .poster_layout import _split_panels, _update_dynamic_canvas


logger = logging.getLogger(__name__)


def _latex_escape(text):
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in str(text))


def _tex_path(filename):
    return os.path.abspath(filename).replace("\\", "/")


def _run_xelatex(tex_file, output_dir, passes=1):
    executable = shutil.which("xelatex")
    if not executable:
        raise RuntimeError("xelatex was not found in PATH")
    tex_file = os.path.abspath(tex_file)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    for _ in range(passes):
        result = subprocess.run(
            [
                executable,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-no-shell-escape",
                f"-output-directory={output_dir}",
                os.path.basename(tex_file),
            ],
            cwd=os.path.dirname(tex_file),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:])
    return result.stdout


def _pdf_to_png(pdf_file, png_prefix, dpi=180):
    executable = shutil.which("pdftocairo")
    if not executable:
        raise RuntimeError("pdftocairo was not found in PATH")
    result = subprocess.run(
        [executable, "-png", "-singlefile", "-r", str(dpi), pdf_file, png_prefix],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return png_prefix + ".png"


def _prepare_assets(layout, output_dir, latex_dir):
    paper_id = layout["paper_id"]
    os.makedirs(latex_dir, exist_ok=True)

    for panel in layout["panels"]:
        for asset in panel["assets"]:
            source_path = os.path.abspath(asset.get("source_path", ""))
            fallback_path = os.path.abspath(asset.get("fallback_path", ""))
            if asset["type"] in ("equation", "table"):
                if os.path.isfile(fallback_path):
                    asset.update(render_mode="png", path=fallback_path)
                    continue
                raise FileNotFoundError(
                    f"Missing {asset['type']} image: {paper_id} | {asset['id']} | {fallback_path}"
                )

            if asset["type"] == "figure":
                if os.path.isfile(source_path):
                    with open(source_path, "rb") as file:
                        valid_pdf = file.read(5) == b"%PDF-"
                    if valid_pdf:
                        asset.update(render_mode="pdf", path=source_path)
                        continue
                if os.path.isfile(fallback_path):
                    logger.warning(
                        "Figure source PDF unavailable; using raster image: %s | %s | %s",
                        paper_id,
                        asset["id"],
                        fallback_path,
                    )
                    asset.update(render_mode="png", path=fallback_path)
                    continue
                raise FileNotFoundError(
                    f"Missing figure image: {paper_id} | {asset['id']} | "
                    f"source={source_path} | fallback={fallback_path}"
                )

            raise FileNotFoundError(f"Missing poster asset: {paper_id} | {asset['id']}")


def _write_panel_files(layout, latex_dir, environment, config):
    panel_dir = os.path.join(latex_dir, "panels")
    os.makedirs(panel_dir, exist_ok=True)
    template = environment.get_template("panel.tex.j2")
    font_size = layout["fonts"]["body_font_size"]
    line_spacing = layout["fonts"]["body_line_spacing"]
    line_height = round(font_size * line_spacing, 2)
    for panel in layout["panels"]:
        prepared = {asset["id"]: asset for asset in panel["assets"]}
        asset_rows = []
        for row in panel.get("asset_rows", []):
            assets = []
            for item in row["assets"]:
                asset = prepared[item["id"]]
                if asset.get("path") and os.path.exists(asset["path"]):
                    assets.append({**asset, "path": _tex_path(asset["path"])})
            if assets:
                asset_rows.append({**row, "assets": assets})
        source = template.render(
            topic=_latex_escape(panel["topic"]),
            text=_latex_escape(panel["text"]),
            asset_rows=asset_rows,
            font_size=font_size,
            line_height=line_height,
        )
        with open(os.path.join(panel_dir, panel["panel_id"] + ".tex"), "w", encoding="utf-8") as file:
            file.write(source.strip() + "\n")


def _measure_panels(layout, latex_dir, panel_gap=0):
    lines = [
        r"\documentclass{article}",
        r"\input{preamble.tex}",
        r"\pagestyle{empty}",
        r"\newsavebox{\pnpmeasurebox}",
        r"\begin{document}",
    ]
    for panel in layout["panels"]:
        panel_id = panel["panel_id"]
        lines.extend(
            [
                r"\sbox{\pnpmeasurebox}{\begin{minipage}{"
                + str(layout["canvas"]["column_width"])
                + r"in}\input{panels/"
                + panel_id
                + r".tex}\end{minipage}}",
                r"\typeout{PNPHEIGHT-"
                + panel_id
                + r"=\the\dimexpr\ht\pnpmeasurebox+\dp\pnpmeasurebox\relax}",
            ]
        )
    lines.append(r"\end{document}")
    tex_file = os.path.join(latex_dir, "measure_panels.tex")
    with open(tex_file, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    output = _run_xelatex(tex_file, os.path.join(latex_dir, "measurements"))
    measurements = {
        panel_id: round(float(points) / 72.27, 3)
        for panel_id, points in re.findall(r"PNPHEIGHT-(panel_\d+)=(\d+(?:\.\d+)?)pt", output)
    }
    for panel in layout["panels"]:
        if panel["panel_id"] in measurements:
            panel["measured_height"] = measurements[panel["panel_id"]]
    layout["columns"], layout["split_points"] = _split_panels(
        layout["panels"], layout["canvas"]["body_height"], panel_gap
    )
    measurement_file = os.path.join(latex_dir, "measurements", "panel_heights.json")
    with open(measurement_file, "w", encoding="utf-8") as file:
        json.dump(measurements, file, ensure_ascii=False, indent=2)
    return measurements


def _columns_fit(layout, config):
    limit = layout["canvas"]["body_height"] * (1 + config["layout"]["overflow_tolerance"])
    return max(column["estimated_height"] for column in layout["columns"].values()) <= limit


def _set_column_gaps(layout, config):
    panels = {panel["panel_id"]: panel for panel in layout["panels"]}
    target = layout["canvas"]["body_height"] * config["layout"]["target_utilization"]
    minimum = config["panels"]["min_gap"]
    maximum = config["panels"]["max_gap"]
    for column in layout["columns"].values():
        panel_ids = column["panel_ids"]
        content_height = sum(panels[panel_id]["measured_height"] for panel_id in panel_ids)
        if len(panel_ids) > 1:
            gap = min(max((target - content_height) / (len(panel_ids) - 1), minimum), maximum)
        else:
            gap = 0
        column["panel_gap"] = round(gap, 3)
        column["estimated_height"] = round(content_height + gap * max(0, len(panel_ids) - 1), 3)
        column["utilization"] = round(column["estimated_height"] / layout["canvas"]["body_height"], 4)


def _fit_panel_typography(layout, latex_dir, environment, config):
    text_config = config["text"]
    minimum_spacing = text_config["min_line_spacing"]
    minimum_gap = config["panels"]["min_gap"]

    low = text_config["min_font_size"]
    high = text_config["max_font_size"]
    selected_font = low
    while low <= high:
        font_size = (low + high) // 2
        layout["fonts"]["body_font_size"] = font_size
        layout["fonts"]["body_line_spacing"] = minimum_spacing
        _write_panel_files(layout, latex_dir, environment, config)
        _measure_panels(layout, latex_dir, minimum_gap)
        if _columns_fit(layout, config):
            selected_font = font_size
            low = font_size + 1
        else:
            high = font_size - 1

    spacing_values = []
    spacing = text_config["min_line_spacing"]
    while spacing <= text_config["max_line_spacing"] + 0.001:
        spacing_values.append(round(spacing, 2))
        spacing = round(spacing + 0.02, 2)

    low = 0
    high = len(spacing_values) - 1
    selected_spacing = spacing_values[0]
    while low <= high:
        index = (low + high) // 2
        layout["fonts"]["body_font_size"] = selected_font
        layout["fonts"]["body_line_spacing"] = spacing_values[index]
        _write_panel_files(layout, latex_dir, environment, config)
        _measure_panels(layout, latex_dir, minimum_gap)
        if _columns_fit(layout, config):
            selected_spacing = spacing_values[index]
            low = index + 1
        else:
            high = index - 1

    layout["fonts"]["body_font_size"] = selected_font
    layout["fonts"]["body_line_spacing"] = selected_spacing
    _write_panel_files(layout, latex_dir, environment, config)
    _measure_panels(layout, latex_dir, minimum_gap)
    _update_dynamic_canvas(layout, config)
    _set_column_gaps(layout, config)
    logger.info(
        "     Poster typography fitted: %s | font=%d spacing=%.2f | left=%.1f%% right=%.1f%%",
        layout["paper_id"],
        selected_font,
        selected_spacing,
        layout["columns"]["left"]["utilization"] * 100,
        layout["columns"]["right"]["utilization"] * 100,
    )


def _write_columns(layout, latex_dir):
    column_dir = os.path.join(latex_dir, "columns")
    os.makedirs(column_dir, exist_ok=True)
    for column_name in ("left", "right"):
        panel_ids = layout["columns"][column_name]["panel_ids"]
        gap = layout["columns"][column_name].get("panel_gap", 0)
        lines = []
        for index, panel_id in enumerate(panel_ids):
            lines.append(f"\\input{{panels/{panel_id}.tex}}")
            if index < len(panel_ids) - 1 and gap > 0:
                lines.append(f"\\vspace{{{gap}in}}")
        with open(os.path.join(column_dir, column_name + ".tex"), "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


def _validate_final_columns(layout):
    overflow = {}
    body_height = layout.get("canvas", {}).get("body_height", 0)
    for column_name, column in layout["columns"].items():
        utilization = column.get("utilization")
        if utilization is None and body_height:
            utilization = column.get("estimated_height", 0) / body_height
        if utilization is not None and utilization > 1.01:
            overflow[column_name] = utilization
    if overflow:
        details = ", ".join(
            f"{name}={value * 100:.1f}%" for name, value in overflow.items()
        )
        raise RuntimeError(
            f"Dynamic poster height is stale in {layout['paper_id']}: {details}. "
            "Render poster columns again before final rendering."
        )


def render_poster_columns(args):
    template_dir = os.path.join("code", "template", "latex")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
    )
    with open(os.path.join("code", "config", "poster_layout.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    preamble = environment.get_template("preamble.tex").render(
        panel_title_font_size=config["panels"]["title_font_size"],
        panel_title_line_height=config["panels"]["title_line_height"],
        panel_title_top_padding=config["panels"]["title_top_padding"],
        panel_title_bottom_padding=config["panels"]["title_bottom_padding"],
    )

    results = {}
    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        poster_dir = os.path.join(temp_root, paper_id, "poster")
        layout_file = os.path.join(poster_dir, "poster_layout.json")
        if not os.path.isfile(layout_file):
            continue
        with open(layout_file, "r", encoding="utf-8") as file:
            layout = json.load(file)
        latex_dir = os.path.join(poster_dir, "latex")
        preview_dir = os.path.join(poster_dir, "previews")
        os.makedirs(latex_dir, exist_ok=True)
        os.makedirs(preview_dir, exist_ok=True)
        with open(os.path.join(latex_dir, "preamble.tex"), "w", encoding="utf-8") as file:
            file.write(preamble)

        _prepare_assets(layout, args.output_dir, latex_dir)
        _fit_panel_typography(layout, latex_dir, environment, config)
        _write_columns(layout, latex_dir)

        preview_template = environment.get_template("column_preview.tex.j2")
        previews = {}
        for column_name in ("left", "right"):
            preview_height = max(
                layout["canvas"]["body_height"],
                layout["columns"][column_name]["estimated_height"],
            )
            source = preview_template.render(
                page_width=layout["canvas"]["column_width"] + 0.4,
                page_height=preview_height + 0.4,
                margin=0.2,
                column_name=column_name,
            )
            tex_file = os.path.join(latex_dir, f"preview_{column_name}.tex")
            with open(tex_file, "w", encoding="utf-8") as file:
                file.write(source)
            _run_xelatex(tex_file, preview_dir)
            pdf_file = os.path.join(preview_dir, f"preview_{column_name}.pdf")
            previews[column_name] = _pdf_to_png(
                pdf_file, os.path.join(preview_dir, column_name)
            )

        with open(layout_file, "w", encoding="utf-8") as file:
            json.dump(layout, file, ensure_ascii=False, indent=2)
        results[paper_id] = previews
        logger.info("     ✅ Poster columns rendered: %s", paper_id)
    return results


def render_final_poster(args):
    template_dir = os.path.join("code", "template", "latex")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
    )
    template = environment.get_template("poster.tex.j2")
    results = {}
    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        poster_dir = os.path.join(temp_root, paper_id, "poster")
        layout_file = os.path.join(poster_dir, "poster_layout.json")
        if not os.path.isfile(layout_file):
            continue
        with open(layout_file, "r", encoding="utf-8") as file:
            layout = json.load(file)
        _validate_final_columns(layout)
        latex_dir = os.path.join(poster_dir, "latex")
        final_dir = os.path.join(args.output_dir, "poster", paper_id)
        os.makedirs(final_dir, exist_ok=True)
        header = layout["header"]
        source = template.render(
            **layout["canvas"],
            **layout["fonts"],
            title=_latex_escape(header["title"]),
            authors=_latex_escape(", ".join(header["authors"])),
            affiliations=_latex_escape("  |  ".join(header["affiliations"])),
            abstract=_latex_escape(layout.get("abstract", "")),
        )
        tex_file = os.path.join(latex_dir, "main.tex")
        with open(tex_file, "w", encoding="utf-8") as file:
            file.write(source)
        _run_xelatex(tex_file, final_dir, passes=2)
        pdf_file = os.path.join(final_dir, "main.pdf")
        final_pdf = os.path.join(final_dir, "poster.pdf")
        shutil.copyfile(pdf_file, final_pdf)
        png_file = _pdf_to_png(final_pdf, os.path.join(final_dir, "poster"), dpi=180)
        shutil.copyfile(tex_file, os.path.join(final_dir, "poster.tex"))
        shutil.copyfile(os.path.join(latex_dir, "preamble.tex"), os.path.join(final_dir, "preamble.tex"))
        shutil.copytree(os.path.join(latex_dir, "panels"), os.path.join(final_dir, "panels"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(latex_dir, "columns"), os.path.join(final_dir, "columns"), dirs_exist_ok=True)
        results[paper_id] = {"tex": os.path.join(final_dir, "poster.tex"), "pdf": final_pdf, "png": png_file}
        logger.info("     ✅ Final poster rendered: %s", paper_id)
    return results
