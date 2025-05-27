import os
import json
import pandas as pd
from typing import Union, List, Dict
from pdf2image import convert_from_path

def convert_json_to_csv_and_excel(
    json_input: Union[str, List[Dict]],
    output_dir: str,
    base_filename: str = "gemini_output"
) -> None:
    """
    Converts a JSON list of dicts into both CSV and Excel formats.

    Args:
        json_input (str or List[Dict]): JSON file path or in-memory JSON object.
        output_dir (str): Directory where output files will be saved.
        base_filename (str): Base name for CSV and Excel files.
    """

    # Load JSON from file if a path is provided
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json_input  # Assume it's already a Python object

    # Create DataFrame
    df = pd.DataFrame(data)

    # Define output paths
    csv_path = os.path.join(output_dir, f"{base_filename}.csv")
    excel_path = os.path.join(output_dir, f"{base_filename}.xlsx")

    # Save files
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(excel_path, index=False)

    print(f"✅ Saved CSV to: {csv_path}")
    print(f"✅ Saved Excel to: {excel_path}")
    
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
    
def convert_json_to_csv_and_excel(
    json_input: Union[str, List[Dict]],
    output_dir: str,
    base_filename: str = "gemini_output"
) -> None:
    """
    Converts a JSON list of dicts into both CSV and Excel formats.

    Args:
        json_input (str or List[Dict]): JSON file path or in-memory JSON object.
        output_dir (str): Directory where output files will be saved.
        base_filename (str): Base name for CSV and Excel files.
    """

    # Load JSON from file if a path is provided
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json_input  # Assume it's already a Python object

    # Create DataFrame
    df = pd.DataFrame(data)

    # Define output paths
    csv_path = os.path.join(output_dir, f"{base_filename}.csv")
    excel_path = os.path.join(output_dir, f"{base_filename}.xlsx")

    # Save files
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(excel_path, index=False)

    print(f"✅ Saved CSV to: {csv_path}")
    print(f"✅ Saved Excel to: {excel_path}")
    
def convert_pdf_to_images(
    pdf_path: str,
    output_dir: str,
    image_format: str = "jpeg",  # ⬅️ Changed from "jpg" to "jpeg"
    dpi: int = 200,
    poppler_path: str = None
) -> List[str]:
    """
    Converts each page of a PDF into an image.

    Args:
        pdf_path (str): Path to the PDF file.
        output_dir (str): Directory to save image files.
        image_format (str): Image format (jpeg, png). Default is 'jpeg'.
        dpi (int): Resolution in DPI. Default is 200.
        poppler_path (str): Path to poppler/bin (Windows only).

    Returns:
        List[str]: List of paths to the generated image files.
    """
    os.makedirs(output_dir, exist_ok=True)

    images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler_path)

    image_paths = []
    for i, img in enumerate(images):
        image_filename = f"page_{i + 1}.{image_format}"
        image_path = os.path.join(output_dir, image_filename)
        img.save(image_path, format="JPEG")  # Always use "JPEG" format for saving
        image_paths.append(image_path)

    #print(f"✅ Converted {len(image_paths)} pages to images in: {output_dir}")
    print(f"✅ Converted {len(image_paths)} pages to images")
    return image_paths

