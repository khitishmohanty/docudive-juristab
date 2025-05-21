import os
import requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash-preview-04-17")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# Token pricing from environment variables (price per 1M tokens)
GEMINI_INPUT_PRICE_PER_MILLION = float(os.getenv("GEMINI_INPUT_PRICE_PER_MILLION", "0.25"))  # Example: $0.25 per 1M tokens
GEMINI_OUTPUT_PRICE_PER_MILLION = float(os.getenv("GEMINI_OUTPUT_PRICE_PER_MILLION", "0.50"))  # Example: $0.50 per 1M tokens

# Convert to per-token price
GEMINI_INPUT_TOKEN_PRICE = GEMINI_INPUT_PRICE_PER_MILLION / 1_000_000
GEMINI_OUTPUT_TOKEN_PRICE = GEMINI_OUTPUT_PRICE_PER_MILLION / 1_000_000


def call_gemini_api(
    image_base64: str,
    prompt_parts: list,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    mime_type: str = "image/jpeg"
) -> Dict[str, Any]:
    """
    Calls Gemini API with image and prompt, returns structured response including text, tokens, and cost.
    """
    api_key = api_key or GEMINI_API_KEY
    model = model or GEMINI_MODEL
    endpoint = f"{GEMINI_BASE_URL}/{model}:generateContent?key={api_key}"

    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": image_base64
                        }
                    }
                ] + prompt_parts
            }
        ]
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        # Extract main response text
        text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        # Extract token usage metadata (if available)
        usage = result.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)

        # Calculate estimated cost
        cost = (
            GEMINI_INPUT_TOKEN_PRICE * input_tokens +
            GEMINI_OUTPUT_TOKEN_PRICE * output_tokens
        )

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost
        }

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"❌ Failed to call Gemini API: {e}")
    except Exception as e:
        raise RuntimeError(f"❌ Unexpected response structure from Gemini: {e}")
