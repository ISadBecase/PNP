import json
import logging
import os
import re

import yaml
from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from jinja2 import StrictUndefined, Template

from .response import get_json_from_response
from utils.retry import retry_sync


logger = logging.getLogger(__name__)


def build_summary_markdown(raw_results, markdown_file):
    paper_id = raw_results["paper_id"]
    logging.info(f"     ⏳ Building summary markdown: {paper_id}")

    paper_info = raw_results["paper_info"]
    parts = ["# Paper Information"]

    if paper_info.get("title"):
        parts.append(f"## Title\n\n{paper_info['title']}")
    if raw_results.get("paper_type"):
        paper_types = "\n".join(f"- {name}" for name in raw_results["paper_type"])
        parts.append(f"## Paper Types\n\n{paper_types}")
    if paper_info.get("authors"):
        parts.append(f"## Authors\n\n{', '.join(paper_info['authors'])}")
    if paper_info.get("affiliations"):
        affiliations = "\n".join(f"- {name}" for name in paper_info["affiliations"])
        parts.append(f"## Affiliations\n\n{affiliations}")
    if paper_info.get("abstract"):
        parts.append(f"## Abstract\n\n{paper_info['abstract']}")

    text_parts = []
    for category, items in raw_results.get("text_queries", {}).items():
        answers = []
        for item in items:
            # 对于回答失败的问题就跳过
            if item.get("success") is False:
                continue
            answer = item.get("answer", "").strip()
            answer = re.sub(r"\n+### References\b.*$", "", answer, flags=re.I | re.S).strip()
            if answer:
                answers.append(answer)
        if answers:
            title = category.replace("_", " ").title()
            text_parts.append(f"## {title}\n\n" + "\n\n---\n\n".join(answers))
    if text_parts:
        parts.append("# Text Evidence\n\n" + "\n\n".join(text_parts))

    asset_titles = {
        "figures": "Figure Evidence",
        "tables": "Table Evidence",
        "equations": "Equation Evidence",
    }
    for asset_type, asset_result in raw_results.get("asset_queries", {}).items():
        seen = set()
        asset_parts = []
        for index, group in enumerate(asset_result.get("groups", []), 1):
            resource_ids = group.get("resource_ids", [])
            for resource_id in resource_ids:
                if resource_id in seen:
                    raise ValueError(
                        f"Duplicate asset ID in {paper_id} {asset_type}: {resource_id}"
                    )
                seen.add(resource_id)
            role = group.get("Role") or group.get("topic") or group.get("role")
            role = role or f"Evidence Group {index}"
            lines = [f"## {role}"]
            if resource_ids:
                ids = ", ".join(f"`{resource_id}`" for resource_id in resource_ids)
                lines.append(f"**Resource IDs:** {ids}")
            if group.get("summary"):
                lines.append(f"**Summary:** {group['summary']}")
            if group.get("poster_value"):
                lines.append(f"**Poster Value:** {group['poster_value']}")
            asset_parts.append("\n\n".join(lines))

        if asset_parts:
            title = asset_titles.get(asset_type, f"{asset_type.title()} Evidence")
            parts.append(f"# {title}\n\n" + "\n\n".join(asset_parts))

    markdown = "\n\n---\n\n".join(parts).strip() + "\n"
    with open(markdown_file, "w", encoding="utf-8") as file:
        file.write(markdown)
    logging.info(f"     ✅ Summary markdown built: {paper_id} | {markdown_file}")
    return markdown


def summarize_papers(config, args):
    prompt_dir = os.path.join("code", "prompt", "en")
    with open(os.path.join(prompt_dir, "summary.yaml"), "r", encoding="utf-8") as file:
        summary_config = yaml.safe_load(file)
    with open(os.path.join(prompt_dir, "summary_type_guidance.yaml"), "r", encoding="utf-8") as file:
        type_guidance = yaml.safe_load(file)

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=config.llm.model,
        model_config_dict={"temperature": 0.1},
        api_key=config.llm.api_key,
        url=config.llm.base_url,
        max_retries=0,
    )
    agent = ChatAgent(
        system_message=summary_config["system_prompt"],
        model=model,
        retry_attempts=1,
    )
    template = Template(summary_config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results = {}

    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        paper_dir = os.path.join(temp_root, paper_id)
        raw_file = os.path.join(paper_dir, "raw_query_results.json")

        with open(raw_file, "r", encoding="utf-8") as file:
            raw_results = json.load(file)

        summary_markdown = build_summary_markdown(raw_results,os.path.join(paper_dir, "summary_input.md"),)

        # 根据文章类型引入指导性语言
        guidance = []
        for paper_type in raw_results.get("paper_type", []):
            if type_guidance.get(paper_type):
                guidance.append(type_guidance[paper_type])

        prompt = template.render(
            type_guidance="\n\n".join(guidance),
            summary_markdown=summary_markdown,
        )
        logger.info(f"     ✅ Summarizing poster evidence: {paper_id}")
        def call_summary_agent():
            agent.reset()
            return agent.step(prompt)

        response = retry_sync(call_summary_agent)
        result = get_json_from_response(response.msgs[0].content)

        # 建立资源集合
        allowed_ids = {"figures": set(), "tables": set(), "equations": set()}
        for asset_type, asset_result in raw_results.get("asset_queries", {}).items():
            for group in asset_result.get("groups", []):
                allowed_ids.get(asset_type, set()).update(group.get("resource_ids", []))

        theme_fields = {
            "figure_ids": "figures",
            "table_ids": "tables",
            "equation_ids": "equations",
        }
        for theme in result.get("themes", []):
            for field, asset_type in theme_fields.items():
                unknown = set(theme.get(field, [])) - allowed_ids[asset_type]
                if unknown:
                    raise ValueError(f"Unknown {asset_type} IDs in {paper_id}: {', '.join(sorted(unknown))}")

        usage = response.info.get("usage", {})
        for name in total_usage:
            total_usage[name] += usage.get(name, 0) or 0

        with open(os.path.join(paper_dir, "poster_evidence.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        results[paper_id] = result
        logger.info(f"     ✅ Poster evidence completed: {paper_id} | themes={len(result.get('themes', []))}")

    return results, total_usage
