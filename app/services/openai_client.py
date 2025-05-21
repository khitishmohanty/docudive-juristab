import os
import imghdr
from openai import OpenAI
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

# Load config from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Pricing: cost per 1 million tokens
OPENAI_INPUT_TOKEN_PRICE = float(os.getenv("OPENAI_INPUT_TOKEN_PRICE_PER_MILLION", "0.00"))
OPENAI_OUTPUT_TOKEN_PRICE = float(os.getenv("OPENAI_OUTPUT_TOKEN_PRICE_PER_MILLION", "0.00"))

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def call_openai_api(prompt: str,
                    image_base64: Optional[str] = None,
                    model: Optional[str] = None,
                    image_path: Optional[str] = None) -> Dict:
    """
    Calls OpenAI's Vision API (GPT-4o or similar) with an optional image and prompt.
    Calculates cost using separate per-million token prices for input and output.

    Returns:
        dict: {
            "text": <completion>,
            "input_tokens": int,
            "output_tokens": int,
            "cost": float
        }
    """
    model = model or OPENAI_MODEL

    try:
        # Detect image MIME type if image path is provided
        mime_type = "image/jpeg"
        if image_path and os.path.isfile(image_path):
            ext = imghdr.what(image_path)
            if ext in {"png", "gif", "webp", "jpeg"}:
                mime_type = f"image/{ext}"
            else:
                raise ValueError(f"Unsupported image format detected: {ext}")

        # Construct messages for the chat API
        messages: List[Dict] = [{"role": "user", "content": []}]

        if image_base64:
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{image_base64}"
                }
            })

        messages[0]["content"].append({
            "type": "text",
            "text": prompt
        })

        # API call
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )

        # Extract usage data
        text = response.choices[0].message.content
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens

        # Calculate cost per million tokens
        cost = (
            input_tokens * OPENAI_INPUT_TOKEN_PRICE +
            output_tokens * OPENAI_OUTPUT_TOKEN_PRICE
        ) / 1_000_000

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost
        }

    except Exception as e:
        raise RuntimeError(f"Failed to call OpenAI API: {e}")
