import dash
from dash import dcc, html, Input, Output, State, ALL, no_update
import dash_bootstrap_components as dbc
import json
import re

from dotenv import load_dotenv
load_dotenv()

from utils.auth import get_gcp_token
from src.search_client import perform_search
from utils.s3_client import load_s3_config, fetch_document_from_s3

S3_CONFIG = load_s3_config()

POPPINS_FONT = "https://fonts.googleapis.com/css2?family=Poppins:wght@400;500&display=swap"
FONT_AWESOME = "https://use.fontawesome.com/releases/v5.15.4/css/all.css"

app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.LUX, POPPINS_FONT, FONT_AWESOME],
    suppress_callback_exceptions=True
)
server = app.server

app.layout = dbc.Container([
    dcc.Store(id='selected-doc-store', data=None),

    dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Searching...")),
            dbc.ModalBody(
                html.Div([
                    dbc.Spinner(size="lg", color="primary", spinner_style={"width": "3rem", "height": "3rem"}),
                    html.Div("Processing your query and generating a summary. Please wait.", className="mt-2")
                ], className="text-center")
            ),
        ],
        id="loading-modal",
        is_open=False,
        centered=True,
        backdrop="static",
        keyboard=False,
    ),

    html.H1(
        [
            html.Span("JurisTab", style={'color': '#003366'}),
            html.Span(" Legal Store", style={'color': '#6c757d'})
        ],
        className="my-4 text-center",
        style={'textTransform': 'none'}
    ),
    
    dbc.Row([
        dbc.Col(
            dcc.Input(
                id='search-input', type='text',
                placeholder='e.g., cases handled by Mills Oakley',
                style={'borderRadius': '30px', 'border': '1px solid #ced4da', 'height': '40px'},
                className='form-control me-2', n_submit=0
            ), width=8
        ),
        dbc.Col(
            html.Button('Search', id='search-button', n_clicks=0, 
                style={
                    'backgroundColor': '#003366', 'color': 'white', 
                    'borderRadius': '30px', 'border': 'none', 
                    'padding': '0 30px', 'height': '40px'
                }),
            width=4, className="d-flex"
        )
    ], className="mb-4 justify-content-center"),

    html.Div(
        id='search-content-container',
        style={'display': 'none'},
        children=[
            html.Hr(),
            dbc.Row([
                dbc.Col(
                    dcc.Loading(
                        id="loading-spinner", type="circle", color="primary",
                        children=html.Div(id="results-output", style={'maxHeight': '80vh', 'overflowY': 'auto', 'paddingRight': '15px'})
                    ), md=5
                ),
                dbc.Col(
                    html.Div([
                        dbc.Tabs(
                            id="doc-tabs",
                            active_tab="content-tab",
                            children=[
                                dbc.Tab(label="Content", tab_id="content-tab"),
                                dbc.Tab(label="Juris Map", tab_id="juris-map-tab"),
                                dbc.Tab(label="Juris Tree", tab_id="juris-tree-tab"),
                                dbc.Tab(label="Summary", tab_id="juris-summary-tab"),
                                dbc.Tab(label="Juris Link", tab_id="juris-link-tab"),
                            ],
                        ),
                        dcc.Loading(
                            id="loading-viewer", type="circle", color="primary",
                            children=html.Div(id="tab-content", className="p-2")
                        )
                    ], style={"height": "80vh", "border": "1px solid #e0e0e0", "borderRadius": "5px"}),
                    md=7
                )
            ])
        ]
    )
], fluid=True, className="p-5", style={'fontFamily': "'Poppins', sans-serif"})

def format_results(response_json):
    """Helper function to format the API response into clickable result cards."""
    if not response_json or ("results" not in response_json and "summary" not in response_json):
        return dbc.Alert("An error occurred or the search returned no results.", color="danger")

    summary_card = []
    if response_json.get("summary", {}).get("summaryText"):
        summary_text = response_json["summary"]["summaryText"]
        references = response_json.get("summary", {}).get("summaryWithMetadata", {}).get("references", [])
        results = response_json.get("results", [])
        doc_id_map = {result['document']['id']: result['document'] for result in results if 'document' in result}

        def create_citation_link(citation_num_str):
            try:
                citation_index = int(citation_num_str) - 1
                if 0 <= citation_index < len(references):
                    doc_resource_name = references[citation_index].get('document', '')
                    doc_id = doc_resource_name.split('/')[-1]
                    if doc_id in doc_id_map:
                        doc_struct_data = doc_id_map[doc_id].get('structData', {})
                        source_id = doc_struct_data.get('source_id')
                        jurisdiction_code = doc_struct_data.get('jurisdiction_code')
                        if source_id and jurisdiction_code:
                            return html.Span(
                                citation_num_str,
                                id={'type': 'view-doc-button', 'index': f'summary-ref-{citation_index}', 'source_id': source_id, 'jurisdiction_code': jurisdiction_code},
                                style={'cursor': 'pointer', 'color': '#003366', 'textDecoration': 'underline', 'fontWeight': '500'},
                                title=f"View source document: {doc_id}"
                            )
            except (ValueError, IndexError) as e:
                print(f"Error creating citation link for '{citation_num_str}': {e}")
            return citation_num_str
        
        def render_text_with_markdown(text_segment):
            pattern = re.compile(r'(\*.*?\*)')
            parts = pattern.split(text_segment)
            components = []
            for part in parts:
                if not part: continue
                if part.startswith('*') and part.endswith('*'):
                    components.append(html.Strong(part[1:-1]))
                else:
                    components.append(part)
            return components

        summary_body_components = []
        citation_pattern = re.compile(r'(\[[\d,\s]+\])')
        
        for paragraph in summary_text.strip().split('\n\n'):
            if not paragraph: continue
            
            paragraph_components = []
            text_parts = citation_pattern.split(paragraph)
            for part in text_parts:
                if not part: continue
                match = citation_pattern.fullmatch(part)
                if match:
                    citation_numbers = match.group(1).strip('[]').split(',')
                    linked_citations = []
                    for num_str in citation_numbers:
                        num_str = num_str.strip()
                        if num_str:
                            linked_citations.append(create_citation_link(num_str))
                    
                    final_citation_block = []
                    for i, link in enumerate(linked_citations):
                        if i > 0: final_citation_block.append(", ")
                        final_citation_block.append(link)
                    
                    paragraph_components.append("[")
                    paragraph_components.extend(final_citation_block)
                    paragraph_components.append("]")
                else:
                    paragraph_components.extend(render_text_with_markdown(part))
            
            summary_body_components.append(html.P(paragraph_components, className="card-text"))

        summary_card = [
            html.Div([
                html.H5(
                    [
                        "Summary ",
                        html.I(className="fas fa-chevron-down", id="summary-toggle-icon")
                    ],
                    id="summary-collapse-button",
                    className="mb-2",
                    style={'cursor': 'pointer', 'color': '#6c757d', 'textTransform': 'none'}
                ),
                dbc.Collapse(
                    dbc.Card(
                        dbc.CardBody(summary_body_components),
                        className="border-0 bg-transparent p-0",
                    ),
                    id="summary-collapse",
                    is_open=False,
                )
            ])
        ]

    if not response_json.get("results"):
        if summary_card: return summary_card
        return dbc.Alert("No results found for your query.", color="info")

    result_cards = []
    for i, result in enumerate(response_json["results"]):
        doc = result.get('document', {})
        struct_data = doc.get('structData', {})
        
        book_name = struct_data.get('book_name', 'No Title Available')
        neutral_citation = struct_data.get('neutral_citation')
        source_id = struct_data.get('source_id')
        jurisdiction_code = struct_data.get('jurisdiction_code')
        is_disabled = not (source_id and jurisdiction_code)

        heading_div = html.Div(
            [
                html.Span(
                    neutral_citation,
                    style={'backgroundColor': '#e9ecef', 'color': 'black', 'padding': '0.2rem 0.4rem', 'borderRadius': '4px', 'marginRight': '8px', 'fontSize': '0.9rem'}
                ) if neutral_citation else None,
                html.Span(book_name, style={'color': 'black', 'fontSize': '0.9rem'})
            ],
            id={'type': 'view-doc-button', 'index': i, 'source_id': source_id or '', 'jurisdiction_code': jurisdiction_code or ''},
            style={'cursor': 'pointer' if not is_disabled else 'not-allowed'},
            className='mb-2'
        )
        
        content_preview = []
        full_content = struct_data.get('content')
        if full_content:
            words = full_content.split()
            preview_text = " ".join(words[:30]) + ("..." if len(words) > 30 else "")
            # --- UPDATED: Added style for smaller font size ---
            content_preview.append(html.P(preview_text, className="card-text", style={'fontSize': '0.9rem'}))
        else:
            content_preview.append(html.P("No preview available.", className="card-text", style={'fontSize': '0.9rem'}))
        
        card = dbc.Card(dbc.CardBody([heading_div] + content_preview), className="mb-3")
        result_cards.append(card)

    return summary_card + result_cards

@app.callback(
    Output("summary-collapse", "is_open"),
    Output("summary-toggle-icon", "className"),
    [Input("summary-collapse-button", "n_clicks")],
    [State("summary-collapse", "is_open")],
    prevent_initial_call=True,
)
def toggle_summary_collapse(n_clicks, is_open):
    if not n_clicks:
        return no_update, no_update
    
    new_state = not is_open
    icon_class = "fas fa-chevron-up" if new_state else "fas fa-chevron-down"
    return new_state, icon_class

@app.callback(
    Output('selected-doc-store', 'data'),
    Output('doc-tabs', 'active_tab'),
    Input({'type': 'view-doc-button', 'index': ALL, 'source_id': ALL, 'jurisdiction_code': ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def store_selected_document(n_clicks):
    if not any(n_clicks): return no_update, no_update
    ctx = dash.callback_context
    button_id = ctx.triggered_id
    doc_data = {'source_id': button_id['source_id'], 'jurisdiction_code': button_id['jurisdiction_code']}
    return doc_data, 'content-tab'

@app.callback(
    Output('tab-content', 'children'),
    Input('doc-tabs', 'active_tab'),
    Input('selected-doc-store', 'data')
)
def update_tab_content(active_tab, stored_data):
    if not stored_data:
        return html.Div("Please select a document from the search results.", className="p-3 text-center")
    source_id = stored_data['source_id']
    jurisdiction_code = stored_data['jurisdiction_code']
    if active_tab == 'juris-link-tab':
        return html.Div("Juris Link content will be available in a future update.", className="p-3 text-center")
    tab_to_file_key = {
        'content-tab': 'source_file',
        'juris-map-tab': 'juris_map',
        'juris-tree-tab': 'juris_tree',
        'juris-summary-tab': 'juris_summary'
    }
    file_key = tab_to_file_key.get(active_tab)
    if not file_key: return "Invalid tab selected."
    html_content = fetch_document_from_s3(S3_CONFIG, jurisdiction_code, source_id, file_key)
    return html.Iframe(srcDoc=html_content, style={"width": "100%", "height": "70vh", "border": "none"})

@app.callback(
    Output('loading-modal', 'is_open'),
    [Input('search-button', 'n_clicks'), Input('search-input', 'n_submit')],
    [State('search-input', 'value')],
    prevent_initial_call=True
)
def open_loading_modal(n_clicks, n_submit, query):
    triggered = dash.callback_context.triggered_id
    if triggered and query:
        return True
    return no_update

@app.callback(
    Output('results-output', 'children'),
    Output('loading-modal', 'is_open', allow_duplicate=True),
    Output('search-content-container', 'style'),
    [Input('search-button', 'n_clicks'), Input('search-input', 'n_submit')],
    [State('search-input', 'value')],
    prevent_initial_call=True
)
def update_search_results(n_clicks, n_submit, query):
    """Performs the search and updates the results panel and its visibility."""
    triggered = dash.callback_context.triggered_id
    if not triggered or not query:
        return "", False, no_update
    
    try:
        access_token = get_gcp_token()
        response_json = perform_search(query, access_token)
        return format_results(response_json), False, {'display': 'block'}
    except Exception as e:
        return dbc.Alert(f"An application error occurred: {e}", color="danger"), False, {'display': 'block'}

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8081)