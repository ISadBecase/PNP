import json
import os


import yaml
from jinja2 import StrictUndefined, Template

from .response import get_json_from_response
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from camel.agents import ChatAgent

def classify_papers(app_config,content_dirs):
    classify_prompt="paper_classifier"
    with open(f"code/prompt/{classify_prompt}.yaml", "r", encoding="utf-8") as file:
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

    for content_dir in content_dirs:
        with open(os.path.join(content_dir, "main_section.json"), "r", encoding="utf-8") as file:
            paper_content = json.load(file)

        prompt = template.render(paper_main_content=paper_content)
        classify_agent.reset()
        response = classify_agent.step(prompt)
        result = get_json_from_response(response.msgs[0].content)

        with open(os.path.join(content_dir, "paper_profile.json"),"w",encoding="utf-8",) as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        paper_id=os.path.basename(content_dir)
        results[paper_id] = result

    return results
