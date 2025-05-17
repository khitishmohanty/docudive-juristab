import os
from openai import OpenAI
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def call_openai_api(prompt: str,
                    image_base64: Optional[str] = None,
                    model: Optional[str] = None) -> str:
    """
    Call OpenAI GPT-4o or similar multimodal model with optional image and prompt.

    Args:
        prompt (str): User prompt.
        image_base64 (Optional[str]): Base64 image input (optional).
        model (str): OpenAI model name (default from .env).

    Returns:
        str: Response text from the model.
    """
    model = model or OPENAI_MODEL

    try:
        # Build message payload
        messages: List[Dict] = [{"role": "user", "content": []}]

        if image_base64:
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })

        messages[0]["content"].append({
            "type": "text",
            "text": prompt
        })

        # Call the API using new OpenAI SDK
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )

        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"Failed to call OpenAI API: {e}")
