from typing import Dict, List, TypedDict

RAG_PAPER_QUERIES = {
    "paper_info": [
        "List the paper title, author names and their institutional affiliations."
    ],
    "figures": ["Describe the architecture or framework diagram. What are the main components shown?"],
    "tables": [
        "Show the main performance comparison table with all methods and metrics. Include exact numbers.",
        "Show the ablation study table with all variants and their results.",
        "What datasets are used, and how many training examples or sentence pairs does each contain?",
    ],
    "equations": ["What is the core model formulation or main equation? Show the exact formula and notation."],
    "motivation": [
        "What problem or task does this paper aim to solve? Describe the specific challenges.",
        "What are the limitations or drawbacks of existing approaches mentioned in the introduction or related work?",
        "What gap or unmet need motivates this research? How is it different from prior work?",
    ],
    "solution": [
        "What method, approach, or framework does this paper propose? Provide an overview.",
        "What are the main components, modules, or steps of the proposed method?",
        "What are the key equations, formulas, or mathematical formulations? Show the notation and mathematical expressions.",
        "What is the algorithm, procedure, or workflow? Describe the key steps.",
    ],
    "results": [
        "What datasets, benchmarks, or experimental setups are used for evaluation?",
        "What evaluation metrics or criteria are used to measure performance?",
        "What are the main results shown in the main results table?",
        "How does the proposed method compare to baseline methods? Show the comparison.",
        "What performance does the method achieve? Report the exact numbers from experiments.",
    ],
    "contributions": [
        "What are the main contributions listed in the introduction or conclusion?",
        "What is novel or new about this work compared to existing methods?",
        "What limitations does the paper acknowledge? What future directions are suggested?",
    ],
}

# https://github.com/HKUDS/LightRAG#selecting-query-modes
RAG_QUERY_MODES = {
    "paper_info": "hybrid",
    "figures": "mix",
    "tables": "mix",
    "equations": "mix",
    "motivation": "mix",
    "solution": "mix",
    "results": "mix",
    "contributions": "mix",
}
