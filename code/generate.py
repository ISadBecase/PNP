import base64
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Optional
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

from prompt.image_generation import (
    FORMAT_POSTER,
    POSTER_COMMON_STYLE_RULES,
    POSTER_FIGURE_HINT,
    POSTER_STYLE_HINTS,
    STYLE_PROCESS_PROMPT,
    VISUALIZATION_HINTS,
)

from utils.retry import retry_sync


@dataclass
class ProcessedStyle:
    style_name: str
    color_tone: str
    special_elements: str
    decorations: str
    valid: bool
    error: Optional[str] = None


def process_custom_style(client, user_style, model):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": STYLE_PROCESS_PROMPT.format(user_style=user_style)}
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return ProcessedStyle(
            style_name=result.get("style_name", ""),
            color_tone=result.get("color_tone", ""),
            special_elements=result.get("special_elements", ""),
            decorations=result.get("decorations", ""),
            valid=result.get("valid", False),
            error=result.get("error"),
        )
    except Exception as exc:
        return ProcessedStyle("", "", "", "", False, str(exc))


class ImageGenerator:
    def __init__(self, image_gen_config, prompt_config):
        self.prompt_model = prompt_config.model
        self.prompt_client = OpenAI(
            api_key=prompt_config.api_key,
            base_url=prompt_config.base_url,
        )

        self.image_model = image_gen_config.model
        self.image_client = OpenAI(
            api_key=image_gen_config.api_key,
            base_url=image_gen_config.base_url,
        )
        self.response_mime_type = image_gen_config.response_mime_type

    def generate(self, plan_data, poster_dir, image_size, image_quality, style="academic", custom_style=None):
        plan = plan_data["plan"]
        origin = plan_data["origin"]
        tables_index = {item["id"]: item for item in origin.get("tables", [])}
        figures_index = {item["id"]: item for item in origin.get("figures", [])}
        # TODO: 应该可以直接生成Markdown
        sections_markdown = self._format_sections_markdown(plan, tables_index, figures_index)

        images = self._load_referenced_images(plan, figures_index)

        processed_style = None
        if style == "custom" and custom_style:
            processed_style = self._process_custom_style(custom_style)
            if not processed_style.valid:
                raise ValueError(f"Invalid custom style: {processed_style.error}")
        prompt = self._build_poster_prompt(style, processed_style, sections_markdown)
        image_data, mime_type = self._generate_image(prompt, images, image_size, image_quality)

        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(mime_type, ".png")

        poster_path = os.path.join(poster_dir, f"poster{suffix}")
        with open(poster_path, "wb") as f:
            f.write(image_data)

        return {
            "poster_path": str(poster_path),
            "mime_type": mime_type,
            "num_reference_images": len(images),
        }

    def _process_custom_style(self, user_style):
        return process_custom_style(
            client=self.prompt_client,
            user_style=user_style,
            model=self.prompt_model,
        )

    @staticmethod
    def _load_referenced_images(plan, figures_index):
        image_ids = []
        for section in plan.get("sections", []):
            for reference in section.get("figures", []):
                figure_id = reference.get("figure_id", "")
                if figure_id not in image_ids:
                    image_ids.append(figure_id)

        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        images = []
        for figure_id in image_ids:
            if figure_id not in figures_index:
                raise ValueError(f"规划引用了不存在的图片：{figure_id}")
            figure = figures_index[figure_id]

            image_path = figure["path"]
            if not os.path.isabs(image_path):
                image_path = os.path.join(figure["base_path"], image_path)
            # 本地差异：源仓库缺图时跳过；这里必须中断，避免生成缺失关键素材的 Poster。
            if not os.path.isfile(image_path):
                raise FileNotFoundError(f"Poster 图片不存在：{image_path}({figure_id})")

            try:
                with open(image_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")
            except OSError as exc:
                raise RuntimeError(f"无法读取 Poster 图片：{image_path}({figure_id})") from exc
            images.append(
                {
                    "figure_id": figure_id,
                    "caption": figure.get("caption", ""),
                    "base64": image_data,
                    "mime_type": mime_map.get(os.path.splitext(image_path)[1].lower(), "image/jpeg"),
                }
            )
        return images

    @staticmethod
    def _format_sections_markdown(plan, tables_index, figures_index):
        parts = []
        for section in plan.get("sections"):
            lines = [
                f"## {section.get('title', 'Untitled Section')}",
                "",
                section.get("content", ""),
            ]
            for reference in section.get("tables"):
                table_id = reference.get("table_id")
                if table_id not in tables_index:
                    raise ValueError(f"     ❌ 规划引用了不存在的表格：{table_id}")
                table = tables_index[table_id]
                focus = reference.get("focus", "")
                lines.extend(
                    [
                        "",
                        f"**{table_id}**{f' (focus: {focus})' if focus else ''}:",
                        reference.get("extract") or table.get("html", ""),
                    ]
                )
            for reference in section.get("figures", []):
                figure_id = reference.get("figure_id", "")
                if figure_id not in figures_index:
                    raise ValueError(f"     ❌ 规划引用了不存在的图片：{figure_id}")
                figure = figures_index[figure_id]
                focus = reference.get("focus", "")
                caption = figure.get("caption", "")
                lines.extend(
                    [
                        "",
                        f"**{figure_id}**{f' (focus: {focus})' if focus else ''}: {caption}",
                        "[Reference image attached]",
                    ]
                )
            parts.append("\n".join(lines))
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _format_custom_style_for_poster(processed_style):
        parts = [
            processed_style.style_name + ".",
            "English text only.",
            "Use ROUNDED sans-serif fonts for ALL text.",
            "Characters should react to or interact with the content, with appropriate poses/actions and sizes - not just decoration."
            f"LIMITED COLOR PALETTE (3-4 colors max): {processed_style.color_tone}.",
            POSTER_COMMON_STYLE_RULES,
        ]
        if processed_style.special_elements:
            parts.append(processed_style.special_elements + ".")
        return " ".join(parts)

    @staticmethod
    def _build_poster_prompt(style_name, processed_style, sections_md):
        parts = [FORMAT_POSTER]
        if style_name == "custom" and processed_style:
            parts.append(
                f"Style: {ImageGenerator._format_custom_style_for_poster(processed_style)}"
            )
            if processed_style.decorations:
                parts.append(f"Decorations: {processed_style.decorations}")
        else:
            parts.append(POSTER_STYLE_HINTS.get(style_name))
        parts.append(VISUALIZATION_HINTS)
        parts.append(POSTER_FIGURE_HINT)
        parts.append(f"---\nContent:\n{sections_md}")
        return "\n\n".join(parts)

    def _generate_image(self, prompt, reference_images, image_size, image_quality):
        temporary_paths, image_files = [], []
        try:
            def call():
                # 有参考图时
                if image_files:
                    logger.info("     ⏳ Editing poster, with reference images")
                    response = self.image_client.images.edit(
                        model=self.image_model,
                        image=image_files,
                        prompt=prompt,
                        size=image_size,
                        quality=image_quality,
                    )
                # 无参考图时
                else:
                    logger.info(f"     ⏳ Generating poster, without reference images")
                    response = self.image_client.images.generate(
                        model=self.image_model,
                        prompt=prompt,
                        size=image_size,
                        quality=image_quality,
                    )
                image_base64 = response.data[0].b64_json if response.data else None
                if not image_base64:
                    raise RuntimeError("OpenAI 图片 API 未返回 b64_json 图片数据")
                return base64.b64decode(image_base64), "image/png"

            for index, image in enumerate(reference_images):
                suffix = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "image/gif": ".gif",
                }.get(image["mime_type"], ".png")
                temp_file = tempfile.NamedTemporaryFile(
                    mode="wb", suffix=suffix, prefix=f"poster_ref_{index}_", delete=False
                )
                temp_file.write(base64.b64decode(image["base64"]))
                temp_file.close()
                temporary_paths.append(temp_file.name)
                image_files.append(open(temp_file.name, "rb"))
            return retry_sync(call)
        finally:
            for image_file in image_files:
                image_file.close()
            for path in temporary_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

async def run_generate_stage(
    plan_data,
    poster_dir,
    image_size,
    image_quality,
    image_gen_config,
    prompt_config,
    style="academic",
    custom_style=None,
):
    generator = ImageGenerator(
        image_gen_config=image_gen_config,
        prompt_config=prompt_config,
    )
    return generator.generate(plan_data, poster_dir, image_size, image_quality, style, custom_style)
