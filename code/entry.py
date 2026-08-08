import argparse
import asyncio
import logging
import os
import shutil
import sys
import tempfile

from utils.load_env import load_app_config
from arxiv2agent import digest, write_digest

import agent.parser_arxiv as parser_arxiv
from agent.paper_classifier import classify_papers,extract_main_content
from agent.parser_vlm import analyze_equations,analyze_figures,analyze_tables
from agent.paper_elements import extract_contents
from agent.rag import analyze_asset_categories,build_rag_database,create_content_list,query_rag_categories
from agent.summary import summarize_papers


def set_log(args,close_log_info):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        os.path.join(args.output_dir, "run.log"),
        mode="w",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    for log_name in close_log_info:
        logging.getLogger(log_name).setLevel(logging.WARNING)

    return logging.getLogger("entry")

def run_arxiv2agent_stage(args,logger):
    arxiv_dir = os.path.join(args.output_dir, "arxiv")
    failures = []
    for arxiv_id in args.arxiv_ids:
        try:
            with tempfile.TemporaryDirectory(prefix="pnp_arxiv_") as download_dir:
                paper = digest(
                    arxiv_id=arxiv_id,
                    use_cache=False,
                    cache_dir=download_dir,
                )
                source_folder = os.path.join(download_dir, arxiv_id)
                output_path = write_digest(
                    paper,
                    output_dir=arxiv_dir,
                    source_folder=source_folder,
                    include_source=True,
                )
            logger.info(f"     ✅ Wrote: {output_path}")
        except Exception as exc:
            failures.append(arxiv_id)
            logger.error(f"     ❌ FAILED: {arxiv_id} — {exc}")

    if len(args.arxiv_ids) > 1:
        logger.info(f"    ✅ Done: {len(args.arxiv_ids) - len(failures)}/{len(args.arxiv_ids)} papers digested.")
    if failures:
        logger.info(f"    ❌ Failed IDs: {' '.join(failures)}")
    if len(failures) == len(args.arxiv_ids):
        raise RuntimeError("All arXiv ID processing failed")


STAGES = ["start","render","extract","classify","equation_vlm","figure_vlm","table_vlm","rag_content","rag_build","rag_query","asset_query","summary",]
RAG_QUERY_CATEGORIES = ["motivation", "solution", "results", "contributions"]
ASSET_QUERY_CATEGORIES = ["figures", "tables", "equations"]
CLOSE_LOG_INFO=["httpx","httpcore","openai","camel","PIL","nano-vectordb","lightrag"]

def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_ids", nargs="+", help="one or more arXiv IDs, e.g. 2305.13860 1706.03762")
    parser.add_argument("--output_dir", default="./output", help="Output Directory")
    parser.add_argument("--stage", default="start", choices=STAGES)
    parser.add_argument("--disable_vlm",nargs="*",default=["figure", "table"],choices=["equation", "figure", "table"])

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


# & "D:\Anaconda3\envs\Pytorch\python.exe" .\code\entry.py 2402.17228
def main():
    # 初始化
    args = parse_args()
    app_config = load_app_config()

    if args.stage == "start" and os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    logger = set_log(args,CLOSE_LOG_INFO)
    logger.info(" ✅ Finish file path initialization")
    logger.info(" ✅ Start pipeline from stage: %s", args.stage)
    try:
        from utils.transport_en import sync_english_prompts
    except ImportError:
        pass
    else:
        translated_files = sync_english_prompts(app_config)
        logger.info(f" ✅ 翻译成功{len(translated_files)}个文件")


    start_stage = STAGES.index(args.stage)

    if start_stage <= STAGES.index("start"):
        logger.info(" 🚀 [1/12] Start arXiv parsing")
        run_arxiv2agent_stage(args,logger)

    # Convert Figures PDFs & Equations Latex to PNG
    if start_stage <= STAGES.index("render"):
        logger.info(" 🚀 [2/12] Start LaTeX rendering")
        render_results = parser_arxiv.convert_root(args)
        failed = sum(result[1] == "failed" for result in render_results)
        logger.info(f" ✅ LaTeX fragments: {len(render_results)} processed, {failed} failed")
        figure_results = parser_arxiv.convert_figure_pdfs(args)
        figure_failed = sum(result[1] == "failed" for result in figure_results)
        logger.info(f" ✅ Figure PDFs: {len(figure_results)} processed, {figure_failed} failed")

    # 重炼论文资源
    if start_stage <= STAGES.index("extract"):
        logger.info(" 🚀 [3/12] Start paper element extraction")
        extract_contents(args)

    # 提取主要内容(Title、Abstract、Introduction、Conclusion)->论文类型判断
    if start_stage <= STAGES.index("classify"):
        logger.info(" 🚀 [4/12] Start paper classification")
        extract_main_content(args)
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
    if start_stage <= STAGES.index("equation_vlm"):
        if "equation" in args.disable_vlm:
            logger.info(" ⏭️ [5/12] Skip equation analysis")
        else:
            logger.info(" 🚀 [5/12] Start equation analysis")
            equation_usage = analyze_equations(app_config, args)
            logger.info(
                " ✅ Equation VLM tokens | input=%d output=%d total=%d",
                equation_usage["prompt_tokens"],
                equation_usage["completion_tokens"],
                equation_usage["total_tokens"],
            )

    # 为论文图片添加VLM分析
    if start_stage <= STAGES.index("figure_vlm"):
        if "figure" in args.disable_vlm:
            logger.info(" ⏭️ [6/12] Skip figure analysis")
        else:
            logger.info(" 🚀 [6/12] Start figure analysis")
            figure_usage = analyze_figures(app_config, args)
            logger.info(
                " ✅ Figure VLM tokens | input=%d output=%d total=%d",
                figure_usage["prompt_tokens"],
                figure_usage["completion_tokens"],
                figure_usage["total_tokens"],
            )

    # 为论文表格添加VLM分析
    if start_stage <= STAGES.index("table_vlm"):
        if "table" in args.disable_vlm:
            logger.info(" ⏭️ [7/12] Skip table analysis")
        else:
            logger.info(" 🚀 [7/12] Start table analysis")
            table_usage = analyze_tables(app_config, args)
            logger.info(
                " ✅ Table VLM tokens | input=%d output=%d total=%d",
                table_usage["prompt_tokens"],
                table_usage["completion_tokens"],
                table_usage["total_tokens"],
            )


    # RAG Build Resources
    if start_stage <= STAGES.index("rag_content"):
        logger.info(" 🚀 [8/12] Start RAG content construction")
        results = create_content_list(args)
        logger.info(f" ✅ RAG content list created : {', '.join(list(results.keys()))}")

    async def run_rag_stages(app_config, args, start_stage, logger):
        if start_stage <= STAGES.index("rag_build"):
            logger.info(" 🚀 [9/12] Start LightRAG database construction")
            results = await build_rag_database(app_config, args)
            logger.info(" ✅ LightRAG databases created: %s", ", ".join(results))

        if start_stage <= STAGES.index("rag_query"):
            logger.info(" 🚀 [10/12] Start categorized RAG queries")
            results = await query_rag_categories(
                app_config, args, RAG_QUERY_CATEGORIES
            )
            logger.info(" ✅ Raw query results created: %s", ", ".join(results))

    # RAG Main Content Query
    if start_stage <= STAGES.index("rag_query"):
        asyncio.run(run_rag_stages(app_config, args, start_stage, logger))

    # RAG Asset Query (Figures & Tables & Equations)
    if start_stage <= STAGES.index("asset_query"):
        logger.info(" 🚀 [11/12] Start figure, table and equation analysis")
        results, usage = analyze_asset_categories(
            app_config, args, ASSET_QUERY_CATEGORIES
        )
        logger.info(" ✅ Asset query results updated: %s", ", ".join(results))
        logger.info(
            " ✅ Asset query tokens | input=%d output=%d total=%d",
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
        )

    if start_stage <= STAGES.index("summary"):
        logger.info(" 🚀 [12/12] Start poster evidence summary")
        results, usage = summarize_papers(app_config, args)
        logger.info(" ✅ Poster evidence created: %s", ", ".join(results))
        logger.info(
            " ✅ Summary tokens | input=%d output=%d total=%d",
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
        )

    return


if __name__ == "__main__":
    sys.exit(main())
