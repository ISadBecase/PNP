import json
import os
import re

import yaml
from jinja2 import StrictUndefined, Template

from .response import get_json_from_response
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from camel.agents import ChatAgent

# 论文重点内容提取
INTRODUCTION_NAMES = [ "introduction"]
CONCLUSION_NAMES = ["conclusion", "conclusions", "conclusion and future work","conclusions and future work"]
def extract_main_content(args):
    temp_dir=os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_dir)):
        paper_dir = os.path.join(temp_dir, paper_id)
        sections_json = os.path.join(paper_dir, "sections.json")

        with open(sections_json, "r", encoding="utf-8") as file:
            sections = json.load(file)

        main_sections = {
            "Title": sections.get("title", ""),
            "Abstract": sections.get("abstract", ""),
        }
        for section in sections.get("sections", []):
            title = section.get("title", "").strip().lower()
            title = re.sub(r"^\d+(?:\.\d+)*[\s.:-]+", "", title)    # 删除章节标题开头的数字编号及其分隔符
            if title in INTRODUCTION_NAMES:
                main_sections["Introduction"] = section.get("text", "")
            elif title in CONCLUSION_NAMES:
                main_sections["Conclusion"] = section.get("text", "")
        main_json = os.path.join(paper_dir, "main_section.json")
        with open(main_json, "w", encoding="utf-8") as file:
            json.dump(main_sections, file, ensure_ascii=False, indent=4)

# 判定论文属性
def classify_papers(app_config,args):
    classify_prompt="paper_classifier"
    with open(os.path.join("code", "prompt", "en", f"{classify_prompt}.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    classify_model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=app_config.llm.model,
        model_config_dict={"temperature": 0.1},
        api_key=app_config.llm.api_key,
        url=app_config.llm.base_url,
    )
    classify_agent = ChatAgent(
        system_message=config["system_prompt"],
        model=classify_model,
        message_window_size=4,
    )
    template = Template(config["template"], undefined=StrictUndefined)
    results = {}
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    temp_dir=os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_dir)):
        paper_dir = os.path.join(temp_dir, paper_id)
        with open(os.path.join(paper_dir, "main_section.json"), "r", encoding="utf-8") as file:
            paper_main_content = json.load(file)

        prompt = template.render(paper_main_content=paper_main_content)
        classify_agent.reset()
        response = classify_agent.step(prompt)
        result = get_json_from_response(response.msgs[0].content)

        usage = response.info.get("usage", {})
        for name in total_usage:
            total_usage[name] += usage.get(name, 0) or 0

        with open(os.path.join(paper_dir, "paper_profile.json"),"w",encoding="utf-8",) as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        results[paper_id] = result

    return results, total_usage
