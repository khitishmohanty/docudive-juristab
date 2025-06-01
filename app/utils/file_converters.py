import os
import json
import pandas as pd
from typing import Union, List, Dict, Any
from pdf2image import convert_from_path
import re # For markdown processing

# --- Helper to load tag mapping ---
def load_tag_mapping():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        mapping_path = os.path.join(current_dir, "../config/tag_mapping.json") 
        if not os.path.exists(mapping_path):
            project_root_guess = os.path.abspath(os.path.join(current_dir, ".."))
            mapping_path = os.path.join(project_root_guess, "config/tag_mapping.json")
            if not os.path.exists(mapping_path):
                mapping_path = os.path.join(current_dir, "tag_mapping.json")

        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Tag mapping file not found at expected path(s). Using default mapping.")
        return {
            "Header": "header", "Title": "h1", "Subtitle": "h2", 
            "Heading-h1": "h1", "Heading-h2": "h2", "Heading-h3": "h3", 
            "Heading-h4": "h4", "Heading-h5": "h5", "Heading-h6": "h6",
            "Paragraph": "p", "List": "ul", "Table": "table", "Figure": "figure",
            "Table of Contents": "nav", "Footer": "footer", "Footnote": "aside",
            "Page number": "span", "Enum": "span", "Endnotes": "section", "Glossary": "section"
        }

HTML_TAG_MAP = load_tag_mapping()

# --- Helper function to escape HTML content ---
def escape_html(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&#39;")

# --- Enhanced function to convert markdown and process explicit hyperlinks ---
def process_content_for_html(content_str: str, explicit_hyperlinks: List[Dict[str, str]] = None) -> str:
    if not isinstance(content_str, str):
        content_str = str(content_str)
    
    processed_content = escape_html(content_str)
    # Markdown for bold and italics
    processed_content = re.sub(r'\*\*(?=\S)(.*?)(?<=\S)\*\*|__(?=\S)(.*?)(?<=\S)__', r'<strong>\1\2</strong>', processed_content)
    processed_content = re.sub(r'\*(?=\S)(.*?)(?<=\S)\*|_(?=\S)(.*?)(?<=\S)_', r'<em>\1\2</em>', processed_content)
    # Markdown for links
    processed_content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', processed_content)
    processed_content = processed_content.replace('\n', '<br>\n')

    if explicit_hyperlinks and isinstance(explicit_hyperlinks, list):
        links_html_parts = ["<div class='explicit-hyperlinks'><strong>Links:</strong><ul>"]
        for link_info in explicit_hyperlinks:
            if isinstance(link_info, dict):
                url = link_info.get("url", "#")
                text = link_info.get("text", url)
                links_html_parts.append(f'<li><a href="{escape_html(url)}">{escape_html(text)}</a></li>')
        links_html_parts.append("</ul></div>")
        processed_content += "\n" + "".join(links_html_parts)
        
    return processed_content


# --- Function to convert book_output.json content to hierarchical, collapsible HTML ---
def convert_book_json_to_html(
    book_data: Dict[str, List[Dict[str, Any]]],
    output_dir: str,
    output_filename: str = "book_output.html"
) -> None:
    html_body_parts = []
    all_items = []
    sorted_page_numbers = sorted(book_data.keys(), key=lambda p: int(p) if p.isdigit() else float('inf'))
    for page_num_str in sorted_page_numbers:
        page_items = book_data.get(page_num_str, [])
        if isinstance(page_items, list):
            all_items.extend(page_items)
        else:
            all_items.append({"tag": "Error", "content": f"Invalid content structure for page {page_num_str}: {page_items}"})

    open_details_stack = [] 

    for i, item in enumerate(all_items):
        if not isinstance(item, dict):
            html_body_parts.append(f"<p>Error: Encountered non-dictionary item: {escape_html(str(item))}</p>\n")
            continue

        tag_key = item.get("tag", "Paragraph")
        html_tag_from_map = HTML_TAG_MAP.get(tag_key, "p")
        raw_content = item.get("content", "")
        explicit_hyperlinks = item.get("hyperlinks")
        is_heading = html_tag_from_map.startswith("h") and len(html_tag_from_map) == 2 and html_tag_from_map[1].isdigit()
        current_heading_level = int(html_tag_from_map[1]) if is_heading else 0

        if is_heading:
            while open_details_stack and open_details_stack[-1] >= current_heading_level:
                open_details_stack.pop()
                html_body_parts.append("</div></details>\n") 
            
            cleaned_heading_content = str(raw_content).strip()
            # Remove leading/trailing ** only if they are exact and form the full enclosure
            if cleaned_heading_content.startswith("**") and cleaned_heading_content.endswith("**") and len(cleaned_heading_content) >= 4:
                cleaned_heading_content = cleaned_heading_content[2:-2]
            
            summary_content_html = escape_html(cleaned_heading_content)
            
            details_class = f"details-level-{current_heading_level}" # For indentation of the whole block
            html_body_parts.append(f"<details open class='{details_class}'>\n  <summary><{html_tag_from_map}>{summary_content_html}</{html_tag_from_map}></summary>\n<div class='collapsible-content-wrapper'>\n")
            open_details_stack.append(current_heading_level)
        else:
            processed_content_html = ""
            if tag_key == "Table of Contents":
                processed_content_html += f"<{html_tag_from_map} class='table-of-contents'>\n"
                try:
                    toc_data = json.loads(raw_content if isinstance(raw_content, str) else "[]")
                    def render_toc_items(items_list):
                        if not items_list: return ""
                        rendered_ul = "<ul>\n"
                        for toc_item_dict in items_list:
                            item_text = toc_item_dict.get("item_text", "Untitled")
                            rendered_ul += f"  <li>{escape_html(item_text)}"
                            sub_items = toc_item_dict.get("sub_items")
                            if sub_items and isinstance(sub_items, list):
                                rendered_ul += render_toc_items(sub_items)
                            rendered_ul += "</li>\n"
                        rendered_ul += "</ul>\n"
                        return rendered_ul
                    processed_content_html += render_toc_items(toc_data)
                except Exception as e_toc:
                     processed_content_html += f"<p>Error rendering Table of Contents: {escape_html(str(e_toc))}</p><pre>{escape_html(raw_content)}</pre>"
                processed_content_html += f"</{html_tag_from_map}>\n"
            
            elif tag_key == "List":
                processed_content_html += f"<{html_tag_from_map}>\n" 
                if isinstance(raw_content, str):
                    list_items = raw_content.split('\n')
                    for li_content in list_items:
                        li_content_stripped = li_content.strip()
                        # Clean common leading bullet characters/markdown for lists
                        li_content_stripped = re.sub(r'^[\s]*[\*\-\•\.]\s*', '', li_content_stripped) # Remove *, -, •, . followed by space
                        if li_content_stripped:
                            li_html = process_content_for_html(li_content_stripped, None)
                            processed_content_html += f"  <li>{li_html}</li>\n" 
                elif isinstance(raw_content, list): 
                    for li_content_item_raw in raw_content:
                        li_content_item_str = str(li_content_item_raw).strip()
                        li_content_item_str = re.sub(r'^[\s]*[\*\-\•\.]\s*', '', li_content_item_str)
                        if li_content_item_str:
                            li_html = process_content_for_html(li_content_item_str, None)
                            processed_content_html += f"  <li>{li_html}</li>\n"
                else:
                    # Fallback if raw_content is not string or list (should ideally not happen for "List" tag)
                    cleaned_fallback_content = re.sub(r'^[\s]*[\*\-\•\.]\s*', '', str(raw_content).strip())
                    if cleaned_fallback_content:
                        processed_content_html += f"  <li>{escape_html(cleaned_fallback_content)}</li>\n"
                processed_content_html += f"</{html_tag_from_map}>\n"

            elif tag_key == "Table":
                # (Table rendering logic remains complex and largely the same as previous version)
                # This part might need further refinement based on actual table JSON structure
                processed_content_html += f"<{html_tag_from_map} class='data-table'>\n"
                if isinstance(raw_content, list) and all(isinstance(row, list) for row in raw_content):
                    header_processed_in_list_table = False 
                    tbody_opened = False
                    for i_row, row_data in enumerate(raw_content):
                        is_header_row = False
                        if i_row == 0 and isinstance(row_data[0], dict) and row_data[0].get("isHeader"):
                            is_header_row = True
                            if not header_processed_in_list_table:
                                processed_content_html += "  <thead>\n"; header_processed_in_list_table = True
                        elif not header_processed_in_list_table and not tbody_opened: # First row, not explicitly header
                             processed_content_html += "  <tbody>\n"; tbody_opened = True
                        
                        processed_content_html += "    <tr>\n"
                        cell_tag = "th" if is_header_row else "td"
                        for cell_item in row_data:
                            cell_content_str, colspan, rowspan = "", 1, 1
                            if isinstance(cell_item, dict):
                                cell_content_str = str(cell_item.get("content", ""))
                                colspan = cell_item.get("colspan", 1); rowspan = cell_item.get("rowspan", 1)
                                if cell_item.get("isHeader"): cell_tag = "th"
                            else: cell_content_str = str(cell_item)
                            attrs = ""
                            if colspan > 1: attrs += f' colspan="{colspan}"'
                            if rowspan > 1: attrs += f' rowspan="{rowspan}"'
                            processed_content_html += f"      <{cell_tag}{attrs}>{process_content_for_html(cell_content_str, None)}</{cell_tag}>\n"
                        processed_content_html += "    </tr>\n"
                        if is_header_row and i_row == 0 : 
                            processed_content_html += "  </thead>\n"
                            if not tbody_opened and i_row + 1 < len(raw_content): 
                                processed_content_html += "  <tbody>\n"; tbody_opened = True
                    if tbody_opened : processed_content_html += "  </tbody>\n"
                
                elif isinstance(raw_content, str): 
                    lines = raw_content.strip().split('\n')
                    header_processed_str_table = False; in_tbody_str_table = False
                    for line_idx, line_content in enumerate(lines):
                        line_content = line_content.strip();
                        if not line_content: continue
                        if '|' in line_content: 
                            cells = [cell.strip() for cell in line_content.split('|')]
                            is_md_header_row = not header_processed_str_table and \
                                               (line_idx + 1 < len(lines) and "---" in lines[line_idx+1].replace(" ", "").replace("-",""))
                            
                            if is_md_header_row:
                                if not in_tbody_str_table: processed_content_html += "  <thead>\n" 
                                processed_content_html += "    <tr>\n"; 
                                for cell in cells: processed_content_html += f"      <th>{process_content_for_html(cell, None)}</th>\n"
                                processed_content_html += "    </tr>\n"; 
                                if not in_tbody_str_table: processed_content_html += "  </thead>\n" 
                                header_processed_str_table = True
                            elif "---" in line_content.replace(" ", "") and header_processed_str_table and not in_tbody_str_table: 
                                 if not in_tbody_str_table: processed_content_html += "  <tbody>\n"; in_tbody_str_table = True; continue
                            else: 
                                if not header_processed_str_table and not in_tbody_str_table: 
                                     processed_content_html += "  <tbody>\n"; in_tbody_str_table = True
                                elif header_processed_str_table and not in_tbody_str_table: 
                                     processed_content_html += "  <tbody>\n"; in_tbody_str_table = True

                                processed_content_html += "    <tr>\n"; 
                                for cell in cells: processed_content_html += f"      <td>{process_content_for_html(cell, None)}</td>\n"
                                processed_content_html += "    </tr>\n"
                        else: 
                            if not in_tbody_str_table: processed_content_html += "  <tbody>\n"; in_tbody_str_table = True
                            processed_content_html += f"<tr><td colspan='99'>{process_content_for_html(line_content, explicit_hyperlinks if line_idx == 0 else None)}</td></tr>\n"
                    if in_tbody_str_table: processed_content_html += "  </tbody>\n"
                else: 
                    processed_content_html += f"  <tbody><tr><td>{escape_html(str(raw_content))}</td></tr></tbody>\n"
                processed_content_html += f"</{html_tag_from_map}>\n"
            
            else: 
                content_to_render = process_content_for_html(raw_content, explicit_hyperlinks)
                processed_content_html = f"<{html_tag_from_map}>{content_to_render}</{html_tag_from_map}>\n"
            
            html_body_parts.append(processed_content_html)

    while open_details_stack:
        open_details_stack.pop()
        html_body_parts.append("</div></details>\n")

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Book Output</title>
    <style>
        body {{ 
            font-family: Arial, sans-serif; 
            line-height: 1.6; 
            margin: 0 auto; 
            max-width: 900px; 
            padding: 20px; 
            font-size: 16px; /* Base font size */
        }}
        details {{ 
            margin-bottom: 0.25em; 
            border: none; 
            background-color: transparent; 
        }}
        summary {{ 
            padding-top: 0.3em; 
            padding-bottom: 0.3em;
            /* Left padding is now handled by parent <details> via .details-level-X */
            cursor: pointer; 
            list-style-position: inside; 
            font-weight: bold; 
            background-color: transparent; 
            border-bottom: none; 
        }}
        /* No specific style for details[open] > summary if borders are removed */

        .collapsible-content-wrapper {{ 
            padding-top: 0.5em; 
            padding-bottom: 0.5em;
            /* Content inside wrapper will align with the indented <details> block */
        }}

        /* Headings within summary: same size as body, bold */
        summary > h1, summary > h2, summary > h3, summary > h4, summary > h5, summary > h6 {{ 
            display: inline; 
            margin: 0; 
            font-size: 1em; /* Same size as body font size */
            font-weight: bold;
        }}

        /* Indentation for heading levels applied to the <details> block */
        .details-level-1 {{ padding-left: 0em; }} 
        .details-level-2 {{ padding-left: 1.5em; }}   
        .details-level-3 {{ padding-left: 3em; }} 
        .details-level-4 {{ padding-left: 4.5em; }}
        .details-level-5 {{ padding-left: 6em; }}
        .details-level-6 {{ padding-left: 7.5em; }}

        /* General content styling */
        p {{ margin-top:0; margin-bottom: 0.8em; }}
        ul, ol {{ margin-top:0; margin-bottom: 0.8em; padding-left: 20px; list-style-position: outside;}} 
        li {{ margin-bottom: 0.2em; }}
        table.data-table {{ width: 100%; border-collapse: collapse; margin-bottom: 1em; }}
        table.data-table th, table.data-table td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        table.data-table th {{ background-color: #f2f2f2; font-weight: bold; }}
        figure {{ margin: 1em 0; text-align: center; }}
        figure img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
        figcaption {{ font-style: italic; font-size: 0.9em; color: #555; margin-top: 0.5em; }}
        .table-of-contents ul {{ list-style-type: none; padding-left: 0; }}
        .table-of-contents ul ul {{ padding-left: 20px; }}
        .explicit-hyperlinks {{ font-size: 0.9em; color: #333; background-color: #f0f7fd; border: 1px dashed #add8e6; padding: 8px; margin-top: 8px; border-radius: 3px;}}
        .explicit-hyperlinks ul {{padding-left: 15px; margin-top: 5px;}}
        .explicit-hyperlinks strong {{color: #0056b3;}}
    </style>
</head>
<body>
    {''.join(html_body_parts)}
</body>
</html>
"""

    output_path = os.path.join(output_dir, output_filename)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_html)
        print(f"✅ Hierarchical collapsible HTML file with updated styles created at: {output_path}")
    except Exception as e:
        print(f"❌ Error writing HTML file {output_path}: {e}")


# --- Existing functions (ensure convert_json_to_csv_and_excel is defined only once) ---
def convert_json_to_csv_and_excel(
    json_input: Union[str, List[Dict]],
    output_dir: str,
    base_filename: str = "gemini_output"
) -> None:
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json_input
    if not data or not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        print(f"ℹ️ No valid list of dictionaries found in json_input for {base_filename}. Skipping CSV/Excel conversion.")
        return
    df = pd.DataFrame(data)
    csv_path = os.path.join(output_dir, f"{base_filename}.csv")
    excel_path = os.path.join(output_dir, f"{base_filename}.xlsx")
    try:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"✅ Saved CSV to: {csv_path}")
    except Exception as e:
        print(f"❌ Error saving CSV {csv_path}: {e}")
    try:
        df.to_excel(excel_path, index=False)
        print(f"✅ Saved Excel to: {excel_path}")
    except Exception as e:
        print(f"❌ Error saving Excel {excel_path}: {e}")

def convert_pdf_to_images(
    pdf_path: str, output_dir: str, image_format: str = "jpeg", 
    dpi: int = 200, poppler_path: str = None # type: ignore
) -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler_path)
    image_paths = []
    for i, img in enumerate(images):
        image_filename = f"page_{i + 1}.{image_format.lower()}"
        image_path = os.path.join(output_dir, image_filename)
        save_format = "JPEG" if image_format.lower() == "jpeg" else image_format.upper()
        img.save(image_path, format=save_format)
        image_paths.append(image_path)
    print(f"✅ Converted {len(image_paths)} pages to images in: {output_dir}")
    return image_paths

# Simple HTML converter (kept for potential other uses, but not for book_output.json)
def convert_json_to_html_simple( 
    json_input: Union[str, List[Dict]],
    output_dir: str,
    output_filename: str = "output_simple.html"
) -> None:
    if isinstance(json_input, str):
        with open(json_input, "r", encoding="utf-8") as f: data = json.load(f)
    else: data = json_input
    html_elements = []
    if isinstance(data, list):
        for node in data:
            if isinstance(node, dict):
                tag_key = node.get("tag", "Paragraph"); content = node.get("content", "")
                html_tag = HTML_TAG_MAP.get(tag_key, "p") 
                html_elements.append(f"<{html_tag}>{escape_html(content)}</{html_tag}>")
            else: html_elements.append(f"<p>Error: Non-dictionary item found: {escape_html(str(node))}</p>")
    elif isinstance(data, dict): 
         html_elements.append(f"<p>Error: Input is a dictionary, simple converter expects a list of items. Try convert_book_json_to_html.</p>")
    else: html_elements.append(f"<p>Error: Invalid JSON input type for simple HTML conversion.</p>")
    full_html = ("<!DOCTYPE html>\n<html lang='en'>\n<head>\n<meta charset=\"UTF-8\">\n" "<title>Generated Simple Document</title>\n</head>\n<body>\n    " + "\n    ".join(html_elements) + "\n</body>\n</html>")
    output_path = os.path.join(output_dir, output_filename); 
    with open(output_path, "w", encoding="utf-8") as f: f.write(full_html)
    print(f"✅ Simple HTML file created at: {output_path}")
