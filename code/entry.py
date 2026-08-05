import argparse
import logging
import os
import shutil
import sys

from agent.paper_content import extract_papers
import agent.parser_arxiv as parser_arxiv
from agent.paper_classifier import classify_papers
from arxiv2agent import digest, write_digest
from utils.load_env import load_app_config

def set_log(args):
    logger = logging.getLogger()
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(os.path.join(args.output_dir, "run.log"))
    file_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()                              # 控制台handler
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-10s | %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    if args.ignore_ragcli:
        logging.getLogger("lightrag").setLevel(logging.WARNING)
        logging.getLogger("nano-vectordb").setLevel(logging.WARNING)

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# 初始化文件树和日志
def initialize(args):
    args.output_dir = os.path.abspath(args.output_dir)
    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    set_log(args)
    logging.info(" ✅ Finish file path initialization")

def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_ids", nargs="+", help="one or more arXiv IDs, e.g. 2305.13860 1706.03762")
    parser.add_argument("--output_dir", default="./output", help="Output Directory")

    parser.add_argument("--poster_density", type=str, default="dense", choices=["sparse", "medium", "dense"])
    parser.add_argument("--ignore_ragcli", type=bool, default=True)
    # For gpt-image-2 and gpt-image-2-2026-04-21, arbitrary resolutions are supported as WIDTHxHEIGHT strings.
    # Width and height must both be divisible by 16 and the requested aspect ratio must be between 1:3 and 3:1.
    # Resolutions above 2560x1440 are experimental, and the maximum supported resolution is 3840x2160
    parser.add_argument("--image_size", type=str, default="3840x2160")
    parser.add_argument("--image_quality", type=str, default="high", choices=["low", "medium", "high"])

    # Custom style must be specified when using the "custom" style
    parser.add_argument("--style", type=str, default="academic", choices=["academic", "custom","doraemon"])
    parser.add_argument("--custom_style", type=str, default=None)
    args = parser.parse_args(argv)
    return args


def run_arxiv2agent_stage(args):
    arxiv_output_dir = os.path.join(args.output_dir, "arxiv")
    failures = []
    for arxiv_id in args.arxiv_ids:
        try:
            paper = digest(arxiv_id=arxiv_id)
            from arxiv2agent._tex import get_default_cache_dir
            source_folder = str(get_default_cache_dir() / arxiv_id)
            output_path = write_digest(paper, output_dir=arxiv_output_dir, source_folder=source_folder, include_source=True)
            print(f"Wrote: {output_path}", file=sys.stderr)
        except Exception as exc:
            failures.append(arxiv_id)
            print(f"FAILED: {arxiv_id} — {exc}", file=sys.stderr)

    if len(args.arxiv_ids) > 1:
        logging.info(f"    ✅ Done: {len(args.arxiv_ids) - len(failures)}/{len(args.arxiv_ids)} papers digested.")
    if failures:
        logging.info(f"    ❌ Failed IDs: {' '.join(failures)}")
    if len(failures) == len(args.arxiv_ids):
        raise RuntimeError("All arXiv ID processing failed")

# "D:\Anaconda3\envs\Pytorch\python.exe" .\code\entry.py 2402.17228
# TODO:生成文件名可能会重叠，需要后续检查
def main():
    args = parse_args()
    app_config = load_app_config()
    initialize(args)


    run_arxiv2agent_stage(args)
    arxiv_root = os.path.join(args.output_dir, "arxiv")
    render_results = parser_arxiv.convert_root(arxiv_root)
    failed = sum(result[1] == "failed" for result in render_results)
    logging.info("LaTeX fragments: %d processed, %d failed", len(render_results), failed)

    figure_results = parser_arxiv.convert_figure_pdfs(arxiv_root)
    figure_failed = sum(result[1] == "failed" for result in figure_results)
    logging.info("Figure PDFs: %d processed, %d failed", len(figure_results), figure_failed)

    content_dirs = extract_papers(arxiv_root, args.output_dir)
    logging.info(f"Paper content extracted: {len(content_dirs)}")

    classify_papers(app_config, content_dirs)

    return 0


if __name__ == "__main__":
    sys.exit(main())
