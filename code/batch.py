import logging
import os
import time
import sys
from lark import logger
from tqdm import tqdm
from argparse import Namespace
# from concurrent.futures import ThreadPoolExecutor, as_completed

from parser import IMAGE_FORMATS, OFFICE_FORMATS, TEXT_FORMATS, MineruParser


class BatchParser:
    logger = logging.getLogger(__name__)

    def __init__(self, parser="Mineru", max_workers=4, show_progress=True):
        if parser == "Mineru":
            self.parser = MineruParser()
        else:
            raise ValueError(f"Unsupported parser: {parser}")
        self.max_workers = max_workers
        self.show_progress = show_progress

    # 过滤目录内支持的文件，返回文件列表
    def filter_supported_files(self, source_dir):
        supported_files = set((OFFICE_FORMATS | IMAGE_FORMATS | TEXT_FORMATS | {".pdf"}))
        candidates = (os.path.join(root, name) for root, _, names in os.walk(source_dir) for name in names)
        supported, unsupported = [], []

        for candidate in candidates:
            if os.path.isfile(candidate):
                target = supported if os.path.splitext(candidate)[1].lower() in supported_files else unsupported
                target.append(candidate)

        if supported==[]:
            raise ValueError(" No supported files found.")
        for file in supported:
            logging.info(f"     ✅ Supported file: {os.path.basename(file)}")
        for file in unsupported:
            logging.info(f"     ⚠️ Unsupported file: {os.path.basename(file)}")

        return supported, unsupported, len(supported) + len(unsupported)

    # 单个文件处理入口
    def process_single_file(self, file_path, output_dir):
        try:
            blocks = self.parser.parse_document(file_path=file_path, output_dir=output_dir)
            logging.info(f"     ✅ Processed {os.path.basename(file_path)}, {len(blocks)} blocks")
            return True, file_path, None, blocks
        except Exception as exc:
            logging.error(f"     ❌ Failed to process {os.path.basename(file_path)}: {exc}")
            return False, file_path, exc, None

    # 批量处理入口
    def process_documents_batch(self, source_dir, output_dir):
        started = time.perf_counter()
        logging.info("     ⏳ Check file for supported formats")
        supported, unsupported, total_files = self.filter_supported_files(source_dir)
        successful, failed, errors, content_lists = [], [], {}, {}
        # TODO: 解析文档，并行优化
        logging.info("     ⏳ Starting batch parser for the files")
        for path in supported:
            success, path, error, content_list = self.process_single_file(path, output_dir)
            if success:
                successful.append(path)
                content_lists[path] = content_list
            else:
                failed.append(path)
                errors[path] = str(error or "<Unknown error>")
        result = {
            "total_files": total_files,
            "unsupported_file_count": len(unsupported),
            "successful_file_count": len(successful),
            "failed_file_count": len(failed),
            "unsupported_file_count": len(unsupported),
            "successful_files": successful,                     # 解析成功文件 文件路径列表
            "failed_files": failed,                             # 解析失败文件 文件路径列表
            "unsupported_files": unsupported,                   # 不支持文件格式 文件路径列表
            "content_lists": content_lists,
            "processing_time": time.perf_counter() - started,
            "errors": errors,
            "output_dir": output_dir,
        }
        logging.info(
            " ✅ Batch completed: %d/%d successful in %.2fs",
            result["successful_file_count"], result["total_files"], result["processing_time"],
        )
        return result

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
    )

    args = Namespace(
        source_dir="C:\\Users\\Administrator\\Desktop\\kao\\AGENT\\src\\PNP\\test\\1",
        save_dir="C:\\Users\\Administrator\\Desktop\\kao\\AGENT\\src\\PNP\\test\\2",
    )
    minparser=BatchParser()
    batch_result = minparser.process_documents_batch(source_dir=args.source_dir,output_dir=args.save_dir)