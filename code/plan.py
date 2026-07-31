import base64
import json
import os
import re
from pathlib import Path
from openai import OpenAI

from prompt.poster_planning import (
    PAPER_POSTER_DENSITY_GUIDELINES,
    PAPER_POSTER_PLANNING_PROMPT,
)
from summary import PaperContent

from utils.retry import retry_sync


class ContentPlanner:
    def __init__(self, api_key, base_url, model, output_dir):
        self.model = model
        self.output_dir = output_dir
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def plan(self, summary_data, poster_density="medium"):
        content_data = summary_data["content"]
        content = PaperContent()
        for name in PaperContent.__dataclass_fields__:
            if name in content_data:
                setattr(content, name, content_data[name])
        summary = content.to_summary()
        # 按id索引图表
        origin = summary_data["origin"]
        tables_index = {table["id"]: table for table in origin.get("tables", [])}
        # Load figures
        figures_index = {figure["id"]: figure for figure in origin.get("figures", [])}
        tables_md = "\n\n---\n\n".join(
            f"**{table['id']}**: {table.get('caption', '')}\n\n{table.get('html', '')}"
            for table in tables_index.values()
        )
        figure_images = self._load_figure_images(origin, figures_index)
        density_guidelines = PAPER_POSTER_DENSITY_GUIDELINES.get(poster_density)    # 信息密度 prompt
        assets_section = self._build_assets_section(tables_md, bool(figure_images))

        prompt = PAPER_POSTER_PLANNING_PROMPT.format(
            density_guidelines=density_guidelines,
            summary=summary, # 源仓库会把摘要截断至 10000 个字符；这里按要求完整传入。
            assets_section=assets_section,
        )
        result = self._call_multimodal_llm(prompt, figure_images)

        return result,{
            "output_type": "poster",
            "sections": self._parse_sections(result, tables_index, figures_index),
            "metadata": {"density": poster_density},
        }

    # 加载图像列表，补充编码信息
    def _load_figure_images(self, origin, figures_index):
        images = []
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        for figure_id, figure in figures_index.items():
            image_path = Path(figure["path"])
            if not image_path.is_absolute():
                image_path = Path(figure["base_path"]) / image_path
            # 本地差异：源仓库在图片不存在时跳过；图片是本地 Poster 的必需素材，因此立即报错。
            if not image_path.is_file():
                raise FileNotFoundError(f"Not find image: {image_path}({figure_id})")
            try:
                image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
            except OSError as exc:
                # 本地差异：源仓库在图片读取失败时跳过；本地中断规划以避免生成缺图 Poster。
                raise RuntimeError(f"Cant read image file format: {image_path}({figure_id})") from exc
            images.append(
                {
                    "id": figure_id,
                    "caption": figure.get("caption", ""),
                    "mime_type": mime_map.get(image_path.suffix.lower(), "image/jpeg"),
                    "data": image_data,
                }
            )
        return images

    # 构建图表章节
    @staticmethod
    def _build_assets_section(tables_md, has_figures):
        has_tables = bool(tables_md)
        if not has_tables and not has_figures:
            return ""

        parts = [
            "Below are the original tables and figures. "
            "Tables contain precise data, figures illustrate concepts visually. "
            "Use them to supplement the content."
        ]

        if has_tables:
            parts.append("## Available Tables")
            parts.append(tables_md)

        if has_figures:
            parts.append("## Available Figures")
            parts.append("[FIGURE_IMAGES]")

        return "\n\n".join(parts)


    # 在prompt加入图片信息，输出Plan
    def _call_multimodal_llm(self, prompt, figure_images):
        # Add image prompts
        content = [{"type": "text", "text": prompt}]
        for image in figure_images:
            content.extend(
                [
                    {
                        "type": "text",
                        "text": f"Figure ID: {image['id']}\nCaption: {image['caption']}",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image['mime_type']};base64,{image['data']}"
                        },
                    },
                ]
            )
        # retry_sync 缓解429问题
        response = retry_sync(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                temperature=0.2,
                max_tokens=int(os.getenv("RAG_LLM_MAX_TOKENS")),
                response_format={"type": "json_object"},    # https://developers.openai.com/api/docs/guides/structured-outputs
            )
        )
        if response.choices[0].finish_reason == "length":
            raise RuntimeError("Poster 规划输出被 max_tokens 截断")
        return response.choices[0].message.content

    # TODO: 屎山
    @staticmethod
    def _parse_sections(result, tables_index, figures_index):
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", result, re.DOTALL)
        json_text = match.group(1) if match else result.strip()
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            # 本地差异：源仓库会返回兜底空计划；本地保留失败原因，避免生成不可用 Poster。
            raise ValueError("Poster 规划模型未返回合法 JSON") from exc

        sections = []
        for number, item in enumerate(data.get("sections", []), start=1):
            tables = item.get("tables", [])
            figures = item.get("figures", [])
            for table in tables:
                table_id = table.get("table_id", "")
                # 本地差异：源仓库不校验引用，后续可能静默丢弃；本地立即暴露错误。
                if table_id not in tables_index:
                    raise ValueError(f"规划引用了不存在的表格：{table_id}")
            for figure in figures:
                figure_id = figure.get("figure_id", "")
                # 本地差异：源仓库不校验引用，后续可能静默丢弃；本地立即暴露错误。
                if figure_id not in figures_index:
                    raise ValueError(f"规划引用了不存在的图片：{figure_id}")
            sections.append(
                {
                    "id": item.get("id") or f"section_{number}",
                    "title": item.get("title", "Untitled Section"),
                    "type": "content",
                    "content": item.get("content", ""),
                    "tables": tables,
                    "figures": figures,
                }
            )
        return sections


async def run_plan_stage(output_dir, poster_density="medium"):
    summary_path = os.path.join(output_dir, "checkpoint_summary.json")
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    # TODO: 环境检验，导入args
    api_key = os.getenv("RAG_LLM_API_KEY")
    planner = ContentPlanner(
        api_key=api_key,
        base_url=os.getenv("RAG_LLM_BASE_URL"),
        model=os.getenv("LLM_MODEL"),
        output_dir=output_dir,
    )
    temp_result,plan = planner.plan(summary_data, poster_density)
    result = {
        "plan": plan,
        "origin": summary_data["origin"],
        "content_type": summary_data.get("content_type", "paper"),
    }
    return temp_result, result
