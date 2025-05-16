import os
import json
import pandas as pd
from typing import Union, List, Dict

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
