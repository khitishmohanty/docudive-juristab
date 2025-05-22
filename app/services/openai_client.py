import os
import imghdr
import json
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


def call_openai_with_json(json_file_path: str, prompt: str, model: Optional[str] = None) -> Dict:

    try:
        # Load JSON content and format as string
        with open(json_file_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            json_text = json.dumps(json_data, indent=2)

        # Create full prompt
        combined_prompt = f"{prompt}\n\nHere is the JSON input:\n{json_text}"

        # Use existing function to call OpenAI and calculate cost
        return call_openai_api(prompt=combined_prompt, model=model)

    except Exception as e:
        raise RuntimeError(f"Failed to call OpenAI API with JSON input: {e}")