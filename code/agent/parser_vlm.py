import json
import os

import yaml
from PIL import Image
from jinja2 import Template, StrictUndefined
from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType

from utils.retry import retry_sync
from .response import get_json_from_response
from .paper_elements import extract_equations


def _step_agent(agent, message):
    agent.reset()
    return agent.step(message)


# 加载图片，增加白底
def load_equation_image(png_path):
    image = Image.open(png_path).convert("RGBA")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, image).convert("RGB")

# 为公式增加注释 description
def analyze_equations(app_config, args):
    equations_prompt="equation_analyzer"
    with open(os.path.join("code", "prompt", "en", f"{equations_prompt}.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=app_config.vlm.model,
        model_config_dict={"temperature": 0.1},
        api_key=app_config.vlm.api_key,
        url=app_config.vlm.base_url,
    )
    equation_agent = ChatAgent(
        system_message=config["system_prompt"],
        model=model,
    )
    template = Template(config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    temp_dir = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_dir)):
        paper_dir = os.path.join(temp_dir, paper_id)

        equations_json = os.path.join(paper_dir, "equations.json")
        with open(equations_json, "r", encoding="utf-8") as file:
            equations = json.load(file)

        sections_json = os.path.join(paper_dir, "sections.json")
        with open(sections_json, "r", encoding="utf-8") as file:
            sections = json.load(file)

        for equation in equations["equations"]:
            paper_title = sections["title"]

            context_section = {"title": "", "text": ""}
            for section in sections.get("sections", []):
                if section.get("id") == equation.get("defined_in"):
                    context_section = section
                    break

            prompt = template.render(
                raw_tex=equation["raw_tex"],
                paper_title=paper_title,
                section_title=context_section["title"],
                section_text=context_section["text"],
                is_appendix=equation["is_appendix"]
            )
            image = load_equation_image(equation["png_file"])
            message = BaseMessage.make_user_message(
                role_name="Equation Analyst",
                content=prompt,
                image_list=[image],
                image_detail="high",
            )
            response = retry_sync(lambda: _step_agent(equation_agent, message))
            result = get_json_from_response(response.msgs[0].content)

            equation["description"] = result.get("description", "")

            usage = response.info.get("usage", {})
            for name in total_usage:
                total_usage[name] += usage.get(name, 0) or 0

        with open(equations_json, "w", encoding="utf-8") as file:
            json.dump(equations, file, ensure_ascii=False, indent=2)

    return total_usage

# 为图片增加注释 description
def analyze_figures(app_config, args):
    figures_prompt = "figure_analyzer"
    with open(os.path.join("code", "prompt", "en", f"{figures_prompt}.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=app_config.vlm.model,
        model_config_dict={"temperature": 0.1},
        api_key=app_config.vlm.api_key,
        url=app_config.vlm.base_url,
    )
    figure_agent = ChatAgent(
        system_message=config["system_prompt"],
        model=model,
    )
    template = Template(config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    temp_dir = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_dir)):
        paper_dir = os.path.join(temp_dir, paper_id)

        figures_json = os.path.join(paper_dir, "figures.json")
        with open(figures_json, "r", encoding="utf-8") as file:
            figures = json.load(file)

        sections_json = os.path.join(paper_dir, "sections.json")
        with open(sections_json, "r", encoding="utf-8") as file:
            sections = json.load(file)

        for figure in figures["figures"]:
            paper_title = sections["title"]

            context_section = {"title": "", "text": ""}
            for section in sections.get("sections", []):
                if section.get("id") == figure.get("defined_in"):
                    context_section = section
                    break

            prompt = template.render(
                caption=figure["caption"],
                paper_title=paper_title,
                section_title=context_section["title"],
                section_text=context_section["text"],
                is_appendix=figure["is_appendix"],
            )
            image = load_equation_image(figure["png_path"])
            message = BaseMessage.make_user_message(
                role_name="Figure Analyst",
                content=prompt,
                image_list=[image],
                image_detail="high",
            )
            response = retry_sync(lambda: _step_agent(figure_agent, message))
            result = get_json_from_response(response.msgs[0].content)

            figure["description"] = result.get("description", "")

            usage = response.info.get("usage", {})
            for name in total_usage:
                total_usage[name] += usage.get(name, 0) or 0

        with open(figures_json, "w", encoding="utf-8") as file:
            json.dump(figures, file, ensure_ascii=False, indent=2)

    return total_usage

# 为表格增加注释 description
def analyze_tables(app_config, args):
    tables_prompt = "table_analyzer"
    with open(os.path.join("code", "prompt", "en", f"{tables_prompt}.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=app_config.vlm.model,
        model_config_dict={"temperature": 0.1},
        api_key=app_config.vlm.api_key,
        url=app_config.vlm.base_url,
    )
    table_agent = ChatAgent(
        system_message=config["system_prompt"],
        model=model,
    )
    template = Template(config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    temp_dir = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_dir)):
        paper_dir = os.path.join(temp_dir, paper_id)

        tables_json = os.path.join(paper_dir, "tables.json")
        with open(tables_json, "r", encoding="utf-8") as file:
            tables = json.load(file)

        sections_json = os.path.join(paper_dir, "sections.json")
        with open(sections_json, "r", encoding="utf-8") as file:
            sections = json.load(file)

        for table in tables["tables"]:
            paper_title = sections["title"]

            context_section = {"title": "", "text": ""}
            for section in sections.get("sections", []):
                if section.get("id") == table.get("defined_in"):
                    context_section = section
                    break

            prompt = template.render(
                caption=table["caption"],
                raw_tex=table["raw_tex"],
                paper_title=paper_title,
                section_title=context_section["title"],
                section_text=context_section["text"],
                is_appendix=table["is_appendix"],
            )
            image = load_equation_image(table["png_file"])
            message = BaseMessage.make_user_message(
                role_name="Table Analyst",
                content=prompt,
                image_list=[image],
                image_detail="high",
            )
            response = retry_sync(lambda: _step_agent(table_agent, message))
            result = get_json_from_response(response.msgs[0].content)

            table["description"] = result.get("description", "")

            usage = response.info.get("usage", {})
            for name in total_usage:
                total_usage[name] += usage.get(name, 0) or 0

        with open(tables_json, "w", encoding="utf-8") as file:
            json.dump(tables, file, ensure_ascii=False, indent=2)

    return total_usage
