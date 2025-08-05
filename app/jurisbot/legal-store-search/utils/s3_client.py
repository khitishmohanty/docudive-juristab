import os
import yaml
import boto3
from botocore.exceptions import ClientError

def load_s3_config():
    """Loads and parses the config.yaml file from the config/ directory."""
    try:
        with open("config/config.yaml", "r") as f:
            config = yaml.safe_load(f)
            s3_config_map = {
                item['jurisdiction_code']: item for item in config.get('aws', {}).get('s3', [])
            }
            config['aws']['s3_map'] = s3_config_map
            return config
    except FileNotFoundError:
        print("Error: config/config.yaml not found.")
        return None
    except yaml.YAMLError as e:
        print(f"Error parsing config.yaml: {e}")
        return None

def fetch_document_from_s3(config, jurisdiction_code, source_id, file_key):
    """
    Fetches a specific document type from S3 based on a file key.

    Args:
        config (dict): The loaded configuration.
        jurisdiction_code (str): The jurisdiction code (e.g., 'NSW').
        source_id (str): The unique identifier for the document.
        file_key (str): The key for the filename in config (e.g., 'source_file', 'juris_map').

    Returns:
        str: The content of the HTML file, or an error message.
    """
    if not all([config, jurisdiction_code, source_id, file_key]):
        return "Error: Missing required information to fetch document."

    enrichment_files = config.get('enrichment_filenames', {})
    filename = enrichment_files.get(file_key)
    if not filename:
        return f"<h3>Configuration Error</h3><p>Filename for '{file_key}' not found in config.yaml.</p>"

    jurisdiction_config = config.get('aws', {}).get('s3_map', {}).get(jurisdiction_code)
    if not jurisdiction_config:
        return f"<h3>Configuration Error</h3><p>No S3 config for jurisdiction '{jurisdiction_code}'.</p>"

    bucket_name = jurisdiction_config.get('bucket_name')
    folder_name = jurisdiction_config.get('folder_name')
    s3_key = f"{folder_name}/{source_id}/{filename}"

    print(f"Attempting to fetch: s3://{bucket_name}/{s3_key}")

    try:
        s3_client = boto3.client('s3', region_name=config['aws'].get('default_region', 'ap-southeast-2'))
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        html_content = response['Body'].read().decode('utf-8')

        # --- UPDATE: Conditionally inject Poppins font only for the main content view ---
        if file_key == 'source_file':
            font_style_tag = """
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500&display=swap" rel="stylesheet">
            <style> body {{ font-family: 'Poppins', sans-serif !important; }} </style>
            """
            # Inject the font styles into the head of the document
            if '</head>' in html_content:
                return html_content.replace('</head>', f'{font_style_tag}</head>')
            else:
                # If no <head> tag, create one to inject the styles
                return f'<html><head>{font_style_tag}</head><body>{html_content}</body></html>'
        
        # For all other files, return the original content
        return html_content

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return f"<div style='padding: 20px; text-align: center;'><h3>File Not Found</h3><p>This file has not been processed yet.</p></div>"
        else:
            print(f"An AWS ClientError occurred: {e}")
            return f"<h3>Error</h3><p>An AWS error occurred: {e.response['Error']['Message']}</p>"
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return f"<h3>Error</h3><p>An unexpected error occurred: {e}</p>"