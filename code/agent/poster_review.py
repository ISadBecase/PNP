import json
import logging
import os
import shutil

import yaml
from PIL import Image
from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from jinja2 import StrictUndefined, Template

from .poster_latex import render_poster_columns
from .response import get_json_from_response
from utils.retry import retry_sync


logger = logging.getLogger(__name__)


def _save_column_iteration(poster_dir, layout, iteration):
    iteration_dir = os.path.join(
        poster_dir, "iterations", f"iteration_{iteration:02d}"
    )
    os.makedirs(iteration_dir, exist_ok=True)
    for column_name in ("left", "right"):
        shutil.copyfile(
            os.path.join(poster_dir, "previews", column_name + ".png"),
            os.path.join(iteration_dir, column_name + ".png"),
        )
    with open(os.path.join(iteration_dir, "layout.json"), "w", encoding="utf-8") as file:
        json.dump(layout, file, ensure_ascii=False, indent=2)
    return iteration_dir


def _create_agent(config, system_prompt):
    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=config.vlm.model,
        model_config_dict={"temperature": 0.1},
        api_key=config.vlm.api_key,
        url=config.vlm.base_url,
        max_retries=0,
    )
    return ChatAgent(system_message=system_prompt, model=model, retry_attempts=1)


def _call_agent(agent, prompt, image_file, role_name):
    image = Image.open(image_file).convert("RGB")
    message = BaseMessage.make_user_message(
        role_name=role_name,
        content=prompt,
        image_list=[image],
        image_detail="high",
    )

    def call():
        agent.reset()
        return agent.step(message)

    return retry_sync(call)


def _apply_adjustments(layout, adjustments):
    changed = False
    panels = {panel["panel_id"]: panel for panel in layout["panels"]}
    for adjustment in adjustments:
        if adjustment.get("action") not in ("increase_asset_height", "decrease_asset_height"):
            continue
        panel = panels.get(adjustment.get("panel_id"))
        if not panel:
            continue
        asset = next(
            (item for item in panel["assets"] if item["id"] == adjustment.get("asset_id")),
            None,
        )
        if not asset:
            continue
        ratio = adjustment.get("ratio", 1.0)
        if not isinstance(ratio, (int, float)):
            continue
        ratio = min(max(float(ratio), 0.8), 1.2)
        old_height = asset["display_height"]
        height = min(max(asset["display_height"] * ratio, asset["min_height"]), asset["max_height"])
        if abs(height - old_height) > 0.01:
            asset["display_height"] = round(height, 3)
            difference = asset["display_height"] - old_height
            panel["asset_height"] = round(panel["asset_height"] + difference, 3)
            panel["estimated_height"] = round(panel["estimated_height"] + difference, 3)
            changed = True
    return changed


def review_poster_columns(config, args):
    prompt_file = os.path.join("code", "prompt", "en", "poster_column_review.yaml")
    with open(prompt_file, "r", encoding="utf-8") as file:
        prompt_config = yaml.safe_load(file)
    with open(os.path.join("code", "config", "poster_layout.yaml"), "r", encoding="utf-8") as file:
        layout_config = yaml.safe_load(file)

    agent = _create_agent(config, prompt_config["system_prompt"])
    template = Template(prompt_config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results = {}
    temp_root = os.path.join(args.output_dir, "temp")

    for paper_id in sorted(os.listdir(temp_root)):
        poster_dir = os.path.join(temp_root, paper_id, "poster")
        layout_file = os.path.join(poster_dir, "poster_layout.json")
        if not os.path.isfile(layout_file):
            continue
        reviews = []
        for iteration in range(layout_config["layout"]["max_iterations"]):
            with open(layout_file, "r", encoding="utf-8") as file:
                layout = json.load(file)
            iteration_dir = _save_column_iteration(poster_dir, layout, iteration)
            iteration_reviews = {}
            changed = False
            for column_name in ("left", "right"):
                panel_ids = layout["columns"][column_name]["panel_ids"]
                column_panels = [panel for panel in layout["panels"] if panel["panel_id"] in panel_ids]
                prompt = template.render(
                    column_name=column_name,
                    column_json=json.dumps(
                        {
                            "available_height": layout["canvas"]["body_height"],
                            "current_height": layout["columns"][column_name]["estimated_height"],
                            "utilization": layout["columns"][column_name].get("utilization"),
                            "panels": column_panels,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                image_file = os.path.join(poster_dir, "previews", column_name + ".png")
                response = _call_agent(agent, prompt, image_file, "Poster Column Reviewer")
                review = get_json_from_response(response.msgs[0].content)
                iteration_reviews[column_name] = review
                changed = _apply_adjustments(layout, review.get("adjustments", [])) or changed
                usage = response.info.get("usage", {})
                for name in total_usage:
                    total_usage[name] += usage.get(name, 0) or 0

            reviews.append({"iteration": iteration + 1, "columns": iteration_reviews})
            with open(os.path.join(iteration_dir, "review.json"), "w", encoding="utf-8") as file:
                json.dump(iteration_reviews, file, ensure_ascii=False, indent=2)
            layout["iteration"] = iteration + 1
            with open(layout_file, "w", encoding="utf-8") as file:
                json.dump(layout, file, ensure_ascii=False, indent=2)
            if not changed or all(review.get("status") == "pass" for review in iteration_reviews.values()):
                break
            render_poster_columns(args)
            with open(layout_file, "r", encoding="utf-8") as file:
                layout = json.load(file)
            _save_column_iteration(poster_dir, layout, iteration + 1)

        review_file = os.path.join(poster_dir, "layout_reviews.json")
        with open(review_file, "w", encoding="utf-8") as file:
            json.dump(reviews, file, ensure_ascii=False, indent=2)
        results[paper_id] = reviews
        logger.info("     ✅ Poster columns reviewed: %s | iterations=%d", paper_id, len(reviews))
    return results, total_usage


def review_final_posters(config, args):
    prompt_file = os.path.join("code", "prompt", "en", "poster_final_review.yaml")
    with open(prompt_file, "r", encoding="utf-8") as file:
        prompt_config = yaml.safe_load(file)
    agent = _create_agent(config, prompt_config["system_prompt"])
    template = Template(prompt_config["template"], undefined=StrictUndefined)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    results = {}
    temp_root = os.path.join(args.output_dir, "temp")
    for paper_id in sorted(os.listdir(temp_root)):
        layout_file = os.path.join(temp_root, paper_id, "poster", "poster_layout.json")
        image_file = os.path.join(args.output_dir, "poster", paper_id, "poster.png")
        if not os.path.isfile(layout_file) or not os.path.isfile(image_file):
            continue
        with open(layout_file, "r", encoding="utf-8") as file:
            layout = json.load(file)
        iteration_dir = os.path.join(
            args.output_dir, "poster", paper_id, "iterations", "final_00"
        )
        os.makedirs(iteration_dir, exist_ok=True)
        shutil.copyfile(image_file, os.path.join(iteration_dir, "poster.png"))
        pdf_file = os.path.join(args.output_dir, "poster", paper_id, "poster.pdf")
        if os.path.isfile(pdf_file):
            shutil.copyfile(pdf_file, os.path.join(iteration_dir, "poster.pdf"))
        with open(os.path.join(iteration_dir, "layout.json"), "w", encoding="utf-8") as file:
            json.dump(layout, file, ensure_ascii=False, indent=2)
        prompt = template.render(layout_json=json.dumps(layout, ensure_ascii=False, indent=2))
        response = _call_agent(agent, prompt, image_file, "Poster Final Reviewer")
        result = get_json_from_response(response.msgs[0].content)
        output_file = os.path.join(args.output_dir, "poster", paper_id, "poster_review.json")
        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        with open(os.path.join(iteration_dir, "review.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        usage = response.info.get("usage", {})
        for name in total_usage:
            total_usage[name] += usage.get(name, 0) or 0
        results[paper_id] = result
        logger.info("     ✅ Final poster reviewed: %s | status=%s", paper_id, result.get("status"))
    return results, total_usage
