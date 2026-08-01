from dataclasses import dataclass
from dotenv import load_dotenv
import os

@dataclass(frozen=True)
class ModelConfig:
    model: str
    api_key: str
    base_url: str

@dataclass(frozen=True)
class ImageGenConfig:
    model: str
    api_key: str
    base_url: str
    response_mime_type: str

@dataclass(frozen=True)
class AppConfig:
    llm: ModelConfig
    vlm: ModelConfig
    embedding: ModelConfig
    image_gen: ImageGenConfig
    plan_max_tokens: int

def load_app_config():
    load_dotenv()

    return AppConfig(
        llm=ModelConfig(
            model=os.environ["LLM_MODEL"],
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_BASE_URL"],
        ),
        vlm=ModelConfig(
            model=os.environ["VLM_MODEL"],
            api_key=os.environ["VLM_API_KEY"],
            base_url=os.environ["VLM_BASE_URL"],
        ),
        embedding=ModelConfig(
            model=os.environ["EMBEDDING_MODEL"],
            api_key=os.environ["EMBEDDING_API_KEY"],
            base_url=os.environ["EMBEDDING_BASE_URL"],
        ),
        image_gen=ImageGenConfig(
            model=os.environ["IMAGE_GEN_MODEL"],
            api_key=os.environ["IMAGE_GEN_API_KEY"],
            base_url=os.environ["IMAGE_GEN_BASE_URL"],
            response_mime_type=os.environ["IMAGE_GEN_RESPONSE_MIME_TYPE"],
        ),
        plan_max_tokens=int(os.environ["PLAN_MAX_TOKENS"]),
    )