import argparse
from concurrent.futures import ThreadPoolExecutor
import glob
import json
import os
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory


def _replace_suffix(path, suffix):
    return os.path.splitext(path)[0] + suffix

# 去除表格背景tex设置
def strip_table_backgrounds(source):
    commands = re.compile(
        r"\\(rowcolors\*?|rowcolor|cellcolor|colorbox|fcolorbox)(?![A-Za-z@])"
    )

    def read_group(position, opening, closing):
        while position < len(source) and source[position].isspace():
            position += 1
        if position >= len(source) or source[position] != opening:
            return None

        depth = 1
        start = position + 1
        position += 1
        while position < len(source):
            character = source[position]
            escaped = position > 0 and source[position - 1] == "\\"
            if not escaped and character == opening:
                depth += 1
            elif not escaped and character == closing:
                depth -= 1
                if depth == 0:
                    return source[start:position], position + 1
            position += 1
        return None

    output = []
    cursor = 0
    for match in commands.finditer(source):
        if match.start() < cursor:
            continue

        command = match.group(1)
        position = match.end()
        optional = read_group(position, "[", "]")
        if optional:
            position = optional[1]

        argument_count = {
            "rowcolor": 1,
            "cellcolor": 1,
            "rowcolors": 3,
            "rowcolors*": 3,
            "colorbox": 2,
            "fcolorbox": 3,
        }[command]
        arguments = []
        valid = True
        for _ in range(argument_count):
            group = read_group(position, "{", "}")
            if not group:
                valid = False
                break
            arguments.append(group[0])
            position = group[1]

        if not valid:
            continue

        if command in ("rowcolor", "cellcolor"):
            for _ in range(2):
                overhang = read_group(position, "[", "]")
                if not overhang or "&" in overhang[0] or "\\\\" in overhang[0]:
                    break
                position = overhang[1]

        output.append(source[cursor:match.start()])
        if command == "colorbox":
            output.append(arguments[1])
        elif command == "fcolorbox":
            output.append(arguments[2])
        cursor = position

    output.append(source[cursor:])
    return "".join(output)


def collect_tex_fragments(root):
    fragments = []
    for name in sorted(os.listdir(root)):
        paper = os.path.join(root, name)
        if os.path.isdir(paper):
            fragments.extend(sorted(glob.glob(os.path.join(paper, "equations", "*.tex"))))
            fragments.extend(sorted(glob.glob(os.path.join(paper, "tables", "*.tex"))))
    return fragments


def find_source_preamble(tex_path):
    source_dir = os.path.join(os.path.dirname(os.path.dirname(tex_path)), "source")
    if os.path.isdir(source_dir):
        for root, _, files in os.walk(source_dir):
            for name in files:
                if not name.lower().endswith(".tex"):
                    continue
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as source:
                    text = source.read()
                if "\\documentclass" in text and "\\begin{document}" in text:
                    return source_dir, text.split("\\begin{document}", 1)[0]
    return None, ""


def convert_fragment(tex_path, dpi=600, background="white", force=True):
    tex_path = os.fspath(tex_path)
    pdf_path = os.path.abspath(_replace_suffix(tex_path, ".pdf"))
    png_path = os.path.abspath(_replace_suffix(tex_path, ".png"))
    if os.path.exists(png_path) and not force:
        return tex_path, "skipped", ""

    try:
        with open(tex_path, "r", encoding="utf-8") as source_file:
            source = source_file.read().rstrip()
        if os.path.basename(os.path.dirname(tex_path)) == "equations":
            source = re.sub(r"\\bm\{(Step~\d+:)\}", r"\\text{\\bfseries \1}", source)
            json_path = _replace_suffix(tex_path, ".json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as json_file:
                    env = json.load(json_file).get("env", "")
            else:
                env = ""
            if env in ("align", "align*"):
                body = f"$\\begin{{aligned}}\n{source}\n\\end{{aligned}}$\n"
            else:
                body = f"$\\displaystyle {source}$\n"
        else:
            source = strip_table_backgrounds(source)
            body = f"{{\\centering\n{source}\n\\par}}\n"

        workdir, preamble = find_source_preamble(tex_path)
        if preamble:
            document = preamble + r"""
\usepackage[active,tightpage]{preview}
\begin{document}
\begin{preview}
""" + body + "\\end{preview}\n\\end{document}\n"
        else:
            document = r"""\documentclass[border=2pt]{standalone}
\usepackage{amsmath,amssymb,mathtools,bm}
\usepackage{array,booktabs,multirow,makecell,graphicx,rotating}
\usepackage[table]{xcolor}
\usepackage{xspace}
\begin{document}
""" + body + "\\end{document}\n"

        with TemporaryDirectory(prefix="arxiv_tex_") as temp_dir:
            tex_file = os.path.join(temp_dir, "fragment.tex")
            with open(tex_file, "w", encoding="utf-8") as output:
                output.write(document)

            result = subprocess.run(
                [
                    "xelatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    f"-output-directory={temp_dir}",
                    tex_file,
                ],
                cwd=workdir or temp_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                return tex_path, "failed", (result.stderr or result.stdout or "")[-1000:]

            shutil.copyfile(os.path.join(temp_dir, "fragment.pdf"), pdf_path)
            command = ["pdftocairo", "-png", "-singlefile"]
            if background == "transparent":
                command.append("-transp")
            result = subprocess.run(
                command
                + ["-r", str(dpi), pdf_path, os.path.splitext(png_path)[0]],
                cwd=os.path.dirname(tex_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                return tex_path, "failed", (result.stderr or result.stdout or "")[-1000:]
    except (OSError, UnicodeError) as error:
        return tex_path, "failed", str(error)

    return tex_path, "rendered", ""


def convert_root(args, dpi=600, workers=4, background="white", force=True):
    def render(tex_path):
        try:
            return convert_fragment(tex_path, dpi, background, force)
        except Exception as error:
            return tex_path, "failed", str(error)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(render, collect_tex_fragments(os.path.join(args.output_dir, "arxiv"))))


def convert_figure_pdfs(args, dpi=300, workers=4, force=True):
    arxiv_dir=os.path.join(args.output_dir, "arxiv")
    pdf_paths = sorted(glob.glob(os.path.join(os.fspath(arxiv_dir), "*", "figures", "*.pdf")))

    def render(pdf_path):
        png_path = os.path.abspath(_replace_suffix(pdf_path, ".png"))
        if os.path.exists(png_path) and not force:
            return pdf_path, "skipped", ""
        result = subprocess.run(
            [
                "pdftocairo",
                "-png",
                "-singlefile",
                "-cropbox",
                "-r",
                str(dpi),
                os.path.abspath(pdf_path),
                os.path.splitext(png_path)[0],
            ],
            cwd=os.path.dirname(pdf_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            return pdf_path, "failed", (result.stderr or result.stdout or "")[-1000:]
        return pdf_path, "rendered", ""

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(render, pdf_paths))


def main():
    parser = argparse.ArgumentParser(description="Render arXiv equations and tables as PDF and PNG.")
    parser.add_argument("root", nargs="?", default=os.path.join("output", "arxiv"))
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--background", choices=["transparent", "white"], default="white")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    results = convert_root(args.root, args.dpi, args.workers, args.background, args.force)
    failed = [result for result in results if result[1] == "failed"]
    print(
        f"Processed {len(results)} fragments: "
        f"rendered={sum(x[1] == 'rendered' for x in results)}, "
        f"skipped={sum(x[1] == 'skipped' for x in results)}, "
        f"failed={len(failed)}"
    )
    for tex_path, _, error in failed:
        print(f"FAILED {tex_path}: {error}")
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
