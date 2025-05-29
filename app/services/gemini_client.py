import os
import requests
from typing import Optional, Dict, Any, List # Added List
from dotenv import load_dotenv
import json


load_dotenv()

# Load environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-1.5-flash-latest") # Updated to a common model, adjust if needed
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# Token pricing from environment variables (price per 1M tokens)
# Ensure these environment variables are set, or adjust defaults if necessary.
GEMINI_INPUT_PRICE_PER_MILLION = float(os.getenv("GEMINI_INPUT_PRICE_PER_MILLION", "0.35")) # Example for Flash 1.5
GEMINI_OUTPUT_PRICE_PER_MILLION = float(os.getenv("GEMINI_OUTPUT_PRICE_PER_MILLION", "1.05")) # Example for Flash 1.5 (text)

# Convert to per-token price
GEMINI_INPUT_TOKEN_PRICE = GEMINI_INPUT_PRICE_PER_MILLION / 1_000_000
GEMINI_OUTPUT_TOKEN_PRICE = GEMINI_OUTPUT_PRICE_PER_MILLION / 1_000_000

def _make_gemini_request(
    payload: Dict[str, Any],
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Internal helper function to make a request to the Gemini API and handle common response processing.
    """
    api_key_to_use = api_key or GEMINI_API_KEY
    model_to_use = model or GEMINI_MODEL
    
    if not api_key_to_use:
        raise ValueError("❌ GEMINI_API_KEY is not set. Please set it in your .env file or pass it directly.")

    endpoint = f"{GEMINI_BASE_URL}/{model_to_use}:generateContent?key={api_key_to_use}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status() # Raises an HTTPError for bad responses (4XX or 5XX)
        result = response.json()

        text = ""
        # Safely extract text from the response
        if result.get("candidates") and \
           isinstance(result["candidates"], list) and \
           len(result["candidates"]) > 0 and \
           result["candidates"][0].get("content") and \
           result["candidates"][0]["content"].get("parts") and \
           isinstance(result["candidates"][0]["content"]["parts"], list) and \
           len(result["candidates"][0]["content"]["parts"]) > 0:
            
            first_part = result["candidates"][0]["content"]["parts"][0]
            if "text" in first_part:
                text = first_part["text"]
            # If the model returns a function call, it won't have 'text' in the same way.
            # elif "functionCall" in first_part:
            #     text = json.dumps(first_part["functionCall"]) # Example: serialize function call
            else:
                # This case might occur if the response isn't simple text (e.g., tool use)
                # For now, we'll try to concatenate any text found in parts or represent as string
                all_parts_content = [part.get("text", str(part)) for part in result["candidates"][0]["content"]["parts"]]
                text = "\n".join(all_parts_content) if all_parts_content else ""
                if not text: # Fallback if no text parts found at all
                     print(f"⚠️ Warning: No 'text' found in Gemini response parts. Raw first part: {first_part}")


        usage_metadata = result.get("usageMetadata", {})
        input_tokens = usage_metadata.get("promptTokenCount", 0)
        # Output tokens might be under 'candidatesTokenCount' or 'totalTokenCount' - 'promptTokenCount'
        # 'candidatesTokenCount' is usually more accurate for the generated content.
        output_tokens = usage_metadata.get("candidatesTokenCount", 0) 
        
        # Ensure tokens are integers
        input_tokens = int(input_tokens)
        output_tokens = int(output_tokens)

        cost = (GEMINI_INPUT_TOKEN_PRICE * input_tokens) + (GEMINI_OUTPUT_TOKEN_PRICE * output_tokens)

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens, # Total tokens used in the call
            "cost_usd": cost,
            "raw_response": result # Include the full raw response for debugging or richer data
        }

    except requests.exceptions.HTTPError as http_err:
        error_content = "No error content in response body."
        try:
            error_content = response.json() # Try to get JSON error details
        except json.JSONDecodeError:
            error_content = response.text # Fallback to raw text if not JSON
        print(f"❌ HTTP error occurred: {http_err} - Status Code: {response.status_code}")
        print(f"Error details: {error_content}")
        # Consider re-raising with more info or a custom exception
        raise RuntimeError(f"❌ Gemini API HTTP error: {http_err} - {error_content}") from http_err
    except requests.exceptions.RequestException as req_err:
        # Network errors (DNS failure, refused connection, etc.)
        print(f"❌ Request error occurred: {req_err}")
        raise RuntimeError(f"❌ Gemini API request failed: {req_err}") from req_err
    except Exception as e:
        # Catch-all for other unexpected errors, e.g., issues with response.json() if not an HTTPError
        print(f"❌ An unexpected error occurred: {e}")
        raise RuntimeError(f"❌ Unexpected error processing Gemini response: {e}") from e


def call_gemini_api(
    prompt_text: str,
    media_item1_base64: str,
    media_item1_mime_type: str,
    media_item2_base64: Optional[str] = None,
    media_item2_mime_type: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    generation_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Calls the Gemini API with a text prompt and one or two media items (images or PDFs).

    Args:
        prompt_text (str): The main text prompt for the task.
        media_item1_base64 (str): Base64 encoded string of the first media item.
        media_item1_mime_type (str): Mime type of the first media item (e.g., "application/pdf", "image/jpeg").
        media_item2_base64 (Optional[str]): Base64 encoded string of the second media item.
        media_item2_mime_type (Optional[str]): Mime type of the second media item.
        api_key (Optional[str]): Gemini API key. Defaults to environment variable.
        model (Optional[str]): Gemini model name. Defaults to environment variable.
        generation_config (Optional[Dict[str, Any]]): Configuration for generation,
                                                     e.g., {"responseMimeType": "application/json"}.

    Returns:
        Dict[str, Any]: A dictionary containing the API response including 'text', 
                        token counts, 'cost_usd', and 'raw_response'.
    
    Raises:
        ValueError: If required inputs are missing or inconsistent.
    """
    if not prompt_text:
        raise ValueError("❌ prompt_text cannot be empty.")
    if not media_item1_base64 or not media_item1_mime_type:
        raise ValueError("❌ First media item (base64 data and mimeType) must be provided.")
    
    if media_item2_base64 and not media_item2_mime_type:
        raise ValueError("❌ Mime type for the second media item must be provided if its data is present.")
    if not media_item2_base64 and media_item2_mime_type:
        raise ValueError("❌ Data for the second media item must be provided if its mime type is present.")

    parts_list: List[Dict[str, Any]] = []

    # Add first media item
    parts_list.append({
        "inlineData": {
            "mimeType": media_item1_mime_type,
            "data": media_item1_base64
        }
    })

    # Add second media item if provided
    if media_item2_base64 and media_item2_mime_type:
        parts_list.append({
            "inlineData": {
                "mimeType": media_item2_mime_type,
                "data": media_item2_base64
            }
        })
    
    # Add the main text prompt. Conventionally, text prompts often follow media items in multimodal requests.
    parts_list.append({"text": prompt_text})

    # Construct the final payload for the API request
    payload: Dict[str, Any] = {"contents": [{"parts": parts_list}]}

    # Include generation configuration if provided (e.g., for forcing JSON output)
    if generation_config:
        payload["generationConfig"] = generation_config
    # Example: If you usually want JSON output, you could default it here:
    # else:
    #     payload["generationConfig"] = {"responseMimeType": "application/json"}


    # Delegate the actual API call and response handling to _make_gemini_request
    return _make_gemini_request(payload, api_key, model)

# You can now delete the old `call_gemini_api`, `call_gemini_with_pdf`, 
# and `call_gemini_multimodal_content` functions from this file, 
# as their functionalities are covered by the new `call_gemini_api` 
# and the helper `_make_gemini_request`.