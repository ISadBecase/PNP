"""直接消费 BatchParser content_lists 的 LightRAG 建库层。"""

import asyncio
import base64
import hashlib
import os
from collections import Counter

from lightrag import LightRAG, QueryParam
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

from utils.retry import retry_async
import logging
import sys

# 列表数据字符串化
def _as_text(value):
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item)
    return str(value or "")


class ContentContextExtractor:
    """按 MinerU 的 page_idx 为图片、表格和公式提供邻近内容。"""
    # TODO:按页作为上下文chunk是否是最合理的选择？
    def __init__(self, content_list, page_window=1):
        self.content_list = content_list
        self.page_window = page_window

    def extract(self, current_item):
        current_page = current_item.get("page_idx")
        parts = []
        for item in self.content_list:
            if not isinstance(item, dict):
                continue
            if abs(item.get("page_idx") - current_page) > self.page_window:
                continue
            content_type = item.get("type", "text")
            if content_type == "text":
                text = _as_text(item.get("text")).strip()
                if text:
                    level = item.get("text_level", 0)
                    parts.append(f"{'#' * level} {text}" if level else text)
            elif content_type == "image":
                caption = _as_text(item.get("image_caption"))
                if caption:
                    parts.append(f"[Image Title] {caption}")
            elif content_type == "table":
                caption = _as_text(item.get("table_caption"))
                if caption:
                    parts.append(f"[Table Title] {caption}")
        return "\n".join(parts)


def content_to_text(content_list):
    parts, multimodal_count = [], 0
    for item in content_list:
        if not isinstance(item, dict):
            continue
        content_type = item.get("type", "text")
        if content_type == "text":
            parts.append(_as_text(item.get("text")))
        elif content_type == "table":
            parts.extend((_as_text(item.get("table_caption")), _as_text(item.get("table_body"))))
        elif content_type == "equation":
            parts.append(_as_text(item.get("text")))
        else:
            multimodal_count += 1
    return "\n\n".join(part for part in parts if part.strip()), multimodal_count


class RAGClient:
    logger = logging.getLogger(__name__)

    def __init__(self, output_dir, config, context_page_window=1):
        self.storage_dir = os.path.join(output_dir, "rag_storage")
        self.context_page_window = context_page_window
        self.rag = None
        self.config = config
        if self.config.embedding.model == "text-embedding-3-small":
            self.embedding_dim = 1536   # OpenAI默认1536
            self.embedding_max_tokens = 8192 # OpenAI默认8192
        elif self.config.embedding.model == "text-embedding-3-large":
            self.embedding_dim = 3072   # OpenAI默认3072
            self.embedding_max_tokens = 8192 # OpenAI默认8192
        else:
            raise ValueError(f"Unsupported embedding model: {self.config.embedding.model}")

        self._vision_model_func = self._create_vision_function()

    # LLM for RAG
    def _create_llm_function(self):
        async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
            return await retry_async(
                lambda: openai_complete_if_cache(
                    self.config.llm.model,
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    api_key=self.config.llm.api_key,
                    base_url=self.config.llm.base_url,
                    **kwargs
                )
            )
        logging.info(f"     ✅ LLM model Created: {self.config.llm.model}")
        return llm_model_func

    # LightRAG 内部调用的Chat Completions API，而非 Responses API
    # 详见：https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create
    def _create_vision_function(self):
        async def vision_model_func(prompt, image_data, system_prompt=None):
            messages = [
                {"role": "system", "content": system_prompt or ""},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        },
                    ],
                },
            ]
            return await retry_async(
                lambda: openai_complete_if_cache(
                    self.config.vlm.model,
                    "",
                    messages=messages,
                    api_key=self.config.vlm.api_key,
                    base_url=self.config.vlm.base_url,
                )
            )
        logging.info(f"     ✅ Vision model Created: {self.config.vlm.model}")
        return vision_model_func

    # 创建文本嵌入函数(包装的OpenAI接口)
    def _create_embedding_function(self):
        async def embed_func(texts, max_token_size=None):
            return await openai_embed.func(
                texts,
                model=self.config.embedding.model,
                api_key=self.config.embedding.api_key,
                base_url=self.config.embedding.base_url,
                max_token_size=max_token_size,
        )
        logging.info(f"     ✅ Embedding model Created: {self.config.embedding.model}")
        return EmbeddingFunc(
            embedding_dim=self.embedding_dim,
            max_token_size=self.embedding_max_tokens,
            model_name=self.config.embedding.model,
            func=embed_func,
        )

    # Initialize the RAGClient.
    async def initialize(self):
        os.makedirs(self.storage_dir, exist_ok=True)
        self.rag = LightRAG(
            working_dir=self.storage_dir,
            llm_model_func=self._create_llm_function(),
            embedding_func=self._create_embedding_function(),
            llm_model_name=self.config.llm.model,
        )
        await self.rag.initialize_storages()
        await initialize_pipeline_status()
        logging.info(f"     ✅ RAGClient initialized with storage_dir.")

    @staticmethod
    def _image_to_base64(image_path):
        if not image_path or not os.path.isfile(image_path):
            raise FileNotFoundError(f" ❌ Image file not found: {image_path}")
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    # 将图片内容块转换为文本描述，并结合上下文信息
    # MinerU的默认图片输出均为JPG格式
    async def _describe_image(self, item, context):
        caption = _as_text(item.get("image_caption"))
        footnote = _as_text(item.get("image_footnote"))
        image_data = self._image_to_base64(item.get("img_path"))
        prompt = (
            "Please describe the key information in the image in English and explain its purpose "
            "in the context of the document.\n"
            f"Caption: {caption or 'None'}\nFootnote: {footnote or 'None'}\nContext: {context or 'None'}"
        )
        try:
            # TODO:这里的system_prompt可能设计的过于粗略
            return await self._vision_model_func(prompt, image_data, system_prompt="You are a multimodal document understanding assistant.")
        except Exception:
            return "\n".join(part for part in (caption, footnote, context) if part)

    @staticmethod
    def _section(title, body, context):
        parts = [f"[{title}]", body.strip()]
        if context.strip():
            parts.append(f"Context: \n{context}")
        return "\n".join(part for part in parts if part)

    # 逐元素(text/image/table/equation)解析
    async def _build_index_text(self, content_list):
        context_extractor = ContentContextExtractor(content_list, page_window=self.context_page_window)
        sections, type_counts = [], Counter()
        for item in content_list:
            if not isinstance(item, dict):
                continue

            content_type = item.get("type", "text")
            if content_type == "text":
                # TODO:是否也应该增加读入页码、标题级信息
                text = _as_text(item.get("text")).strip()
                if text:
                    sections.append(text)
                continue

            # TODO:是否应该在图表返回的解析结果中加入上下文
            context = context_extractor.extract(item)   # 为图表信息提取上下文
            if content_type == "image":
                # TODO:理应控制并发数
                description = (await self._describe_image(item, context)).strip()
                section = self._section("Image", description, context)
            elif content_type == "table":
                body = "\n".join(
                    part
                    for part in (
                        _as_text(item.get("table_caption")),
                        _as_text(item.get("table_body")),
                        _as_text(item.get("table_footnote")),
                    )
                    if part.strip()
                )
                section = self._section("Table", body, context)
            elif content_type == "equation":
                body = _as_text(item.get("text")).strip()
                section = self._section(
                    "Equation",
                    f"Equation (LaTeX):\n{body}",
                    "",
                )
            else:
                # TODO:数据的包容性方面欠妥 https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
                section = self._section(
                    "Extra content",
                    f"Extra content type: {content_type}",
                    context,
                )


            if section.strip():
                sections.append(section)
                type_counts[content_type] += 1
        return "\n\n".join(sections), dict(type_counts)

    # TODO:当前的doc_id可能会因为index_text内容变化而变换，不适合重复开发
    @staticmethod
    def _build_document_id(source_file, index_text):
        source = os.path.abspath(source_file)
        digest = hashlib.md5(f"{source}\n{index_text}".encode("utf-8")).hexdigest()
        return f"doc-{digest}"

    # 将一个文件的内容块转换为索引文本并调用 LightRAG.ainsert()
    async def index_document(self, content_list, source_file, split_by_character=None):
        index_text, multimodal_types = await self._build_index_text(content_list)
        if not index_text.strip():
            raise ValueError(f"     ❌ No indexable content extracted from: {source_file}")


        doc_id = self._build_document_id(source_file, index_text)
        await self.rag.ainsert(
            input=index_text,
            ids=doc_id,
            file_paths=os.path.abspath(source_file),
            split_by_character="\n\n" if split_by_character is None else split_by_character,
            split_by_character_only=False,  # False:兼容考虑max_tokens
        )
        multimodal_indexed = sum(multimodal_types.values())
        return {
            "status": "success",
            "processed": True,
            "doc_id": doc_id,
            "text_length": len(index_text),
            "multimodal_indexed": multimodal_indexed,
            "multimodal_types": multimodal_types,
        }

    # 遍历content_list，批量写入 RAG
    async def index_batch(self, batch_result, split_by_character=None):
        # 获取解析后的内容
        content_lists = batch_result.get("content_lists")
        if content_lists is None:
            raise ValueError(" ❌ Batch_result must contain content_lists from BatchParser")

        results = {}
        for source_file in batch_result.get("successful_files", []):
            logging.info(f"     ⏳ Index before RAG :{os.path.basename(source_file)}...")
            content_list = content_lists.get(source_file)
            if content_list is None:
                logging.info(f"     ❌ Failed Index, Content_list is None: {os.path.basename(source_file)}...")
                results[source_file] = {
                    "status": "failed",
                    "processed": False,
                    "error": " ⚠️ Missing content_list for successful file",
                }
                continue
            try:
                results[source_file] = await self.index_document(content_list, source_file, split_by_character)
                logging.info(f"     ✅ Successfully Index, processed: {os.path.basename(source_file)}")
            except Exception as exc:
                results[source_file] = {
                    "status": "failed",
                    "processed": False,
                    "error": f"❌ {str(exc)}",
                }
                logging.info(f"     ❌ Failed Index, processed: {os.path.basename(source_file)}, error: {str(exc)}")
        return results

    async def query(self, prompt, mode="mix", system_prompt=None, **kwargs):
        if self.rag is None:
            raise RuntimeError("Call await initialize() before querying")
        return await self.rag.aquery(
            prompt,
            param=QueryParam(mode=mode, **kwargs),
            system_prompt=system_prompt,
        )

    # RAG Query
    async def batch_query_by_category(
        self,
        queries_by_category,
        modes_by_category,
        default_mode="mix",
        max_concurrency=2,  # 受限于OPENAI的TPM,我降低并发数8->2
    ):
        semaphore = asyncio.Semaphore(max_concurrency)
        async def query_one(category, index, prompt, mode):
            async with semaphore:
                try:
                    answer = await self.query(prompt, mode=mode)
                    if answer is None:
                        raise RuntimeError("LightRAG 查询未返回回答；请检查建库状态和 LightRAG 日志。")
                    return category, index, {
                        "query": prompt,
                        "answer": answer,
                        "mode": mode,
                        "success": True,
                    }
                except Exception as exc:
                    return category, index, {
                        "query": prompt,
                        "answer": None,
                        "mode": mode,
                        "success": False,
                        "error": str(exc),
                    }

        tasks = []
        for category, prompts in queries_by_category.items():
            mode = modes_by_category.get(category, default_mode)
            tasks.extend(
                query_one(category, index, prompt, mode)
                for index, prompt in enumerate(prompts)
            )

        grouped_results = {category: [] for category in queries_by_category}
        for category, index, result in await asyncio.gather(*tasks):
            grouped_results[category].append((index, result))
        for category in grouped_results:
            grouped_results[category].sort(key=lambda item: item[0])
            grouped_results[category] = [result for _, result in grouped_results[category]]
        return grouped_results

    async def close(self):
        if self.rag is not None:
            await self.rag.finalize_storages()
            self.rag = None


RAGIndexer = RAGClient
