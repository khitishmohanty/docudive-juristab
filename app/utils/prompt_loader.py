from pathlib import Path

def load_prompt(filename: str) -> str:
    # Dynamically locate the project root
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent  # this removes the extra 'app/'

    # Corrected path to app/prompts/
    prompt_path = project_root / "prompts" / filename

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()
