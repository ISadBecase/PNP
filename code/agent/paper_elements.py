import json
import os
import re

def clean_ref(text):
    return re.sub(
        r"\s*\[\s*@[^\s;\[\]]+(?:\s*;\s*@[^\s;\[\]]+)*\s*\]",
        "",
        text,
    ).strip()

def extract_contents(args):
    arxiv_dir = os.path.join(args.output_dir, "arxiv")
    for paper_id in sorted(os.listdir(arxiv_dir)):
        temp_dir = os.path.join(args.output_dir, "temp", paper_id)
        os.makedirs(temp_dir, exist_ok=True)

        paper_json = os.path.join(arxiv_dir, paper_id, "paper.json")

        sections_json = os.path.join(temp_dir, "sections.json")
        extract_sections(paper_json, sections_json)

        figures_json = os.path.join(temp_dir, "figures.json")
        extract_figures(paper_json, figures_json)

        tables_json = os.path.join(temp_dir, "tables.json")
        extract_tables(paper_json, tables_json)

        equations_json = os.path.join(temp_dir, "equations.json")
        extract_equations(paper_json, equations_json)
        print("Extraction complete for:", paper_id)

def extract_sections(paper_json, sections_json):
    with open(paper_json, "r", encoding="utf-8") as file:
        paper = json.load(file)

    result = {
        "title": paper.get("metadata", {}).get("title", ""),
        "abstract": paper.get("metadata", {}).get("abstract", ""),
        "authors": paper.get("metadata", {}).get("authors", []),
        "affiliations": paper.get("metadata", {}).get("affiliations", []),
        "sections": [
            {
                "id": section.get("id", ""),
                "title": section.get("title", ""),
                "text": clean_ref(section.get("text", "")),
                "parent_id": section.get("parent_id"),
                "is_appendix": section.get("is_appendix", False),
            }
            for section in paper.get("sections", [])
        ],
    }
    with open(sections_json, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    return result


def extract_figures(paper_json, figures_json):
    with open(paper_json, "r", encoding="utf-8") as file:
        paper = json.load(file)

    paper_dir = os.path.dirname(paper_json)
    figures = []
    for figure in paper.get("figures", []):
        png_file = os.path.splitext(figure.get("file", ""))[0] + ".png"
        pdf_file = os.path.splitext(figure.get("file", ""))[0] + ".pdf"
        figures.append(
            {
                "id": figure.get("id", ""),
                "caption": figure.get("caption", ""),
                "defined_in": figure.get("defined_in", ""),
                "is_appendix": figure.get("is_appendix", False),
                "png_path": os.path.normpath(os.path.join(paper_dir, png_file)),
                "pdf_path": os.path.normpath(os.path.join(paper_dir, pdf_file)),  # 不一定存在
            }
        )

    with open(figures_json, "w", encoding="utf-8") as file:
        json.dump({"figures": figures}, file, ensure_ascii=False, indent=2)
    return figures


def extract_tables(paper_json, tables_json):
    with open(paper_json, "r", encoding="utf-8") as file:
        paper = json.load(file)

    tables_dir = os.path.dirname(paper_json)
    tables = []
    for table in paper.get("tables", []):
        png_file = os.path.splitext(table.get("file", ""))[0] + ".png"
        tables.append(
            {
                "id": table.get("id", ""),
                "caption": table.get("caption", ""),
                "raw_tex": table.get("raw_tex", ""),
                "defined_in": table.get("defined_in", ""),
                "is_appendix": table.get("is_appendix", False),
                "tex_file": os.path.normpath(os.path.join(tables_dir, table.get("file", ""))),
                "png_file": os.path.normpath(os.path.join(tables_dir, png_file)),
            }
        )

    with open(tables_json, "w", encoding="utf-8") as file:
        json.dump({"tables": tables}, file, ensure_ascii=False, indent=2)
    return tables


def extract_equations(paper_json, equations_json):
    with open(paper_json, "r", encoding="utf-8") as file:
        paper = json.load(file)

    equations_dir = os.path.dirname(paper_json)
    equations = []
    for equation in paper.get("equations", []):
        png_file = os.path.splitext(equation.get("file", ""))[0] + ".png"
        equations.append(
            {
                "id": equation.get("id", ""),
                "description": "",
                "raw_tex": equation.get("raw_tex", ""),
                "defined_in": equation.get("defined_in", ""),
                "is_appendix": equation.get("is_appendix", False),
                "tex_file": os.path.normpath(os.path.join(equations_dir, equation.get("file", ""))),
                "png_file": os.path.normpath(os.path.join(equations_dir, png_file)),
            }
        )

    with open(equations_json, "w", encoding="utf-8") as file:
        json.dump({"equations": equations}, file, ensure_ascii=False, indent=2)
    return equations
