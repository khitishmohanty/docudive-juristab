import json

def load_config(path):
    print(f"Loading configuration from: {path}")
    try:
        with open(path, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Could not load or parse config file '{path}': {e}")
        return None