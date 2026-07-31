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

from batch import BatchParser
from generate import run_generate_stage
from plan import run_plan_stage
from prompt.query import RAG_PAPER_QUERIES, RAG_QUERY_MODES
from rag import RAGClient
from summary import run_summary_stage

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


def start_up():
    console = Console()
    logo=pyfiglet.figlet_format("PNP", font="starwars") # font="block", width=200
    console.print(logo, style="bold cyan")
    console.print("🚀 Initializing...\n")

def initialize(args):
    if os.path.exists(args.save_dir):
        shutil.rmtree(args.save_dir)
    os.makedirs(args.save_dir, exist_ok=True)

    if not os.path.exists(args.source_dir):
        raise FileNotFoundError(f"Source directory does not exist")
    if not os.path.isdir(args.source_dir):
        raise ValueError(f"Source directory must be a directory")

    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    set_log(args)
    load_dotenv()       # TODO: 环境验证程序+

def parse_args():
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()
    return args



# TODO:生成文件名可能会重叠，需要后续检查
if __name__ == "__main__":
    start_up()
    args = parse_args()
    initialize(args)
    logging.info(" ✅ Finish file path initialization")

    # 解析
    logging.info("\n")
    logging.info(f" 🚀 Parsering files...")
    minparser=BatchParser()
    batch_result = minparser.process_documents_batch(source_dir=args.source_dir,output_dir=args.save_dir)
    # 保存解析中间结果
    batch_result_path = os.path.join(args.save_dir, "batch_result.json")
    with open(batch_result_path, "w", encoding="utf-8") as f:
        json.dump(batch_result, f, ensure_ascii=False, indent=2)
    logging.info(f" ✅ Saved batch_result: {batch_result_path}")

    async def process_agent():
        logging.info("\n")
        logging.info(" 🚀 Initializing RAGClient...")
        indexer = RAGClient(output_dir=args.save_dir)
        await indexer.initialize()
        # 建库
        logging.info("\n")
        logging.info(f" 🚀 Index before RAG...")
        index_results = await indexer.index_batch(batch_result)
        # 保存建库中间结果
        index_results_path = os.path.join(args.save_dir, "index_results.json")
        with open(index_results_path, "w", encoding="utf-8") as f:
            json.dump(index_results, f, ensure_ascii=False, indent=2)
        logging.info(f" ✅ Saved index_results: {index_results_path}")

        # RAG
        logging.info("\n")
        logging.info(f" 🚀 Start RAG Query ...")
        rag_results = await indexer.batch_query_by_category(
            RAG_PAPER_QUERIES,
            RAG_QUERY_MODES,
            max_concurrency=2,  # 受限于OPENAI的TPM,我降低并发数8->2
        )
        checkpoint = {
            "rag_results": rag_results,
            "markdown_paths": sorted(str(path) for path in Path(args.save_dir).rglob("*.md")),
            "input_paths": batch_result["successful_files"],
            "mode": "normal",   # TODO:mode设置，和可支持的体验推荐
        }
        # 保存RAG检查点
        checkpoint_path = os.path.join(args.save_dir, "checkpoint_rag.json")
        with open(checkpoint_path, "w", encoding="utf-8") as file:
            json.dump(checkpoint, file, ensure_ascii=False, indent=2)
        logging.info(f" ✅ Saved RAG checkpoint: {checkpoint_path}")

        # 释放RAG Storage
        await indexer.close()
        logging.info(f" ✅ Release the RAG Storage")

        # Summary阶段
        logging.info("\n")
        logging.info(f" 🚀 Start summary stage ...")
        content, summary_text, result = await run_summary_stage(args.save_dir, checkpoint)

        # 保存中间结果
        summary_path = os.path.join(args.save_dir, "summary.md")
        checkpoint_path = os.path.join(args.save_dir, "checkpoint_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary_text)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        logging.info(f" ✅ Saved summary: {summary_path}")
        logging.info(f" ✅ Saved summary checkpoint: {checkpoint_path}")

        # Plan stage
        logging.info("\n")
        logging.info(f" 🚀 Start plan stage ...")
        plan_temp_result, plan_result = await run_plan_stage(args.save_dir, poster_density=args.poster_density)
        # 保存中间结果
        plan_temp_result_path = os.path.join(args.save_dir, "plan_temp_result.json")
        plan_result_path = os.path.join(args.save_dir, "checkpoint_plan.json")
        with open(plan_temp_result_path, "w", encoding="utf-8") as f:
            json.dump(plan_temp_result,f,ensure_ascii=False,indent=2,default=str)
        with open(plan_result_path, "w", encoding="utf-8") as f:
            json.dump(plan_result,f,ensure_ascii=False,indent=2,default=str)
        logging.info(f" ✅ Saved plan temp result: {plan_temp_result_path}")
        logging.info(f" ✅ Saved plan result checkpoint: {plan_result_path}")

        # Generation stage
        logging.info("\n")
        logging.info(f" 🚀 Start generation stage ...")
        poster_result = await run_generate_stage(args.save_dir,args.output_dir, args.image_size, args.image_quality, style="academic")
        logging.info(f" 🎉🎉🎉 Finish generation stage: {poster_result['poster_path']} ...")


    asyncio.run(process_agent())