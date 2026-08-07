import json
import os


def create_content_list(args):
    temp_root = os.path.join(args.output_dir, "temp")
    results = {}

    for paper_id in sorted(os.listdir(temp_root)):
        paper_dir = os.path.join(temp_root, paper_id)
        if not os.path.isdir(paper_dir):
            continue

        sections_json = os.path.join(paper_dir, "sections.json")
        figures_json = os.path.join(paper_dir, "figures.json")
        tables_json = os.path.join(paper_dir, "tables.json")
        equations_json = os.path.join(paper_dir, "equations.json")

        with open(sections_json, "r", encoding="utf-8") as file:
            section_data = json.load(file)
        with open(figures_json, "r", encoding="utf-8") as file:
            figures = json.load(file)["figures"]
        with open(tables_json, "r", encoding="utf-8") as file:
            tables = json.load(file)["tables"]
        with open(equations_json, "r", encoding="utf-8") as file:
            equations = json.load(file)["equations"]

        title = section_data["title"]
        sections = section_data["sections"]
        content_list = []
        current = None
        figure_index = 0
        table_index = 0
        equation_index = 0

        for section in sections:
            section_id = section["id"]
            level = section_id.count(".")

            if level == 0:
                if current:
                    current["index_text"] = "\n\n".join(current["index_text"])
                    content_list.append(current)

                current = {
                    "doc_id": f"{paper_id}__section__{section_id.replace(':', '_')}",
                    "content_type": "section_group",
                    "section_id": section_id,
                    "section_title": section["title"],
                    "section_ids": [],
                    "asset_ids": [],
                    "source_file": sections_json,
                    "index_text": [],
                }

            heading = "#" * min(level + 1, 6)
            current["section_ids"].append(section_id)
            current["index_text"].append(
                f"{heading} {section.get('title', '')}\n\n\n{section.get('text', '')}".strip()
            )

            while figure_index < len(figures) and figures[figure_index].get("defined_in") == section_id:
                figure = figures[figure_index]
                current["asset_ids"].append(figure.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Figure]:",
                            f"{figure['id']} Caption: {figure.get('caption', '')}",
                            f"{figure['id']} Description: {figure.get('description', '')}",
                        ]
                    )
                )
                figure_index += 1

            while table_index < len(tables) and tables[table_index].get("defined_in") == section_id:
                table = tables[table_index]
                current["asset_ids"].append(table.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Table]:",
                            f"{table['id']} Caption: {table.get('caption', '')}",
                            f"{table['id']} Description as: {table.get('description', '')}",
                        ]
                    )
                )
                table_index += 1

            while equation_index < len(equations) and equations[equation_index].get("defined_in") == section_id:
                equation = equations[equation_index]
                current["asset_ids"].append(equation.get("id", ""))
                current["index_text"].append(
                    "\n".join(
                        [
                            f"[Equation]:",
                            f"{equation['id']} LaTeX Format: {equation['raw_tex']}",
                            f"{equation['id']} Description as: {equation.get('description', '')}",
                        ]
                    )
                )
                equation_index += 1

        if current:
            current["index_text"] = "\n\n".join(current["index_text"])
            content_list.append(current)

        result = {
            "paper_id": paper_id,
            "title": title,
            "content_list": content_list,
        }

        # 导出直观的中间文件 JSON & MARKDOWN
        rag_sections_dir = os.path.join(paper_dir, "rag_sections")
        os.makedirs(rag_sections_dir, exist_ok=True)
        for section in content_list:
            section_name = section["section_id"].replace(":", "_")
            section_result = {
                "paper_id": paper_id,
                "title": title,
                **section,
            }
            with open(os.path.join(rag_sections_dir, section_name + ".json"), "w", encoding="utf-8") as file:
                json.dump(section_result, file, ensure_ascii=False, indent=2)
            with open(os.path.join(rag_sections_dir, section_name + ".md"), "w", encoding="utf-8") as file:
                file.write(section["index_text"])
                file.write("\n")

        with open(os.path.join(paper_dir, "content_list.json"), "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        results[paper_id] = result

    return results
