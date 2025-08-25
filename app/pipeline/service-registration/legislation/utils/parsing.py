import logging
import re
import yaml
import pandas as pd
from datetime import datetime

def load_config(path='config/config.yaml'):
    """
    Loads the main YAML configuration file.
    """
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {path}")
        return None
    except Exception as e:
        logging.error(f"Error loading YAML configuration from {path}: {e}")
        return None

def load_json_config(path):
    """
    Loads a JSON configuration file into a pandas DataFrame.
    """
    try:
        return pd.read_json(path, orient='records')
    except FileNotFoundError:
        logging.error(f"JSON config file not found at {path}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"Error loading JSON config from {path}: {e}")
        return pd.DataFrame()

def parse_legislation_context(context_str):
    """
    Parses the book_context string for legislation to extract the start date.
    Example context: "Start date: 08/08/2025"
    
    Args:
        context_str (str): The string from the book_context column.

    Returns:
        dict: A dictionary containing the parsed 'start_date' or None.
    """
    details = {'start_date': None}
    if not context_str:
        logging.warning("Received empty context string.")
        return details

    # Search for the date pattern following "Start date:"
    match = re.search(r'Start date:\s*(\d{2}/\d{2}/\d{4})', context_str, re.IGNORECASE)
    
    if match:
        date_str = match.group(1)
        try:
            # Convert the extracted date string to a date object
            details['start_date'] = datetime.strptime(date_str, '%d/%m/%Y').date()
            logging.info(f"Successfully parsed start date: {details['start_date']}")
        except ValueError:
            logging.warning(f"Could not parse date '{date_str}' from context: {context_str}")
    else:
        logging.warning(f"Could not find 'Start date:' pattern in context: {context_str}")

    return details
