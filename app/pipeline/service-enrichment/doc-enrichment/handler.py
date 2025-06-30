def enrich_pdf(pdf_path: str, enrichment_prompt: dict, output_dir: str) -> None:
    """
    Uses Gemini to extract structured information from a full PDF using the provided enrichment prompt dict.
    Stores the result in output_dir/genai_outputs/pdf_enrichment_output.json.
    """
    from services.gemini_client import call_gemini_with_pdf  # Ensure this exists

    def encode_pdf_to_base64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    #genai_output_dir = os.path.join(output_dir, "genai_outputs")
    os.makedirs(output_dir, exist_ok=True)
    enrichment_output_path = os.path.join(output_dir, "enrichment_output.json")

    try:
        pdf_base64 = encode_pdf_to_base64(pdf_path)
        enrichment_response = call_gemini_with_pdf(pdf_base64, enrichment_prompt_dict=enrichment_prompt)
        raw_text = enrichment_response.get("text", "")

        # Try to parse JSON from response
        try:
            enrichment_json_str = extract_json_string(raw_text)
            enrichment_json = json.loads(enrichment_json_str) if enrichment_json_str else {}
        except Exception as je:
            enrichment_json = {
                "error": "Failed to parse JSON from enrichment response",
                "raw_text": raw_text,
                "exception": str(je)
            }

        with open(enrichment_output_path, "w", encoding="utf-8") as f:
            json.dump(enrichment_json, f, indent=2, ensure_ascii=False)

        print(f"✅ Enrichment output saved to: {enrichment_output_path}")

    except Exception as e:
        print(f"❌ Failed to enrich PDF with Gemini: {e}")
        
        
if __name__ == "__main__":
    # Perform enrichment-level extraction
    enrich_pdf(
        pdf_path=str(pdf_path),
        enrichment_prompt=enrichment_prompt_config, 
        output_dir=str(output_dir_path)
    )