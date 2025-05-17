<<<<<<< HEAD
import os
import json
from typing import Union, List, Dict

# Load HTML tag mapping directly from JSON
def load_tag_mapping():
    mapping_path = os.path.join(os.path.dirname(__file__), "../config/tag_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        return json.load(f)

HTML_TAG_MAP = load_tag_mapping()

def convert_json_to_html(
    json_input: Union[str, List[Dict]],
    output_dir: str,
    output_filename: str = "output.html"
) -> None:
    """
    Converts a JSON list of dicts into an HTML file using the "tag" key to define HTML tags.

    Args:
        json_input (str or List[Dict]): Path to JSON file or list of dicts.
        output_dir (str): Directory to save the HTML file.
        output_filename (str): Name of the output HTML file.
    """

    # Load the JSON input
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json_input

    html_elements = []

    for node in data:
        tag_name = node.get("tag", "div")
        content = node.get("content", "")
        html_tag = HTML_TAG_MAP.get(tag_name, "div")  # fallback to <div>
        html_elements.append(f"<{html_tag}>{content}</{html_tag}>")

    # Compose full HTML
    full_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "  <head>\n"
        "    <meta charset=\"UTF-8\">\n"
        "    <title>Generated Document</title>\n"
        "  </head>\n"
        "  <body>\n    "
        + "\n    ".join(html_elements) +
        "\n  </body>\n</html>"
    )

    # Write output HTML
    output_path = os.path.join(output_dir, output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"✅ HTML file created at: {output_path}")
=======
import os
import json
from typing import Union, List, Dict

# Load HTML tag mapping directly from JSON
def load_tag_mapping():
    mapping_path = os.path.join(os.path.dirname(__file__), "../config/tag_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        return json.load(f)

HTML_TAG_MAP = load_tag_mapping()

def convert_json_to_html(
    json_input: Union[str, List[Dict]],
    output_dir: str,
    output_filename: str = "output.html"
) -> None:
    """
    Converts a JSON list of dicts into an HTML file using the "tag" key to define HTML tags.

    Args:
        json_input (str or List[Dict]): Path to JSON file or list of dicts.
        output_dir (str): Directory to save the HTML file.
        output_filename (str): Name of the output HTML file.
    """

    # Load the JSON input
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json_input

    html_elements = []

    for node in data:
        tag_name = node.get("tag", "div")
        content = node.get("content", "")
        html_tag = HTML_TAG_MAP.get(tag_name, "div")  # fallback to <div>
        html_elements.append(f"<{html_tag}>{content}</{html_tag}>")

    # Compose full HTML
    full_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "  <head>\n"
        "    <meta charset=\"UTF-8\">\n"
        "    <title>Generated Document</title>\n"
        "  </head>\n"
        "  <body>\n    "
        + "\n    ".join(html_elements) +
        "\n  </body>\n</html>"
    )

    # Write output HTML
    output_path = os.path.join(output_dir, output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"✅ HTML file created at: {output_path}")
>>>>>>> 0a83a9c1580e560899dd70f82a8bbcb59f0dcb6f
