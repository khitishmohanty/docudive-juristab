import os
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash-preview-04-17")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

def call_gemini_api(
    image_base64: str,
    prompt: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    mime_type: str = "image/jpeg"
) -> str:
    """
    Calls the Gemini API with an image and prompt, and returns the response.

    Args:
        image_base64 (str): Base64-encoded image string.
        prompt (str): Text prompt to send to Gemini.
        api_key (Optional[str]): Gemini API key. Defaults to value in .env.
        model (Optional[str]): Model name. Defaults to value in .env.
        mime_type (str): MIME type of the image (e.g., "image/jpeg", "image/png").

    Returns:
        str: The text response from Gemini API.
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
                    },
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to call Gemini API: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected response structure: {e}")
