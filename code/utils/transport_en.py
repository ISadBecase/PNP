import hashlib
import json
import os
import logging

from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType

logger = logging.getLogger(__name__)

# 哈希编码+文件内容同步(中->英)
def sync_english_prompts(app_config):
    zh_dir = "./code/prompt/zh"
    en_dir = "./code/prompt/en"
    json_file = "./code/prompt/zh_en.json"

    if os.path.isfile(json_file) and os.path.getsize(json_file):
        with open(json_file, "r", encoding="utf-8") as file:
            hashes = json.load(file)
    else:
        hashes = {}

    changed = []
    for filename in sorted(os.listdir(zh_dir)):
        zh_file = os.path.join(zh_dir, filename)
        en_file = os.path.join(en_dir, filename)
        if not os.path.isfile(zh_file):
            continue

        with open(zh_file, "rb") as file:
            file_hash = hashlib.sha256(file.read()).hexdigest()
        if hashes.get(filename) != file_hash or not os.path.isfile(en_file):
            changed.append((filename, zh_file, en_file, file_hash))

    if not changed:
        return []

    system_prompt = """你是一名专业的提示词本地化翻译助手。
    请将所提供的中文提示词翻译成准确、结构对齐的英文提示词。完整保留文件的结构和格式。
    不要翻译 YAML 或 JSON 键、文件名、诸如{{ variable }} 的 Jinja 表达式、格式占位符、标识符、枚举值、JSON 示例、代码、LaTeX 或 Markdown 语法。仅翻译中文自然语言指令和注释。
    输入信息格式为{Filename: {filename}\n\nFile content:\n{content}}，无额外指令;要求只返回完整的{{content}}的翻译后内容。
    不要使用 Markdown 代码围栏，也不要添加额外的说明。
    """

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=app_config.llm.model,
        model_config_dict={"temperature": 0},
        api_key=app_config.llm.api_key,
        url=app_config.llm.base_url,
    )
    agent = ChatAgent(system_message=system_prompt, model=model)
    translated = []

    logger.info(" 🚀 开始翻译英文提示词...")
    for filename, zh_file, en_file, file_hash in changed:
        with open(zh_file, "r", encoding="utf-8") as file:
            content = file.read()

        if content:
            agent.reset()
            response = agent.step(f"Filename: {filename}\n\nFile content:\n{content}")
            english = response.msgs[0].content
            stripped = english.strip()
            if stripped.startswith("```") and stripped.endswith("```"):
                english = "\n".join(stripped.splitlines()[1:-1])
            if not english.strip():
                raise ValueError(f"Translated prompt is empty: {filename}")
        else:
            english = ""

        with open(en_file, "w", encoding="utf-8") as file:
            file.write(english)
        hashes[filename] = file_hash
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(hashes, file, ensure_ascii=False, indent=2)
        translated.append(filename)
        logger.info(f" ✅ 成功翻译文件: {filename}")

    return translated
