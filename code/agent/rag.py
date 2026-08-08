import os
import json
import logging
import yaml

from lightrag import LightRAG
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from lightrag import QueryParam

from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from jinja2 import StrictUndefined, Template


from .response import get_json_from_response
from utils.retry import retry_sync,retry_async

logger = logging.getLogger(__name__)

# 建立便于RAG建库的内容列表
def create_content_list(args):
    temp_root = os.path.join(args.output_dir, "temp")
    results = {}

    for paper_id in sorted(os.listdir(temp_root)):
        logger.info(f"     ⏳ Creating content list: {paper_id}")
        paper_dir = os.path.join(temp_root, paper_id)

        sections_json = os.path.join(paper_dir, "sections.json")
        figures_json = os.path.join(paper_dir, "figures.json")
        tables_json = os.path.join(paper_dir, "tables.json")
        equations_json = os.path.join(paper_dir, "equations.json")

        with open(sections_json, "r", encoding="utf-8") as file:
            section_data = json.load(file)
        with open(figures_json, "r", encoding="utf-8") as file:
            figures = json.load(file)["figures"]
        with open(tables_json, "r", encoding="utf-8") as file:
            tables = json.load(file)["tables"]
        with open(equations_json, "r", encoding="utf-8") as file:
            equations = json.load(file)["equations"]

        title = section_data["title"]
        sections = section_data["sections"]
        content_list = [
            {
                "doc_id": f"{paper_id}__abstract",
                "section_title": "Abstract",
                "section_ids": [],
                "asset_ids": [],
                "index_text": f"# Abstract\n\n{section_data.get('abstract', '')}".strip(),
            }
        ]
        current = None
        figure_index = 0
        table_index = 0
        equation_index = 0

        for section in sections:
            section_id = section["id"]
            level = section_id.count(".")

            if level == 0:
                if current:
                    current["index_text"] = "\n\n".join(current["index_text"])
                    content_list.append(current)

                current = {
                    "doc_id": f"{paper_id}__section__{section_id.replace(':', '_')}",
                    "section_title": section["title"],
                    "section_ids": [],
                    "asset_ids": [],
                    "index_text": [],
                }

            heading = "#" * min(level + 1, 6)
            current["section_ids"].append(section_id)
            current["index_text"].append(
                f"{heading} {section.get('title', '')}\n\n\n{section.get('text', '')}".strip()
            )

            while figure_index < len(figures) and figures[figure_index].get("defined_in") == section_id:
                figure = figures[figure_index]
                current["asset_ids"].append(figure.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Figure]:",
                            f"{figure['id']} Caption: {figure.get('caption', '')}",
                            f"{figure['id']} Description: {figure.get('description', '')}",
                        ]
                    )
                )
                figure_index += 1

            while table_index < len(tables) and tables[table_index].get("defined_in") == section_id:
                table = tables[table_index]
                current["asset_ids"].append(table.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Table]:",
                            f"{table['id']} Caption: {table.get('caption', '')}",
                            f"{table['id']} Description as: {table.get('description', '')}",
                        ]
                    )
                )
                table_index += 1

            while equation_index < len(equations) and equations[equation_index].get("defined_in") == section_id:
                equation = equations[equation_index]
                current["asset_ids"].append(equation.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Equation]:",
                            f"{equation['id']} LaTeX Format: {equation['raw_tex']}",
                            f"{equation['id']} Description as: {equation.get('description', '')}",
                        ]
                    )
                )
                equation_index += 1

        if current:
            current["index_text"] = "\n\n".join(current["index_text"])
            content_list.append(current)

        result = {
            "paper_id": paper_id,
            "title": title,
            "abstract": section_data.get("abstract", ""),
            "authors": section_data.get("authors", []),
            "affiliations": section_data.get("affiliations", []),
            "content_list": content_list,
        }

        # 导出直观的中间文件 JSON & MARKDOWN
        rag_sections_dir = os.path.join(paper_dir, "rag_sections")
        os.makedirs(rag_sections_dir, exist_ok=True)
        for section in content_list:
            section_name = section["doc_id"].rsplit("__", 1)[-1]
            section_result = {
                "paper_id": paper_id,
                "title": title,
                **section,
            }
            with open(os.path.join(rag_sections_dir, section_name + ".json"), "w", encoding="utf-8") as file:
                json.dump(section_result, file, ensure_ascii=False, indent=2)
            with open(os.path.join(rag_sections_dir, section_name + ".md"), "w", encoding="utf-8") as file:
                file.write(section["index_text"])
                file.write("\n")

        with open(os.path.join(paper_dir, "content_list.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        logger.info(f"     ✅ Content list created: {paper_id} | sections={len(content_list)}")
        results[paper_id] = result

    return results

# 初始化RAG数据库
async def _initialize_rag(config, storage_dir):
    # 当前嵌入模型只支持如下：
    embedding_models = {
        "text-embedding-3-small": (1536, 8192),
        "text-embedding-3-large": (3072, 8192),
    }
    embedding_dim, embedding_tokens = embedding_models[config.embedding.model]

    async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return await retry_async(
            lambda: openai_complete_if_cache(
                config.llm.model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=config.llm.api_key,
                base_url=config.llm.base_url,
                **kwargs,
            )
        )

    async def embedding_func(texts, max_token_size=None):
        return await retry_async(
            lambda: openai_embed.func(
                texts,
                model=config.embedding.model,
                api_key=config.embedding.api_key,
                base_url=config.embedding.base_url,
                max_token_size=max_token_size,
            )
        )

    rag = LightRAG(
        working_dir=storage_dir,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=embedding_tokens,
            model_name=config.embedding.model,
            func=embedding_func,
        ),
        llm_model_name=config.llm.model,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag

# 批量建立RAG数据库
async def build_rag_database(config, args):
    temp_root = os.path.join(args.output_dir, "temp")
    results = {}

    for paper_id in sorted(os.listdir(temp_root)):
        paper_dir = os.path.join(temp_root, paper_id)
        content_file = os.path.join(paper_dir, "content_list.json")

        with open(content_file, "r", encoding="utf-8") as file:
            content_list = json.load(file)["content_list"]

        documents = [section["index_text"] for section in content_list]
        document_ids = [section["doc_id"] for section in content_list]
        source_files = [
            os.path.abspath(os.path.join(paper_dir, "rag_sections",section["doc_id"].rsplit("__", 1)[-1] + ".md",))
            for section in content_list
        ]
        storage_dir = os.path.join(paper_dir, "rag_storage")

        logger.info(f"     ⏳ Building LightRAG database: {paper_id} | sections={len(documents)}")
        rag = await _initialize_rag(config, storage_dir)
        try:
            await rag.ainsert(
                input=documents,
                ids=document_ids,
                file_paths=source_files,
                split_by_character="\n\n",  # 本地设置的段落分隔符
                split_by_character_only=False,
            )
        finally:
            await rag.finalize_storages()

        results[paper_id] = {
            "storage_dir": storage_dir,
            "documents": len(documents),
            "doc_ids": document_ids,
        }
        logging.info(f"     ✅ LightRAG database completed: {paper_id}")

    return results


async def query_rag_categories(config, args, categories):
    prompt_dir = os.path.join("code", "prompt", "en")
    with open(os.path.join(prompt_dir, "rag_queries.yaml"), "r", encoding="utf-8") as file:
        base_queries = yaml.safe_load(file)
    with open(os.path.join(prompt_dir, "rag_type_queries.yaml"), "r", encoding="utf-8") as file:
        type_queries = yaml.safe_load(file)

    results = {}
    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        logger.info(f"     ⏳ Running RAG queries: {paper_id}")
        paper_dir = os.path.join(temp_root, paper_id)
        content_file = os.path.join(paper_dir, "content_list.json")

        # 查询前清理上次运行的运行文件
        raw_file = os.path.join(paper_dir, "raw_query_results.json")
        if os.path.isfile(raw_file):
            os.remove(raw_file)

        with open(os.path.join(paper_dir, "paper_profile.json"), "r", encoding="utf-8") as file:
            profile = json.load(file)
        with open(os.path.join(paper_dir, "sections.json"), "r", encoding="utf-8") as file:
            sections = json.load(file)

        paper_types = profile.get("categories")
        queries = {name: list(base_queries[name]) for name in categories}
        type_question_counts = {}
        for paper_type in paper_types:
            type_question_counts[paper_type] = 0
            for name in queries:
                added_queries = type_queries.get(paper_type, {}).get(name, [])
                queries[name].extend(added_queries)
                type_question_counts[paper_type] += len(added_queries)
                # queries[name] = list(dict.fromkeys(queries[name]))


        rag = await _initialize_rag(config, os.path.join(paper_dir, "rag_storage"))
        text_queries = {name: [] for name in queries}
        try:
            for category, questions in queries.items():
                for question in questions:
                    try:
                        answer = await rag.aquery(
                            question,
                            param=QueryParam(mode="hybrid", enable_rerank=False),
                        )
                        text_queries[category].append(
                            {"query": question, "answer": answer, "mode": "hybrid", "success": True}
                        )
                    except Exception as error:
                        logger.error("     ❌ RAG query failed: %s | %s", paper_id, question)
                        text_queries[category].append(
                            {
                                "query": question,
                                "answer": None,
                                "mode": "hybrid",
                                "success": False,
                                "error": str(error),
                            }
                        )
        finally:
            await rag.finalize_storages()

        result = {
            "paper_id": paper_id,
            "paper_type": paper_types,
            "paper_info": {
                "title": sections.get("title", ""),
                "abstract": sections.get("abstract", ""),
                "authors": sections.get("authors", []),
                "affiliations": sections.get("affiliations", []),
            },
            "text_queries": text_queries,
            "asset_queries": {},
        }
        with open(raw_file, "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        results[paper_id] = result
        logger.info(f"     ✅ Categorized RAG queries completed: {paper_id}")

    return results

# RAG Asset Query (Figures & Tables & Equations)
def analyze_asset_categories(config, args, asset_categories):
    prompt_dir = os.path.join("code", "prompt", "en")
    with open(os.path.join(prompt_dir, "rag_queries.yaml"), "r", encoding="utf-8") as file:
        base_queries = yaml.safe_load(file)
    with open(os.path.join(prompt_dir, "rag_type_queries.yaml"), "r", encoding="utf-8") as file:
        type_queries = yaml.safe_load(file)
    with open(os.path.join(prompt_dir, "rag_asset_analyzer.yaml"), "r", encoding="utf-8") as file:
        asset_config = yaml.safe_load(file)

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=config.llm.model,
        model_config_dict={"temperature": 0.1},
        api_key=config.llm.api_key,
        url=config.llm.base_url,
    )
    asset_agent = ChatAgent(system_message=asset_config["system_prompt"], model=model)
    asset_template = Template(asset_config["template"], undefined=StrictUndefined)

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results = {}

    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        logger.info(f"     ⏳ Running asset evidence analysis: {paper_id}")
        paper_dir = os.path.join(temp_root, paper_id)

        with open(os.path.join(paper_dir, "raw_query_results.json"), "r", encoding="utf-8") as file:
            raw_results = json.load(file)
        with open(os.path.join(paper_dir, "sections.json"), "r", encoding="utf-8") as file:
            sections = json.load(file)
        with open(os.path.join(paper_dir, "paper_profile.json"), "r", encoding="utf-8") as file:
            profile = json.load(file)

        paper_types = profile["paper_type"]
        section_titles = {
            section.get("id", ""): section.get("title", "")
            for section in sections["sections"]
        }
        asset_files = {
            "figures": ("figures.json", "figures"),
            "tables": ("tables.json", "tables"),
            "equations": ("equations.json", "equations"),
        }

        for asset_type in asset_categories:
            filename, key = asset_files[asset_type]
            with open(os.path.join(paper_dir, filename), "r", encoding="utf-8") as file:
                assets = json.load(file)[key]

            asset_items = []
            for asset in assets:
                item = {
                    "id": asset["id"],
                    "defined_in": asset["defined_in"],
                    "section_title": section_titles[asset["defined_in"]],
                    "description": asset["description"],
                    "is_appendix": asset["is_appendix"],
                }
                if asset_type in ("figures", "tables"):
                    item["caption"] = asset["caption"]
                if asset_type == "equations":
                    item["raw_tex"] = asset["raw_tex"]
                asset_items.append(item)

            if not asset_items:
                raw_results["asset_queries"][asset_type] = {
                    "groups": [],
                    "excluded_resources": [],
                }
                continue

            selected_type_questions = []
            for paper_type in paper_types:
                selected_type_questions.extend(type_queries[paper_type].get(asset_type, []))
            # selected_type_questions = list(dict.fromkeys(selected_type_questions))

            questions = list(base_queries[asset_type])
            questions.extend(selected_type_questions)

            prompt = asset_template.render(
                asset_type=asset_type,
                paper_title=sections["title"],
                questions=json.dumps(questions, ensure_ascii=False, indent=2),
                assets_json=json.dumps(asset_items, ensure_ascii=False, indent=2),
            )
            def call_asset_agent():
                asset_agent.reset()
                return asset_agent.step(prompt)

            response = retry_sync(call_asset_agent)
            raw_results["asset_queries"][asset_type] = get_json_from_response(
                response.msgs[0].content
            )

            usage = response.info.get("usage", {})
            for name in total_usage:
                total_usage[name] += usage.get(name, 0) or 0

        with open(os.path.join(paper_dir, "raw_query_results.json"), "w", encoding="utf-8") as file:
            json.dump(raw_results, file, ensure_ascii=False, indent=2)
        results[paper_id] = raw_results
        logger.info(f"     ✅ Asset evidence analysis completed: {paper_id}")

    return results, total_usage
