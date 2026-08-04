import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import pyfiglet
from dotenv import load_dotenv
from rich.console import Console

from arxiv2agent import digest, write_digest
from batch import BatchParser
from generate import run_generate_stage
from plan import run_plan_stage
from prompt.query import RAG_PAPER_QUERIES, RAG_QUERY_MODES
from rag import RAGClient
from summary import run_summary_stage

from utils.load_env import load_app_config

def set_log(args):
    logger = logging.getLogger()
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(os.path.join(args.save_dir, "run.log"))  # 文件handler
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

# 控制台启动界面
def start_up():
    console = Console()
    logo=pyfiglet.figlet_format("PNP", font="starwars") # font="block", width=200
    console.print(logo, style="bold cyan")
    console.print("🚀 Initializing...\n")

# 初始化文件树和日志
def initialize(args):
    if not os.path.exists(args.source_dir):
        raise FileNotFoundError(f"Source directory does not exist")
    if not os.path.isdir(args.source_dir):
        raise ValueError(f"Source directory must be a directory")

    if os.path.exists(args.save_dir):
        shutil.rmtree(args.save_dir)
    os.makedirs(args.save_dir, exist_ok=True)
    os.makedirs(os.path.join(args.save_dir, "temp_result"), exist_ok=True)

    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    set_log(args)

def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_ids", nargs="+", help="one or more arXiv IDs, e.g. 2305.13860 1706.03762")
    parser.add_argument("--arxiv-output", default=r"D:\kao\PNP\arxiv_output", help="arxiv2agent digest 的父输出目录")
    parser.add_argument("--include-source", action="store_true", help="Copy source LaTeX files")
    parser.add_argument("--save_dir", type=str, default="D:\\kao\\PNP\\temp")
    parser.add_argument("--source_dir", type=str, default="D:\\kao\\PNP\\source")    # save temp file
    parser.add_argument("--output_dir", type=str, default="D:\\kao\\PNP\\output")    # save final poster
    parser.add_argument("--poster_density", type=str, default="dense",choices=["sparse", "medium", "dense"])
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
    failures = []
    for arxiv_id in args.arxiv_ids:
        try:
            paper = digest(arxiv_id=arxiv_id)
            from arxiv2agent._tex import get_default_cache_dir
            source_folder = str(get_default_cache_dir() / arxiv_id)
            output_path = write_digest(paper, output_dir=args.arxiv_output, source_folder=source_folder, include_source=args.include_source)
            print(f"Wrote: {output_path}", file=sys.stderr)
        except Exception as exc:
            failures.append(arxiv_id)
            print(f"FAILED: {arxiv_id} — {exc}", file=sys.stderr)

    if len(args.arxiv_ids) > 1:
        print(f"Done: {len(args.arxiv_ids) - len(failures)}/{len(args.arxiv_ids)} papers digested.", file=sys.stderr)
    if failures:
        print(f"Failed IDs: {' '.join(failures)}", file=sys.stderr)
    if len(failures) == len(args.arxiv_ids):
        raise RuntimeError("所有 arXiv ID 均处理失败")

# TODO:生成文件名可能会重叠，需要后续检查
def main(argv=None):
    args = parse_args(argv)
    run_arxiv2agent_stage(args)

    sys.exit()

    start_up()
    config = load_app_config()
    initialize(args)
    logging.info(" ✅ Finish file path initialization")

    # 解析文档
    logging.info("\n")
    logging.info(f" 🚀 Parsering files...")
    minparser=BatchParser()
    parser_batch_result = minparser.process_documents_batch(source_dir=args.source_dir,output_dir=args.save_dir)

    parser_batch_result_path = os.path.join(args.save_dir, "temp_result", "parser_batch_result.json")
    with open(parser_batch_result_path, "w", encoding="utf-8") as f:
        json.dump(parser_batch_result, f, ensure_ascii=False, indent=2)
    logging.info(f" ✅ Saved batch_result: {parser_batch_result_path}")

    async def process_agent():
        logging.info("\n")
        logging.info(" 🚀 Initializing RAGClient...")
        indexer = RAGClient(output_dir=args.save_dir, config=config)
        await indexer.initialize()
        # 建库
        logging.info("\n")
        logging.info(f" 🚀 Index before RAG...")
        rag_index_results = await indexer.index_batch(parser_batch_result)

        rag_index_results_path = os.path.join(args.save_dir, "temp_result", "rag_index_results.json")
        with open(rag_index_results_path, "w", encoding="utf-8") as f:
            json.dump(rag_index_results, f, ensure_ascii=False, indent=2)
        logging.info(f" ✅ Saved index_results: {rag_index_results_path}")

        # RAG
        logging.info("\n")
        logging.info(f" 🚀 Start RAG Query ...")
        rag_results = await indexer.batch_query_by_category(
            RAG_PAPER_QUERIES,
            RAG_QUERY_MODES,
            max_concurrency=2,  # 受限于OPENAI的TPM,我降低并发数8->2
        )
        rag_checkpoint = {
            "rag_results": rag_results,
            "markdown_paths": sorted(str(path) for path in Path(args.save_dir).rglob("*.md")),
            "input_paths": parser_batch_result["successful_files"],
            "mode": "normal",   # TODO:mode设置，和可支持的体验推荐
        }
        # 保存RAG检查点
        rag_checkpoint_path = os.path.join(args.save_dir, "temp_result", "rag_checkpoint.json")
        with open(rag_checkpoint_path, "w", encoding="utf-8") as file:
            json.dump(rag_checkpoint, file, ensure_ascii=False, indent=2)
        logging.info(f" ✅ Saved RAG checkpoint: {rag_checkpoint_path}")

        # 释放RAG Storage
        await indexer.close()
        logging.info(f" ✅ Release the RAG Storage")

        # Summary stage
        logging.info("\n")
        logging.info(f" 🚀 Start summary stage ...")
        content, summary_text, summary_checkpoint = await run_summary_stage(rag_checkpoint, config.llm)

        summary_path = os.path.join(args.save_dir,"temp_result", "summary.md")
        summary_checkpoint_path = os.path.join(args.save_dir, "temp_result", "summary_checkpoint.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary_text)
        with open(summary_checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(summary_checkpoint,f,ensure_ascii=False,indent=2,default=str)
        logging.info(f" ✅ Saved summary: {summary_path}")
        logging.info(f" ✅ Saved summary checkpoint: {summary_checkpoint_path}")

        # Plan stage
        logging.info("\n")
        logging.info(f" 🚀 Start plan stage ...")
        plan_temp_result, plan_checkpoint = await run_plan_stage(summary_checkpoint, args.poster_density, config.vlm, config.plan_max_tokens)

        plan_temp_result_path = os.path.join(args.save_dir, "temp_result", "plan_temp_result.json")
        plan_checkpoint_path = os.path.join(args.save_dir, "temp_result", "plan_checkpoint.json")
        with open(plan_temp_result_path, "w", encoding="utf-8") as f:
            json.dump(plan_temp_result,f,ensure_ascii=False,indent=2,default=str)
        with open(plan_checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(plan_checkpoint,f,ensure_ascii=False,indent=2,default=str)
        logging.info(f" ✅ Saved plan temp result: {plan_temp_result_path}")
        logging.info(f" ✅ Saved plan result checkpoint: {plan_checkpoint_path}")

        # Generation stage
        logging.info("\n")
        logging.info(f" 🚀 Start generation stage ...")
        poster_result = await run_generate_stage(
            plan_data=plan_checkpoint,
            poster_dir=args.output_dir,
            image_size=args.image_size,
            image_quality=args.image_quality,
            image_gen_config=config.image_gen,
            prompt_config=config.llm,
            style=args.style,
            custom_style=args.custom_style,
        )
        logging.info(f" 🎉🎉🎉 Finish generation stage: {poster_result['poster_path']} ...")


    asyncio.run(process_agent())
    return 0


if __name__ == "__main__":
    sys.exit(main())
