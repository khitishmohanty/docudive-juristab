import json
import os
import pandas as pd

from utils.csv_excel_converter import convert_json_to_csv_and_excel
from utils.html_converter import convert_json_to_html

def _save_results(all_responses: list, page_metrics: list, output_dir: str) -> None:
    """Saves all responses to JSON, CSV, Excel, HTML and page metrics to Excel/CSV."""
    master_json_path = os.path.join(output_dir, "layout_with_verification.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"✅ Master JSON with verification status saved to: {master_json_path}")

    if all_responses:
        dict_responses = [item for item in all_responses if isinstance(item, dict)]
        if dict_responses:
            try:
                convert_json_to_csv_and_excel(dict_responses, output_dir, base_filename="layout_with_verification")
                convert_json_to_html(dict_responses, output_dir, output_filename="layout_with_verification.html")
            except Exception as e_convert:
                print(f"❌ Error during CSV/Excel/HTML conversion: {e_convert}")
        else:
            print("No dictionary data found in all_responses to convert to tabular formats.")
    else:
        print("No responses to convert because all_responses is empty.")

    summary_df = pd.DataFrame(page_metrics)
    summary_excel_path = os.path.join(output_dir, "page_summary_with_verification.xlsx")
    try:
        summary_df.to_excel(summary_excel_path, index=False)
        print(f"✅ Page-level summary with verification written to: {summary_excel_path}")
    except Exception as e:
        print(f"❌ Failed to save page summary to Excel: {e}")
        summary_csv_path = os.path.join(output_dir, "page_summary_with_verification.csv")
        try:
            summary_df.to_csv(summary_csv_path, index=False)
            print(f"✅ Page-level summary written to CSV as fallback: {summary_csv_path}")
        except Exception as e_csv:
            print(f"❌ Failed to save page summary to CSV as fallback: {e_csv}")