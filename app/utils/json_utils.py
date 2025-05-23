import re
import json

def attach_page_number_tag(consolidated, page_number: int):
    """Adds 'page_number' to each node if it's not already present."""
    if isinstance(consolidated, list):
        for node in consolidated:
            if isinstance(node, dict) and "page_number" not in node:
                node["page_number"] = page_number
    elif isinstance(consolidated, dict):
        if "document_elements" in consolidated and isinstance(consolidated["document_elements"], list):
            for node in consolidated["document_elements"]:
                if isinstance(node, dict) and "page_number" not in node:
                    node["page_number"] = page_number
        elif "page_number" not in consolidated:
            consolidated["page_number"] = page_number
    return consolidated

def extract_json_string(raw_text: str) -> str:
    """Extracts the first valid JSON array or object from a raw string."""
    json_markdown_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
    if json_markdown_match:
        return json_markdown_match.group(1).strip()
    json_pattern = r"(\[.*?\]|\{.*?\})"
    matches = re.findall(json_pattern, raw_text, re.DOTALL)
    if matches:
        for match in matches:
            try:
                json.loads(match)
                return match
            except json.JSONDecodeError:
                continue
    return ""