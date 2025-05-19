import os
import imghdr  # ⬅️ Add this
from openai import OpenAI
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

client = OpenAI(api_key=OPENAI_API_KEY)

def call_openai_api(prompt: str,
                    image_base64: Optional[str] = None,
                    model: Optional[str] = None,
                    image_path: Optional[str] = None) -> str:  # ⬅️ New param for MIME type check
    model = model or OPENAI_MODEL

    try:
        # Determine MIME type based on file content
        mime_type = "image/jpeg"  # Default
        if image_path and os.path.isfile(image_path):
            ext = imghdr.what(image_path)
            if ext == "png":
                mime_type = "image/png"
            elif ext == "gif":
                mime_type = "image/gif"
            elif ext == "webp":
                mime_type = "image/webp"
            elif ext == "jpeg":
                mime_type = "image/jpeg"
            else:
                raise ValueError(f"Unsupported image format detected: {ext}")

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

        response = client.chat.completions.create(
            model=model,
            messages=messages
        )

        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"Failed to call OpenAI API: {e}")
