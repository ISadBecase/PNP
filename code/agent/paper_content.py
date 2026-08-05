import json
import os
import re
import logging

logger = logging.getLogger(__name__)

def extract_paper_content(paper_json):
    with open(paper_json, "r", encoding="utf-8") as file:
        paper = json.load(file)

    metadata = paper.get("metadata", {})
    introduction = ""
    conclusion = ""

    for section in paper.get("sections", []):
        title = section.get("title", "").strip().lower()
        title = re.sub(r"^\d+(?:\.\d+)*[\s.:-]+", "", title)

        if not introduction and title == "introduction":
            introduction = section.get("text", "")
        if not conclusion and title in (
            "conclusion",
            "conclusions",
            "conclusion and future work",
            "conclusions and future work",
        ):
            conclusion = section.get("text", "")

    return {
        "Title": metadata.get("title", ""),
        "sections": [
            {"title": "Abstract", "content": metadata.get("abstract", "")},
            {"title": "Introduction", "content": introduction},
            {"title": "Conclusion", "content": conclusion},
        ],
    }


def extract_papers(arxiv_root, output_dir):
    temp_dir = os.path.join(output_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    results = []
    for paper_id in sorted(os.listdir(arxiv_root)):
        paper_json = os.path.join(arxiv_root, paper_id, "paper.json")
        paper_main_content = extract_paper_content(paper_json)

        main_section_dir = os.path.join(temp_dir, paper_id)
        os.makedirs(main_section_dir, exist_ok=True)

        with open(os.path.join(main_section_dir, "main_section.json"), "w", encoding="utf-8",) as file:
            json.dump(paper_main_content, file, ensure_ascii=False, indent=2)

        results.append(main_section_dir)
        logging.info(f"    Extracted paper Abstract & Introduction & Conclusion content for {paper_id}")

    return results
