import requests

# IMPORTANT: Replace this with your actual API endpoint URL
API_ENDPOINT = "https://discoveryengine.googleapis.com/v1alpha/projects/534929033323/locations/global/collections/default_collection/engines/juristab-legal-store-searc_1754363845002/servingConfigs/default_search:search"

def perform_search(query: str, access_token: str):
    """
    Performs a search against the Vertex AI Search API.

    Args:
        query (str): The search term from the user.
        access_token (str): The GCP access token for authentication.

    Returns:
        dict: The JSON response from the API, or an error dictionary.
    """
    if not query:
        return {"error": "Query cannot be empty."}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # This is the JSON payload for the search request.
    # We are requesting snippets and a max of 20 results.
    data = {
        "query": query,
        "pageSize": 20,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "contentSearchSpec": {
            "summarySpec": {
                "summaryResultCount": 5,
                "includeCitations": True
            },
            "snippetSpec": {
                "returnSnippet": True
            },
            "extractiveContentSpec": {
                "maxExtractiveAnswerCount": 3
            }
        }
    }

    try:
        response = requests.post(API_ENDPOINT, headers=headers, json=data, timeout=20)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        # Try to get more specific error info from the response body
        error_details = response.json() if response.content else {}
        return {"error": f"HTTP error occurred: {http_err}", "details": error_details}
    except requests.exceptions.RequestException as req_err:
        return {"error": f"A request error occurred: {req_err}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}

