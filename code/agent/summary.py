import json
import logging
import os

import yaml
from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from jinja2 import StrictUndefined, Template

from .response import get_json_from_response
from utils.retry import retry_sync


logger = logging.getLogger(__name__)


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
    )
    agent = ChatAgent(system_message=summary_config["system_prompt"], model=model)
    template = Template(summary_config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results = {}
    temp_root = os.path.join(args.output_dir, "temp")

    for paper_id in sorted(os.listdir(temp_root)):
        paper_dir = os.path.join(temp_root, paper_id)
        raw_file = os.path.join(paper_dir, "raw_query_results.json")
        if not os.path.isfile(raw_file):
            continue

        with open(raw_file, "r", encoding="utf-8") as file:
            raw_results = json.load(file)

        guidance = []
        for paper_type in raw_results.get("paper_type", []):
            if type_guidance.get(paper_type):
                guidance.append(type_guidance[paper_type])

        prompt = template.render(
            poster_density=args.poster_density,
            type_guidance="\n\n".join(guidance),
            raw_results=json.dumps(raw_results, ensure_ascii=False, indent=2),
        )
        logger.info("     Summarizing poster evidence: %s", paper_id)
        def call_summary_agent():
            agent.reset()
            return agent.step(prompt)

        response = retry_sync(call_summary_agent)
        result = get_json_from_response(response.msgs[0].content)

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
                    raise ValueError(
                        f"Unknown {asset_type} IDs in {paper_id}: {', '.join(sorted(unknown))}"
                    )

        usage = response.info.get("usage", {})
        for name in total_usage:
            total_usage[name] += usage.get(name, 0) or 0

        with open(os.path.join(paper_dir, "poster_evidence.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        results[paper_id] = result
        logger.info("     Poster evidence completed: %s | themes=%d", paper_id, len(result.get("themes", [])))

    return results, total_usage
