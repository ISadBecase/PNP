"""
    对于 Office 文档（.doc、.docx、.ppt、.pptx)，请先将其转换为 PDF 格式。
    然后使用 MinerU 解析 PDF 和图像文档，并将结果转换为 Markdown 和 JSON 格式。

    需提前下载LibreOffice

    本代码的 MiuerU 默认解析高质量PDF(非扫描版),采用最高质量解析配置,需要约8GB显存
"""

OFFICE_FORMATS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
IMAGE_FORMATS = {".png", ".jpeg", ".jpg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
TEXT_FORMATS = {".txt", ".md"}

# 系统字体设置
WINDOWS_FONTS = {
    "SimHei": r"C:\Windows\Fonts\simhei.ttf",
    "SimSun": r"C:\Windows\Fonts\simsun.ttc",
    "MicrosoftYaHei": r"C:\Windows\Fonts\msyh.ttf",
}
MAC_FONTS = {
    "PingFang": "/System/Library/Fonts/PingFang.ttc",
    "STHeiti": "/System/Library/Fonts/STHeiti Light.ttc",
}

import json
import glob
import os
import re
import time
import subprocess
import tempfile
import logging
import platform
import shutil
import threading
from PIL import Image
from queue import Queue, Empty


from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

class Parser:
    def __init__(self):
        pass

    # 将 Office [.doc、.docx、.ppt、.pptx、.xls、.xlsx] 文档转换为 PDF
    @staticmethod
    def convert_office_to_pdf(doc_path, output_dir):
        doc_name = os.path.splitext(os.path.basename(doc_path))[0]
        output_dir = os.path.join(output_dir,"source_pdf")
        os.makedirs(output_dir, exist_ok=True)

        # 创建 PDF 转换临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            conversion_successful = False
            # libreoffice --headless --convert-to <目标格式> --outdir <输出目录> <文件>
            convert_cmd = ["soffice","--headless","--convert-to","pdf","--outdir",temp_dir,doc_path]


            result = subprocess.run(
                convert_cmd,
                capture_output=True,    # 捕获输出
                text=True,              # 字符串形式输出
                timeout=120,             # 限制最长运行时间
                encoding="utf-8",       # 输出编码格式
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0  # windows隐藏命令窗口
            )

            if result.returncode == 0:
                conversion_successful = True
            if not conversion_successful:
                raise RuntimeError(f"LibreOffice conversion failed for {os.path.basename(doc_path)}. ")

            pdf_path = os.path.join(temp_dir, f"{doc_name}.pdf")                                    # 生成验证
            if not os.path.exists(pdf_path):
                raise RuntimeError(f"     ❌ Cant find {os.path.basename(doc_path)} in temp-dir")
            if os.path.getsize(pdf_path) < 10:                                                      # 文件极小，可能为空 B
                raise RuntimeError("     ❌ Generated PDF appears to be empty or corrupted.")

            # 将 PDF 复制到最终输出目录
            final_pdf_path = os.path.join(output_dir, f"{doc_name}.pdf")
            shutil.copy2(pdf_path, final_pdf_path)
            logging.info(f"     ✅ Converted {os.path.basename(doc_path)} to PDF ({os.path.getsize(final_pdf_path)/1024:.1f} KB)")

        return final_pdf_path

    # 将 Txt [.txt 、.md] 文档转换为 PDF
    @staticmethod
    def convert_text_to_pdf(text_path, output_dir):
        supported_text_formats = {".txt", ".md"}
        text_suffix = os.path.splitext(text_path)[1].lower()
        if text_suffix not in supported_text_formats:
            raise ValueError(f"Unsupported text format: {text_suffix}")

        # 读取文本内容
        for encoding in ["utf-8", "gbk"]:
            try:
                with open(text_path, "r", encoding=encoding) as f:
                    text_content = f.read()
                break
            except UnicodeDecodeError as e:
                last_error = e

        if text_content is None:
            raise RuntimeError(f"无法解码文本文件：{text_path}") from last_error

        # 设置PDF字体
        font_name = None
        system = platform.system()
        if system == "Linux":
            font_name = "WenQuanYi"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                font_path = "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc"
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                else:
                    raise RuntimeError(f"Font file not found: {font_path}")
        elif system == "Windows":
            for name, path in WINDOWS_FONTS.items():
                if os.path.exists(path):
                    font_name = name
                    pdfmetrics.registerFont(TTFont(name, path))
                    break
        elif system == "Darwin":
            for name, path in MAC_FONTS.items():
                if os.path.exists(path):
                    font_name = name
                    pdfmetrics.registerFont(TTFont(name, path))
                    break
        if not font_name:
            raise RuntimeError("No suitable font found.")

        # 创建 PDF 文档
        text_stem = os.path.splitext(os.path.basename(text_path))[0]
        pdf_path = os.path.join(output_dir, f"{text_stem}.pdf")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=inch,
            rightMargin=inch,
            topMargin=inch,
            bottomMargin=inch,
        )

        # 获取样式
        styles = getSampleStyleSheet()
        normal_style = styles["Normal"]
        heading_style = styles["Heading1"]
        normal_style.fontName = font_name
        heading_style.fontName = font_name


        # 构建文档内容
        story = []

        # 处理 Markdown
        if text_suffix == ".md":
            lines = text_content.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 12))
                    continue

                # 标题
                if line.startswith("#"):
                    level = len(line) - len(line.lstrip("#"))
                    header_text = line.lstrip("#").strip()
                    if header_text:
                        header_style = ParagraphStyle(
                            name=f"Heading{level}",
                            parent=heading_style,
                            fontSize=max(16 - level, 10),
                            spaceAfter=8,
                            spaceBefore=16 if level <= 2 else 12,
                        )
                        story.append(Paragraph(header_text, header_style))
                else:
                    # 普通文本
                    story.append(Paragraph(line, normal_style))
                    story.append(Spacer(1, 6))
        # 处理纯文本文件（.txt）
        else:
            # 将文本拆分为多行并逐行处理
            lines = text_content.split("\n")
            line_count = 0

            for line in lines:
                line = line.rstrip()
                line_count += 1

                # 空行
                if not line.strip():
                    story.append(Spacer(1, 6))
                    continue

                # 普通文本行 转义 ReportLab 的特殊字符
                safe_line = (
                    line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

                # 创建段落
                story.append(Paragraph(safe_line, normal_style))
                story.append(Spacer(1, 3))

        # 若未添加内容，则添加占位符
        if not story:
            story.append(Paragraph("(Empty text file)", normal_style))

        # 生成 PDF
        doc.build(story)
        logging.info(f"     ✅ Converted {os.path.basename(text_path)} to PDF ({os.path.getsize(pdf_path)/1024:.1f} KB)")
        return pdf_path

    # 将Markdown文本中的行内格式转换为ReportLab可识别的格式
    @staticmethod
    def _process_inline_markdown(text):
        # & < >
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 粗体
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.*?)__", r"<b>\1</b>", text)

        # 斜体
        text = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

        # 代码小块
        text = re.sub(
            r"`([^`]+?)`",
            r'<font name="Courier" size="9" color="darkred">\1</font>',
            text,
        )

        # 超链接
        def link_replacer(match):
            link_text = match.group(1)
            url = match.group(2)
            return f'<link href="{url}" color="blue"><u>{link_text}</u></link>'
        text = re.sub(r"\[([^\]]+?)\]\(([^)]+?)\)", link_replacer, text)

        # 删除线
        text = re.sub(r"~~(.*?)~~", r"<strike>\1</strike>", text)

        return text

class MineruParser(Parser):
    def __init__(self):
        super().__init__()

    # MinerU CMD 运行函数
    # https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/cli_tools.md
    # https://opendatalab.github.io/MinerU/quick_start/?utm_source=chatgpt.com#local-deployment
    @staticmethod
    def _run_mineru_command(
        input_path,
        output_dir,
        method="auto",  # auto ,ocr ,txt
        backend=None,   # 解析引擎
        effort=None,
        image_analysis=None,
        source=None,    # 模型来源
        vlm_url=None,   # 当 backend 使用 vlm-sglang-client 时，需要指定模型服务器地址。
    ):
        cmd = [
            "mineru",
            "-p",str(input_path),
            "-o",str(output_dir),
            "-m",method
        ]

        if backend:
            cmd.extend(["-b", backend])
        if source:
            cmd.extend(["--source", source])
        if vlm_url:
            cmd.extend(["-u", vlm_url])
        if effort:
            cmd.extend(["--effort", effort])
        if image_analysis is not None:
            cmd.extend(["--image-analysis", "true" if image_analysis else "false"])
        # logging.info(f"     ⏳ 执行 MinerU CLI命令: {' '.join(cmd)}")

        def enqueue_output(pipe, queue):
            try:
                for line in iter(pipe.readline, ""):
                    if line.strip():
                        queue.put(line.strip())
            finally:
                pipe.close()

        # 启动外部程序
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, # 将控制台输出转为Python管道
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,              # Line buffered
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )

        output_queue  = Queue()
        output_thread = threading.Thread(target=enqueue_output,args=(process.stdout, output_queue),daemon=True)

        output_thread.start()
        while process.poll() is None or not output_queue.empty():
            try:
                while True:
                    line = output_queue.get_nowait()
                    # logging.info("[MinerU] %s", line)
            except Empty:
                pass
            time.sleep(0.05)


        # 等待线程结束强制停止
        output_thread.join(timeout=3)
        return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f" ❌ MinerU 命令执行失败，退出码：{return_code}")
        # logging.info(f" ✅ MinerU 命令执行成功,文件转换:{os.path.basename(input_path)} -> {output_dir}")

    @staticmethod
    def _read_output_files(output_dir, file_stem, backend_name):
        md_file = os.path.join(output_dir, file_stem, backend_name, f"{file_stem}.md")
        #TODO: MinerU 的 {file_stem}_content_list_v2.json的信息可能更丰富，后续可以改进接口
        json_file = os.path.join(output_dir, file_stem, backend_name, f"{file_stem}_content_list.json")

        # 读取Markdown
        md_content = ""
        if os.path.exists(md_file):
            with open(md_file, "r", encoding="utf-8") as f:
                md_content = f.read()

        # 读取JSON内容列表
        content_list = []
        if os.path.exists(json_file):
            with open(json_file, "r", encoding="utf-8") as f:
                content_list = json.load(f)

            # 将图表等相对路径转换为绝对路径
            for item in content_list:
                if isinstance(item, dict):
                    for field_name in ["img_path","table_img_path","equation_img_path"]:
                        if field_name in item and item[field_name]:
                            img_path = item[field_name]
                            item[field_name] = os.path.abspath(os.path.join(output_dir, file_stem, backend_name, img_path))
                            # logging.debug(f"Updated absolute path: {field_name}: {img_path} -> {item[field_name]}")

        return content_list, md_content

    def parse_pdf(self,pdf_path,output_dir=None,method="auto",backend="hybrid-engine",effort="high"):
        name_without_suff = os.path.splitext(os.path.basename(pdf_path))[0]
        # 执行Mineru
        self._run_mineru_command(
            input_path=pdf_path,
            output_dir=output_dir,
            method=method,
            backend=backend,
            effort=effort,                # Only for hybrid-engine
            image_analysis=True,          # Hybrid medium effort automatically disables image/chart analysis (default: enabled)
            source=None,
            vlm_url=None,
        )

        if backend.startswith("vlm"):
            parse_dir_name = "vlm"
        elif backend.startswith("hybrid"):
            parse_dir_name = f"hybrid_{method}"
        elif backend.startswith("pipeline"):
            parse_dir_name = method
        else:
            raise ValueError(f"Unsupported backend: {backend}")

        content_list, _ = self._read_output_files(output_dir, name_without_suff, parse_dir_name)

        return content_list

    # TODO:对于图片格式解析，采用纯VLM会不会更好
    def parse_image(self, image_path, output_dir=None, method="ocr", backend="vlm-engine"):
        try:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file does not exist: {image_path}")
            output_dir=os.path.join(output_dir, "image")
            os.makedirs(output_dir, exist_ok=True)

            ext = os.path.splitext(image_path)[1].lower()
            mineru_supported_formats = {".png", ".jpeg", ".jpg"}

            # Determine the actual image file to process
            actual_image_path = None
            temp_converted_file = None
            temp_dir = None

            # Use Pillow to convert MinerU unsupported image formats
            if ext not in mineru_supported_formats:
                temp_dir = tempfile.mkdtemp()
                filename = os.path.splitext(os.path.basename(image_path))[0]
                temp_converted_file = os.path.join(temp_dir,f"{filename}_converted.png")

                with Image.open(image_path) as img:
                    if img.mode in ("RGBA", "LA", "P"):
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "RGBA":
                            background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
                        else:
                            background.paste(img)
                        img = background
                    elif img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")

                    # Save as PNG
                    img.save(temp_converted_file, "PNG", optimize=True)
                    logging.info(
                        f"     ✅ Successfully converted image to PNG "
                        f"({os.path.getsize(temp_converted_file)/1024:.1f} KB)"
                    )
                    actual_image_path = temp_converted_file


            name_without_suff = os.path.splitext(os.path.basename(image_path))[0]

            # Run mineru command (images are processed with OCR method)
            self._run_mineru_command(
                input_path=actual_image_path,
                output_dir=output_dir,
                method=method,                   # 使用OCR识别
                lang=None,
                backend=backend,
                source=None,
                # vlm_url=vlm_url,
            )

            if backend.startswith("vlm"):
                parse_dir_name = "vlm"
            elif backend.startswith("hybrid"):
                parse_dir_name = f"hybrid_{method}"
            elif backend.startswith("pipeline"):
                parse_dir_name = method
            else:
                raise ValueError(f"Unsupported backend: {backend}")

            content_list, _ = self._read_output_files(output_dir, name_without_suff, parse_dir_name)
            return content_list

        except Exception as e:
            raise ValueError(f"     ❌ Failed to parse image {image_path}: {e}") from e

        finally:
            if temp_converted_file and os.path.exists(temp_converted_file):
                try:
                    os.remove(temp_converted_file)
                    os.rmdir(os.path.dirname(temp_converted_file))
                except Exception:
                    pass

    # 入口
    def parse_document(self, file_path, output_dir=None):
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir)
        elif ext in IMAGE_FORMATS:
            return self.parse_image(file_path, output_dir)
        elif ext in OFFICE_FORMATS:
            pdf_path = self.convert_office_to_pdf(file_path, output_dir)                                # Convert Office document to PDF
            return self.parse_pdf(pdf_path, output_dir)
        elif ext in TEXT_FORMATS:
            pdf_path = self.convert_text_to_pdf(file_path, output_dir)                                  # Convert text to PDF
            return self.parse_pdf(pdf_path, output_dir)
        else:
            raise RuntimeError(f"    ❌ Unsupported file extension for {file_path} with '{ext}' ")


# class DoclingParser(Parser):
#     """
#     Docling document parsing utility class.

#     Specialized in parsing Office documents and HTML files, converting the content
#     into structured data and generating markdown and JSON output.
#     """

#     # Define Docling-specific formats
#     HTML_FORMATS = {".html", ".htm", ".xhtml"}

#     def __init__(self) -> None:
#         """Initialize DoclingParser"""
#         super().__init__()

#     def parse_pdf(
#         self,
#         pdf_path: Union[str, Path],
#         output_dir: Optional[str] = None,
#         method: str = "auto",
#         lang: Optional[str] = None,
#         **kwargs,
#     ) -> List[Dict[str, Any]]:
#         """
#         Parse PDF document using Docling

#         Args:
#             pdf_path: Path to the PDF file
#             output_dir: Output directory path
#             method: Parsing method (auto, txt, ocr)
#             lang: Document language for OCR optimization
#             **kwargs: Additional parameters for docling command

#         Returns:
#             List[Dict[str, Any]]: List of content blocks
#         """
#         try:
#             # Convert to Path object for easier handling
#             pdf_path = Path(pdf_path)
#             if not pdf_path.exists():
#                 raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

#             name_without_suff = pdf_path.stem

#             # Prepare output directory
#             if output_dir:
#                 base_output_dir = Path(output_dir)
#             else:
#                 base_output_dir = pdf_path.parent / "docling_output"

#             base_output_dir.mkdir(parents=True, exist_ok=True)

#             # Run docling command
#             self._run_docling_command(
#                 input_path=pdf_path,
#                 output_dir=base_output_dir,
#                 file_stem=name_without_suff,
#                 **kwargs,
#             )

#             # Read the generated output files
#             content_list, _ = self._read_output_files(
#                 base_output_dir, name_without_suff
#             )
#             return content_list

#         except Exception as e:
#             logging.error(f"Error in parse_pdf: {str(e)}")
#             raise

#     # 根据文件类型，使用 Docling 解析文档
#     def parse_document(
#         self,
#         file_path: Union[str, Path],
#         method: str = "auto",
#         output_dir: Optional[str] = None,
#         lang: Optional[str] = None,
#         **kwargs,
#     ) -> List[Dict[str, Any]]:
#         # 文件路径
#         file_path = Path(file_path)
#         if not file_path.exists():
#             raise FileNotFoundError(f"File does not exist: {file_path}")
#         ext = file_path.suffix.lower()

#         # 基于文件类型选择解析器
#         if ext == ".pdf":
#             return self.parse_pdf(file_path, output_dir, method, lang, **kwargs)
#         elif ext in self.OFFICE_FORMATS:
#             return self.parse_office_doc(file_path, output_dir, lang, **kwargs)
#         elif ext in self.HTML_FORMATS:
#             return self.parse_html(file_path, output_dir, lang, **kwargs)
#         else:
#             raise ValueError(
#                 f"Unsupported file format: {ext}. "
#                 f"Docling only supports PDF files, Office formats ({', '.join(self.OFFICE_FORMATS)}) "
#                 f"and HTML formats ({', '.join(self.HTML_FORMATS)})"
#             )

#     def _run_docling_command(
#         self,
#         input_path: Union[str, Path],
#         output_dir: Union[str, Path],
#         file_stem: str,
#         **kwargs,
#     ) -> None:
#         """
#         Run docling command line tool

#         Args:
#             input_path: Path to input file or directory
#             output_dir: Output directory path
#             file_stem: File stem for creating subdirectory
#             **kwargs: Additional parameters for docling command
#         """
#         # Create subdirectory structure similar to MinerU
#         file_output_dir = Path(output_dir) / file_stem / "docling"
#         file_output_dir.mkdir(parents=True, exist_ok=True)

#         cmd_json = [
#             "docling",
#             "--output",
#             str(file_output_dir),
#             "--to",
#             "json",
#             str(input_path),
#         ]
#         cmd_md = [
#             "docling",
#             "--output",
#             str(file_output_dir),
#             "--to",
#             "md",
#             str(input_path),
#         ]

#         try:
#             # Prepare subprocess parameters to hide console window on Windows
#             import platform

#             docling_subprocess_kwargs = {
#                 "capture_output": True,
#                 "text": True,
#                 "check": True,
#                 "encoding": "utf-8",
#                 "errors": "ignore",
#             }

#             # Hide console window on Windows
#             if platform.system() == "Windows":
#                 docling_subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

#             result_json = subprocess.run(cmd_json, **docling_subprocess_kwargs)
#             result_md = subprocess.run(cmd_md, **docling_subprocess_kwargs)
#             logging.info("Docling command executed successfully")
#             if result_json.stdout:
#                 logging.debug(f"JSON cmd output: {result_json.stdout}")
#             if result_md.stdout:
#                 logging.debug(f"Markdown cmd output: {result_md.stdout}")
#         except subprocess.CalledProcessError as e:
#             logging.error(f"Error running docling command: {e}")
#             if e.stderr:
#                 logging.error(f"Error details: {e.stderr}")
#             raise
#         except FileNotFoundError:
#             raise RuntimeError(
#                 "docling command not found. Please ensure Docling is properly installed."
#             )

#     def _read_output_files(
#         self,
#         output_dir: Path,
#         file_stem: str,
#     ) -> Tuple[List[Dict[str, Any]], str]:
#         """
#         Read the output files generated by docling and convert to MinerU format

#         Args:
#             output_dir: Output directory
#             file_stem: File name without extension

#         Returns:
#             Tuple containing (content list JSON, Markdown text)
#         """
#         # Use subdirectory structure similar to MinerU
#         file_subdir = output_dir / file_stem / "docling"
#         md_file = file_subdir / f"{file_stem}.md"
#         json_file = file_subdir / f"{file_stem}.json"

#         # Read markdown content
#         md_content = ""
#         if md_file.exists():
#             try:
#                 with open(md_file, "r", encoding="utf-8") as f:
#                     md_content = f.read()
#             except Exception as e:
#                 logging.warning(f"Could not read markdown file {md_file}: {e}")

#         # Read JSON content and convert format
#         content_list = []
#         if json_file.exists():
#             try:
#                 with open(json_file, "r", encoding="utf-8") as f:
#                     docling_content = json.load(f)
#                     # Convert docling format to minerU format
#                     content_list = self.read_from_block_recursive(
#                         docling_content["body"],
#                         "body",
#                         file_subdir,
#                         0,
#                         "0",
#                         docling_content,
#                     )
#             except Exception as e:
#                 logging.warning(f"Could not read or convert JSON file {json_file}: {e}")
#         return content_list, md_content

#     def read_from_block_recursive(
#         self,
#         block,
# type: str,
#         output_dir: Path,
#         cnt: int,
#         num: str,
#         docling_content: Dict[str, Any],
#     ) -> List[Dict[str, Any]]:
#         content_list = []
#         if not block.get("children"):
#             cnt += 1
#             content_list.append(self.read_from_block(block, type, output_dir, cnt, num))
#         else:
#             if type not in ["groups", "body"]:
#                 cnt += 1
#                 content_list.append(
#                     self.read_from_block(block, type, output_dir, cnt, num)
#                 )
#             members = block["children"]
#             for member in members:
#                 cnt += 1
#                 member_tag = member["$ref"]
#                 member_type = member_tag.split("/")[1]
#                 member_num = member_tag.split("/")[2]
#                 member_block = docling_content[member_type][int(member_num)]
#                 content_list.extend(
#                     self.read_from_block_recursive(
#                         member_block,
#                         member_type,
#                         output_dir,
#                         cnt,
#                         member_num,
#                         docling_content,
#                     )
#                 )
#         return content_list

#     def read_from_block(
#         self, block, type: str, output_dir: Path, cnt: int, num: str
#     ) -> Dict[str, Any]:
#         if type == "texts":
#             if block["label"] == "formula":
#                 return {
#                     "type": "equation",
#                     "img_path": "",
#                     "text": block["orig"],
#                     "text_format": "unknown",
#                     "page_idx": cnt // 10,
#                 }
#             else:
#                 return {
#                     "type": "text",
#                     "text": block["orig"],
#                     "page_idx": cnt // 10,
#                 }
#         elif type == "pictures":
#             try:
#                 base64_uri = block["image"]["uri"]
#                 base64_str = base64_uri.split(",")[1]
#                 # Create images directory within the docling subdirectory
#                 image_dir = output_dir / "images"
#                 image_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
#                 image_path = image_dir / f"image_{num}.png"
#                 with open(image_path, "wb") as f:
#                     f.write(base64.b64decode(base64_str))
#                 return {
#                     "type": "image",
#                     "img_path": str(image_path.resolve()),  # Convert to absolute path
#                     "image_caption": block.get("caption", ""),
#                     "image_footnote": block.get("footnote", ""),
#                     "page_idx": cnt // 10,
#                 }
#             except Exception as e:
#                 logging.warning(f"Failed to process image {num}: {e}")
#                 return {
#                     "type": "text",
#                     "text": f"[Image processing failed: {block.get('caption', '')}]",
#                     "page_idx": cnt // 10,
#                 }
#         else:
#             try:
#                 return {
#                     "type": "table",
#                     "img_path": "",
#                     "table_caption": block.get("caption", ""),
#                     "table_footnote": block.get("footnote", ""),
#                     "table_body": block.get("data", []),
#                     "page_idx": cnt // 10,
#                 }
#             except Exception as e:
#                 logging.warning(f"Failed to process table {num}: {e}")
#                 return {
#                     "type": "text",
#                     "text": f"[Table processing failed: {block.get('caption', '')}]",
#                     "page_idx": cnt // 10,
#                 }

#     def parse_office_doc(
#         self,
#         doc_path: Union[str, Path],
#         output_dir: Optional[str] = None,
#         lang: Optional[str] = None,
#         **kwargs,
#     ) -> List[Dict[str, Any]]:
#         """
#         Parse office document directly using Docling

#         Supported formats: .doc, .docx, .ppt, .pptx, .xls, .xlsx

#         Args:
#             doc_path: Path to the document file
#             output_dir: Output directory path
#             lang: Document language for optimization
#             **kwargs: Additional parameters for docling command

#         Returns:
#             List[Dict[str, Any]]: List of content blocks
#         """
#         try:
#             # Convert to Path object
#             doc_path = Path(doc_path)
#             if not doc_path.exists():
#                 raise FileNotFoundError(f"Document file does not exist: {doc_path}")

#             if doc_path.suffix.lower() not in self.OFFICE_FORMATS:
#                 raise ValueError(f"Unsupported office format: {doc_path.suffix}")

#             name_without_suff = doc_path.stem

#             # Prepare output directory
#             if output_dir:
#                 base_output_dir = Path(output_dir)
#             else:
#                 base_output_dir = doc_path.parent / "docling_output"

#             base_output_dir.mkdir(parents=True, exist_ok=True)

#             # Run docling command
#             self._run_docling_command(
#                 input_path=doc_path,
#                 output_dir=base_output_dir,
#                 file_stem=name_without_suff,
#                 **kwargs,
#             )

#             # Read the generated output files
#             content_list, _ = self._read_output_files(
#                 base_output_dir, name_without_suff
#             )
#             return content_list

#         except Exception as e:
#             logging.error(f"Error in parse_office_doc: {str(e)}")
#             raise

#     def parse_html(
#         self,
#         html_path: Union[str, Path],
#         output_dir: Optional[str] = None,
#         lang: Optional[str] = None,
#         **kwargs,
#     ) -> List[Dict[str, Any]]:
#         """
#         Parse HTML document using Docling

#         Supported formats: .html, .htm, .xhtml

#         Args:
#             html_path: Path to the HTML file
#             output_dir: Output directory path
#             lang: Document language for optimization
#             **kwargs: Additional parameters for docling command

#         Returns:
#             List[Dict[str, Any]]: List of content blocks
#         """
#         try:
#             # Convert to Path object
#             html_path = Path(html_path)
#             if not html_path.exists():
#                 raise FileNotFoundError(f"HTML file does not exist: {html_path}")

#             if html_path.suffix.lower() not in self.HTML_FORMATS:
#                 raise ValueError(f"Unsupported HTML format: {html_path.suffix}")

#             name_without_suff = html_path.stem

#             # Prepare output directory
#             if output_dir:
#                 base_output_dir = Path(output_dir)
#             else:
#                 base_output_dir = html_path.parent / "docling_output"

#             base_output_dir.mkdir(parents=True, exist_ok=True)

#             # Run docling command
#             self._run_docling_command(
#                 input_path=html_path,
#                 output_dir=base_output_dir,
#                 file_stem=name_without_suff,
#                 **kwargs,
#             )

#             # Read the generated output files
#             content_list, _ = self._read_output_files(
#                 base_output_dir, name_without_suff
#             )
#             return content_list

#         except Exception as e:
#             logging.error(f"Error in parse_html: {str(e)}")
#             raise

#     def check_installation(self) -> bool:
#         """
#         Check if Docling is properly installed

#         Returns:
#             bool: True if installation is valid, False otherwise
#         """
#         try:
#             # Prepare subprocess parameters to hide console window on Windows
#             import platform

#             subprocess_kwargs = {
#                 "capture_output": True,
#                 "text": True,
#                 "check": True,
#                 "encoding": "utf-8",
#                 "errors": "ignore",
#             }

#             # Hide console window on Windows
#             if platform.system() == "Windows":
#                 subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

#             result = subprocess.run(["docling", "--version"], **subprocess_kwargs)
#             logging.debug(f"Docling version: {result.stdout.strip()}")
#             return True
#         except (subprocess.CalledProcessError, FileNotFoundError):
#             logging.debug(
#                 "Docling is not properly installed. "
#                 "Please ensure it is installed correctly."
#             )
#             return False


# def main():
#     """
#     Main function to run the document parser from command line
#     """
#     parser = argparse.ArgumentParser(
#         description="Parse documents using MinerU 2.0 or Docling"
#     )
#     parser.add_argument("file_path", help="Path to the document to parse")
#     parser.add_argument("--output", "-o", help="Output directory path")
#     parser.add_argument(
#         "--method",
#         "-m",
#         choices=["auto", "txt", "ocr"],
#         default="auto",
#         help="Parsing method (auto, txt, ocr)",
#     )
#     parser.add_argument(
#         "--lang",
#         "-l",
#         help="Document language for OCR optimization (e.g., ch, en, ja)",
#     )
#     parser.add_argument(
#         "--backend",
#         "-b",
#         choices=[
#             "pipeline",
#             "vlm-transformers",
#             "vlm-sglang-engine",
#             "vlm-sglang-client",
#         ],
#         default="pipeline",
#         help="Parsing backend",
#     )
#     parser.add_argument(
#         "--device",
#         "-d",
#         help="Inference device (e.g., cpu, cuda, cuda:0, npu, mps)",
#     )
#     parser.add_argument(
#         "--source",
#         choices=["huggingface", "modelscope", "local"],
#         default="huggingface",
#         help="Model source",
#     )
#     parser.add_argument(
#         "--no-formula",
#         action="store_true",
#         help="Disable formula parsing",
#     )
#     parser.add_argument(
#         "--no-table",
#         action="store_true",
#         help="Disable table parsing",
#     )
#     parser.add_argument(
#         "--stats", action="store_true", help="Display content statistics"
#     )
#     parser.add_argument(
#         "--check",
#         action="store_true",
#         help="Check parser installation",
#     )
#     parser.add_argument(
#         "--parser",
#         choices=["mineru", "docling"],
#         default="mineru",
#         help="Parser selection",
#     )
#     parser.add_argument(
#         "--vlm_url",
#         help="When the backend is `vlm-sglang-client`, you need to specify the server_url, for example:`http://127.0.0.1:30000`",
#     )

#     args = parser.parse_args()

#     # Check installation if requested
#     if args.check:
#         doc_parser = DoclingParser() if args.parser == "docling" else MineruParser()
#         if doc_parser.check_installation():
#             print(f"✅ {args.parser.title()} is properly installed")
#             return 0
#         else:
#             print(f"❌ {args.parser.title()} installation check failed")
#             return 1

#     try:
#         # Parse the document
#         doc_parser = DoclingParser() if args.parser == "docling" else MineruParser()
#         content_list = doc_parser.parse_document(
#             file_path=args.file_path,
#             method=args.method,
#             output_dir=args.output,
#             lang=args.lang,
#             backend=args.backend,
#             device=args.device,
#             source=args.source,
#             formula=not args.no_formula,
#             table=not args.no_table,
#             vlm_url=args.vlm_url,
#         )

#         print(f"✅ Successfully parsed: {args.file_path}")
#         print(f"📊 Extracted {len(content_list)} content blocks")

#         # Display statistics if requested
#         if args.stats:
#             print("\n📈 Document Statistics:")
#             print(f"Total content blocks: {len(content_list)}")

#             # Count different types of content
#             content_types = {}
#             for item in content_list:
#                 if isinstance(item, dict):
#                     content_type = item.get("type", "unknown")
#                     content_types[content_type] = content_types.get(content_type, 0) + 1

#             if content_types:
#                 print("\n📋 Content Type Distribution:")
#                 for content_type, count in sorted(content_types.items()):
#                     print(f"  • {content_type}: {count}")

#     except Exception as e:
#         print(f"❌ Error: {str(e)}")
#         return 1

#     return 0


# if __name__ == "__main__":
#     exit(main())
