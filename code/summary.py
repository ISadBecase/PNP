import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
import logging
import sys

from openai import OpenAI
from prompt.paper import EXTRACT_PROMPTS

from utils.retry import retry_async

# paper_info数据不应被LLM处理，直接从RAG结果中提取
# motivation, solution, results, contributions 内容应当提取凝练
# 特别的，solution和results 应当考虑图表数据
logger = logging.getLogger(__name__)

# paper_info figures tables equations motivation solution results contributions
SUMMARY_SECTIONS = ["paper_info", "motivation", "solution", "results", "contributions"]
LLM_SECTIONS = {"motivation", "solution", "results", "contributions"}
SECTION_TITLES = {
    "paper_info": "# Paper Information",
    "motivation": "# Motivation",
    "solution": "# Solution / Methodology",
    "results": "# Results",
    "contributions": "# Contributions",
}
SECTION_SUPPLEMENTS = {
    "solution": [
        ("figures", "The following are figures descriptions extracted from the paper:"),
        ("equations", "The following are equations extracted from the paper:"),
    ],
    "results": [
        ("tables", "The following are tables extracted from the paper:"),
    ],
}

@dataclass
class PaperContent:
    paper_info: str = ""
    figures: str = ""   # 仅 SUMMARY_SECTIONS 内数据包含
    tables: str = ""
    equations: str = ""
    motivation: str = ""
    solution: str = ""
    results: str = ""
    contributions: str = ""
    raw_rag_results: dict = field(default_factory=dict)

    def to_summary(self):
        parts = []
        for section in SUMMARY_SECTIONS:
            text = getattr(self, section)
            if text:
                parts.append(f"{SECTION_TITLES[section]}\n\n{text}")
        return "\n\n---\n\n".join(parts)

# 删除引用格式
def clean_references(text):
    text = re.sub(
        r"###\s*References\s*\n(?:[-*]\s*\[[^\]]+\][^\n]*\n?)*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*\(Reference\s*\[[^\]]+\](?:\s*,\s*\[[^\]]+\])*\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# 合并RAG结果
def merge_answers(rag_results, section, include_supplements=False):
    answers = []
    for item in rag_results.get(section):
        answer = item.get("answer", "")
        if answer and len(answer) > 50:
            answers.append(clean_references(answer))
    merged = "\n\n---\n\n".join(answers)

    if not include_supplements:
        return merged

    supplements = SECTION_SUPPLEMENTS.get(section, [])
    if not supplements:
        return merged

    # 对指定section的补充内容进行合并
    parts = [merged] if merged else []
    parts = [merged] if merged else []
    for supplement, title in supplements:
        text = merge_answers(
            rag_results,
            supplement,
            include_supplements=False,
        )
        if text:
            parts.append(f"{title}\n\n{text}")
    return "\n\n---\n\n".join(parts)

# 根据附属图表公式等材料的文本二次总结
async def _extract_section(content, section, client, model):
    if len(content) < 100:
        return ""
    response = await retry_async(
        lambda: asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[{"role": "user", "content": EXTRACT_PROMPTS[section].format(content=content)}],
            max_tokens=6000,    # 原始为4000 max_tokens限制
        )
    )   # retry_async 缓解429问题
    return response.choices[0].message.content

# 将图表公式等材料的文本使用LLM融入最终总结
async def extract_paper(
    rag_results,
    client,
    model,
    parallel=True,
    max_concurrency=5,
):
    content = PaperContent(raw_rag_results=rag_results)
    llm_tasks = {}

    for section in SUMMARY_SECTIONS:
        if section in LLM_SECTIONS:             # motivation, solution, results, contributions
            merged = merge_answers(
                rag_results,
                section,
                include_supplements=True,
            )
            if merged:
                llm_tasks[section] = merged
        else:                                   # paper_info
            merged = merge_answers(rag_results, section)
            if merged:
                setattr(content, section, merged)

    # 对于附属内容 SECTION_SUPPLEMENTS 的二次总结
    extracted_sections = []
    if llm_tasks and parallel:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def extract_with_semaphore(section, merged):
            async with semaphore:
                return section, await _extract_section(merged, section, client, model)

        extracted_sections = await asyncio.gather(
            *(extract_with_semaphore(section, merged) for section, merged in llm_tasks.items())
        )
    elif llm_tasks:
        for section, merged in llm_tasks.items():
            extracted_sections.append(
                (section, await _extract_section(merged, section, client, model))
            )

    for section, extracted in extracted_sections:
        if extracted:
            setattr(content, section, extracted)
    return content


def _find_caption(content, start, end, kind):
    if kind == "Figure":
        pattern = r"((?:Figure|Image)\s+\d+[a-z]?)\s*[:.]?\s*([^\n]+)"
        regions = (content[end : end + 500], content[max(0, start - 500) : start])
    else:
        pattern = r"(Table\s+\d+[a-z]?)\s*[:.]?\s*([^\n]+)"
        regions = (content[max(0, start - 500) : start], content[end : end + 500])

    for region in regions:
        match = re.search(pattern, region, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2).strip()
    return "", ""

# 从markdown文件中提取图表和表格信息
def extract_tables_and_figures(markdown_path):
    with open(markdown_path, "r", encoding="utf-8") as f:
        text = f.read()
    figures, tables = [], []
    base_path = os.path.dirname(os.path.abspath(markdown_path))

    for index, match in enumerate(
        re.finditer(r"!\[[^\]]*\]\((images/[^)]+)\)", text), 1
    ):
        figure_id, caption = _find_caption(text, match.start(), match.end(), "Figure")
        figures.append(
            {
                "id": figure_id or f"Figure {index}",
                "caption": caption,
                "path": match.group(1),
                "base_path": base_path,
            }
        )

    for index, match in enumerate(
        re.finditer(r"<table\b[^>]*>.*?</table>", text, re.IGNORECASE | re.DOTALL), 1
    ):
        table_id, caption = _find_caption(text, match.start(), match.end(), "Table")
        tables.append(
            {
                "id": table_id or f"Doc Table {index}",
                "caption": caption,
                "html": match.group(0),
                "base_path": base_path,
            }
        )

    return {
        "tables": tables,
        "figures": figures,
        "base_path": base_path,
    }


async def run_summary_stage(rag_data, llm_config):
    rag_results = rag_data["rag_results"]
    client = OpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)
    model = llm_config.model

    # content = await extract_paper(rag_results, client, model, parallel=True, max_concurrency=5)
    content = await extract_paper(rag_results, client, model, parallel=True, max_concurrency=2)   # 由于OPENAI的TPM限制，我改为串行处理，避免并发过高导致失败
    summary_text = content.to_summary()

    all_tables, all_figures = [], []
    markdown_paths = rag_data.get("markdown_paths")
    for index, markdown_path in enumerate(markdown_paths, 1):
        origin = extract_tables_and_figures(markdown_path)
        if len(markdown_paths) > 1:
            prefix = f"Doc{index}_"
            for table in origin["tables"]:
                if not table["id"].startswith(prefix):
                    table["id"] = f"{prefix}{table['id']}"
            for figure in origin["figures"]:
                if not figure["id"].startswith(prefix):
                    figure["id"] = f"{prefix}{figure['id']}"
        all_tables.extend(origin["tables"])
        all_figures.extend(origin["figures"])

    logging.info(f"    ✅ Extracted {len(all_tables)} tables and {len(all_figures)} figures from all markdown files.")
    summary_checkpoint = {
        "content_type": rag_data.get("content_type"),
        "content": asdict(content),
        "origin": {
            "tables": all_tables,
            "figures": all_figures,
        },
        "markdown_paths": markdown_paths,
        "mode": rag_data.get("mode", "normal"),
    }

    return content, summary_text, summary_checkpoint
