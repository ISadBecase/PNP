import argparse
import logging
import os
import shutil
import sys

from utils.load_env import load_app_config
from arxiv2agent import digest, write_digest

import agent.parser_arxiv as parser_arxiv
from agent.paper_classifier import classify_papers,extract_main_content
from agent.parser_vlm import analyze_equations
from agent.paper_elements import extract_contents

def set_log(args) -> logging.Logger:
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-10s | %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(
        os.path.join(args.output_dir, "run.log"),
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, console_handler):
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # 根 logger 不处理第三方日志
    logging.getLogger().handlers.clear()
    logging.getLogger().setLevel(logging.CRITICAL)

    return logger



def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_ids", nargs="+", help="one or more arXiv IDs, e.g. 2305.13860 1706.03762")
    parser.add_argument("--output_dir", default="./output", help="Output Directory")

    parser.add_argument("--poster_density", type=str, default="dense", choices=["sparse", "medium", "dense"])
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


def run_arxiv2agent_stage(args,logger):
    arxiv_dir = os.path.join(args.output_dir, "arxiv")
    failures = []
    for arxiv_id in args.arxiv_ids:
        try:
            paper = digest(arxiv_id=arxiv_id)
            from arxiv2agent._tex import get_default_cache_dir
            source_folder = str(get_default_cache_dir() / arxiv_id)
            output_path = write_digest(paper, output_dir=arxiv_dir, source_folder=source_folder, include_source=True)
            logger.info(f" ✅ Wrote: {output_path}")
        except Exception as exc:
            failures.append(arxiv_id)
            logger.error(f" ❌ FAILED: {arxiv_id} — {exc}")

    if len(args.arxiv_ids) > 1:
        logger.info(f"    ✅ Done: {len(args.arxiv_ids) - len(failures)}/{len(args.arxiv_ids)} papers digested.")
    if failures:
        logger.info(f"    ❌ Failed IDs: {' '.join(failures)}")
    if len(failures) == len(args.arxiv_ids):
        raise RuntimeError("All arXiv ID processing failed")

# & "D:\Anaconda3\envs\Pytorch\python.exe" .\code\entry.py 2402.17228
def main():
    # 初始化
    args = parse_args()
    app_config = load_app_config()

    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    logger = set_log(args)
    logger.info(" ✅ Finish file path initialization")

    try:
        from utils.transport_en import sync_english_prompts
    except ImportError:
        pass
    else:
        translated_files = sync_english_prompts(app_config)
        for index, filename in enumerate(translated_files, start=1):
            logger.info(f" ✅ 翻译成功{index}个文件: {filename}")

    # 下载ARXIV原论文,解析至JSON
    run_arxiv2agent_stage(args,logger)

    render_results = parser_arxiv.convert_root(args)
    failed = sum(result[1] == "failed" for result in render_results)
    logger.info(" ✅ LaTeX fragments: %d processed, %d failed", len(render_results), failed)

    # Convert Figures PDFs & Equations Latex to PNG
    figure_results = parser_arxiv.convert_figure_pdfs(args)
    figure_failed = sum(result[1] == "failed" for result in figure_results)
    logger.info(" ✅ Figure PDFs: %d processed, %d failed", len(figure_results), figure_failed)

    # 重炼论文资源
    extract_contents(args)

    # 提取主要内容(Title、Abstract、Introduction、Conclusion)
    extract_main_content(args)

    # 论文类型判断
    classification_results, classification_usage = classify_papers(app_config, args)
    for paper_id, result in classification_results.items():
        logger.info(" ✅ Paper type: %s | %s", paper_id, ", ".join(result["categories"]))
    logger.info(
        " ✅ Paper classification tokens | input=%d output=%d total=%d",
        classification_usage["prompt_tokens"],
        classification_usage["completion_tokens"],
        classification_usage["total_tokens"],
    )


    # 为论文公式添加VLM分析
    equation_usage = analyze_equations(app_config, args)
    logger.info(
        "Equation VLM tokens | input=%d output=%d total=%d",
        equation_usage["prompt_tokens"],
        equation_usage["completion_tokens"],
        equation_usage["total_tokens"],
    )


if __name__ == "__main__":
    sys.exit(main())
