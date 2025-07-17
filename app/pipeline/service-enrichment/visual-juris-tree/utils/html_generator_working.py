import json
import html
import re

class HtmlGenerator:
    """
    Generates an interactive HTML flowchart from a JuriTree JSON object.
    The generated HTML uses TailwindCSS for styling and is fully self-contained.
    """

    def __init__(self):
        """Initializes the generator with a color palette for borders."""
        self.color_palette = {
            'node-main-issue': {'border': '#FFA500'},
            'node-primary-branch': {'border': '#87CEFA'},
            'node-question': {'border': '#CF9FFF'},
            'node-fact': {'border': '#26F7FD'},
            'node-finding-no': {'border': '#90EE90'},
            'default': {'border': '#b0b0b0'}
        }

    def _get_text_color_for_bg(self, hex_color: str) -> str:
        """
        Determines if text should be black or white for good contrast against a given hex color background.
        """
        try:
            hex_color = hex_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            # Using the luminance formula to determine brightness
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return 'black' if luminance > 0.6 else 'white'
        except Exception:
            return 'black' # Default to black on error

    def _format_tooltip_text(self, text: str) -> str:
        """
        Finds patterns like 'Reason 1:' and makes them bold.
        """
        escaped_text = html.escape(text)
        formatted_text = re.sub(r'(Reason\s*\d*:)', r'<strong>\1</strong>', escaped_text, flags=re.IGNORECASE)
        return formatted_text

    def _render_node_html(self, node: dict) -> str:
        """
        Renders a single flowchart node into an HTML string.
        """
        if not node:
            return ""

        node_type = html.escape(node.get('type', ''))
        raw_title = node.get('title', '')
        
        tag_html = ""
        display_title = html.escape(raw_title)

        # --- MODIFICATION: Split title into tag and new title, and color tag ---
        if ':' in raw_title:
            parts = [part.strip() for part in raw_title.split(':', 1)]
            if len(parts) == 2 and parts[0] and parts[1]:  # Check for valid split
                tag_text, title_text = parts
                display_title = html.escape(title_text)

                # Get colors from palette based on node type
                colors = self.color_palette.get(node_type, self.color_palette['default'])
                bg_color = colors['border']
                text_color = self._get_text_color_for_bg(bg_color)
                
                # Create tag with inline style for dynamic coloring
                tag_html = f'<div class="node-tag" style="background-color: {bg_color}; color: {text_color};">{html.escape(tag_text)}</div>'
        # --- End Modification ---

        tooltip_data = node.get('tooltip', {})
        tooltip_what = self._format_tooltip_text(tooltip_data.get('what', ''))
        tooltip_who = self._format_tooltip_text(tooltip_data.get('who', ''))
        tooltip_why = self._format_tooltip_text(tooltip_data.get('why', ''))

        reference_data = node.get('reference', {})
        ref_text = html.escape(reference_data.get('refText', ''))
        ref_popup_text = html.escape(reference_data.get('refPopupText', ''))

        children_html = self._render_children_html(node.get('children', []))

        return f"""
        <div class="flowchart-node-wrapper">
            <div class="flowchart-node {node_type} w-full">
                {tag_html}
                <span>{display_title}</span>
                <div class="tooltip">
                    <div class="tooltip-item"><strong>What:</strong><br>{tooltip_what}</div>
                    <div class="tooltip-item"><strong>Who:</strong><br>{tooltip_who}</div>
                    <div class="tooltip-item"><strong>Why:</strong><br>{tooltip_why}</div>
                    <span class="tooltip-ref">
                        {ref_text}
                        <div class="ref-popup">{ref_popup_text}</div>
                    </span>
                </div>
            </div>
        </div>
        {children_html}
        """

    def _render_children_html(self, children: list) -> str:
        """
        Renders the children of a node, handling the layout and connectors.
        """
        if not children:
            return ""

        if len(children) > 1:
            branch_container_class = "flex flex-col md:flex-row gap-16 w-full"
            child_wrapper_class = "flex-1 flex flex-col items-center gap-10"
        else:
            branch_container_class = "flex flex-col items-center gap-10 w-full"
            child_wrapper_class = "w-full"

        child_branches = []
        for child in children:
            branch_content = self._render_node_html(child)
            child_branches.append(f'<div class="{child_wrapper_class}">{branch_content}</div>')

        return f"""
        <div class="w-px h-16 bg-gray-400"></div>
        <div class="{branch_container_class}">
            {''.join(child_branches)}
        </div>
        """

    def _render_branch_html(self, node: dict) -> str:
        """
        Renders a complete sub-branch, starting from a given node.
        """
        content = self._render_node_html(node)
        return f"""
        <div class="flowchart-sub-branch">
            {content}
        </div>
        """

    def generate_html_tree(self, json_data: dict) -> str:
        """
        Takes a dictionary parsed from the JuriTree JSON and returns a complete
        HTML string for the interactive flowchart.
        """
        flowchart_data = json_data.get('flowchart', {})
        title = html.escape(flowchart_data.get('title', 'JuriTree Flowchart'))
        subtitle = html.escape(flowchart_data.get('subtitle', ''))
        root_node = flowchart_data.get('rootNode')
        final_outcome = flowchart_data.get('finalOutcome')

        main_branches_html = ""
        if root_node and root_node.get('children'):
            branches = [self._render_branch_html(child) for child in root_node['children']]
            main_branches_html = ''.join(branches)

        node_style_rules = ""
        for node_type, colors in self.color_palette.items():
            node_style_rules += f".{node_type} {{ border-color: {colors['border']}; }}\n"

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}: {subtitle}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Poppins', sans-serif;
            background-color: #f0f2f5;
            color: black;
            overflow: auto;
        }}
        .viewport {{
            width: 100%; min-height: 100vh; cursor: grab; padding: 2rem;
        }}
        .zoom-container {{
            transition: transform 0.2s ease-out; transform-origin: center center;
        }}
        .flowchart-node-wrapper {{
            position: relative;
            margin-top: 20px; /* Make space for the tag */
        }}
        .flowchart-node {{
            border: 2px solid #b0b0b0; /* Default border */
            border-radius: 50px;
            padding: 0.75rem 1.25rem;
            text-align: center;
            position: relative;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
            cursor: pointer;
            font-size: 0.875rem;
            font-weight: 500;
            user-select: text;
            color: black;
            background-color: transparent;
        }}
        .flowchart-node.is-active {{
            z-index: 40;
        }}
        .flowchart-node:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.07), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }}
        
        {node_style_rules}

        /* MODIFICATION: Removed specific background/color, now handled by inline style */
        .node-tag {{
            position: absolute;
            top: -35px;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.25rem 0.85rem;
            border-radius: 9999px; /* Pill shape */
            font-size: 0.8rem;
            font-weight: 600;
            z-index: 5;
            white-space: nowrap;
            border: 1px solid rgba(0,0,0,0.1); /* Subtle border for definition */
        }}

        .node-question {{ transform: rotate(-2deg); }}
        .node-question:hover {{ transform: rotate(0deg) translateY(-4px); }}

        .tooltip {{
            visibility: hidden; opacity: 0;
            width: 320px;
            background-color: #E5E1E1;
            color: black;
            text-align: left; padding: 1rem; border-radius: 0.5rem;
            position: absolute; z-index: 50;
            bottom: 125%; left: 50%; margin-left: -160px;
            transition: opacity 0.3s, visibility 0.3s;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.1);
            pointer-events: none; user-select: text;
        }}
        .tooltip.is-visible {{
            visibility: visible; opacity: 1; pointer-events: auto;
        }}
        .tooltip::after {{
            content: ""; position: absolute;
            top: 100%; left: 50%; margin-left: -5px;
            border-width: 5px; border-style: solid;
            border-color: #E5E1E1 transparent transparent transparent;
        }}
        .tooltip.tooltip-below {{
            bottom: auto; top: 125%;
        }}
        .tooltip.tooltip-below::after {{
            top: auto; bottom: 100%; border-color: transparent transparent #E5E1E1 transparent;
        }}

        .tooltip-item {{ margin-bottom: 0.75rem; }}
        .tooltip-item strong {{ font-weight: 600; color: #1f2937; }}
        
        .tooltip-ref {{
            display: block; margin-top: 0.75rem; padding-top: 0.75rem;
            border-top: 1px solid #9ca3af;
            font-style: italic; color: #4b5563; font-size: 0.75rem;
            position: relative; cursor: help;
        }}
        
        .ref-popup {{
            visibility: hidden; opacity: 0;
            width: 350px;
            background-color: #E5E1E1;
            color: black;
            border: 1px solid #4b5563;
            text-align: left; padding: 1rem; border-radius: 0.375rem;
            position: absolute; z-index: 60; bottom: 0; left: 105%;
            transition: opacity 0.3s, visibility 0.3s;
            font-size: 0.8rem; line-height: 1.4; font-style: normal;
            box-shadow: 0 5px 10px rgba(0,0,0,0.3);
            pointer-events: none; user-select: text;
        }}
        .ref-popup.is-visible {{
            visibility: visible; opacity: 1; pointer-events: auto;
        }}

        .flowchart-sub-branch {{
             border-color: #d1d5db; gap: 4rem;
        }}
        .animate-in {{
            animation: fadeIn 1.2s ease-out forwards, slideUp 1.2s ease-out forwards;
        }}
        @keyframes fadeIn {{ to {{ opacity: 1; }} }}
        @keyframes slideUp {{ from {{ transform: translateY(30px); }} to {{ transform: translateY(0); }} }}
        .flowchart-container > * {{ opacity: 0; }}
    </style>
</head>
<body>
    <div id="viewport" class="viewport">
        <div id="zoom-container" class="zoom-container">
            <div class="flowchart-container">
                <div class="flowchart-level">
                    <div class="max-w-lg">
                        {self._render_node_html(root_node) if root_node else ''}
                    </div>
                </div>
                {"<div class='w-px h-16 bg-gray-400'></div>" if main_branches_html else ""}
                <div class="flowchart-level">
                    <div class="flowchart-branch w-full max-w-7xl">{main_branches_html}</div>
                </div>
                {"<div class='w-px h-16 bg-gray-400'></div>" if final_outcome else ""}
                <div class="flowchart-level">
                    <div class="max-w-lg">
                        {self._render_node_html(final_outcome) if final_outcome else ''}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Standard Javascript for panning, zooming, and popups. No changes needed here.
        document.addEventListener('DOMContentLoaded', () => {{{{
            const viewport = document.getElementById('viewport');
            const zoomContainer = document.getElementById('zoom-container');
            const allNodes = document.querySelectorAll('.flowchart-node');
            const allTooltips = document.querySelectorAll('.tooltip');
            const allRefPopups = document.querySelectorAll('.ref-popup');

            let scale = 1, panX = 0, panY = 0, isPanning = false, startX = 0, startY = 0;

            const updateTransform = () => {{
                zoomContainer.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{scale}})`;
            }};

            const closeAllPopups = () => {{
                allNodes.forEach(n => n.classList.remove('is-active'));
                allTooltips.forEach(t => t.classList.remove('is-visible', 'tooltip-below'));
                allRefPopups.forEach(p => p.classList.remove('is-visible'));
            }};

            viewport.addEventListener('wheel', (event) => {{
                if (!event.ctrlKey) return;
                event.preventDefault();
                const delta = event.deltaY > 0 ? -0.02 : 0.02;
                scale = Math.max(0.2, Math.min(3, scale + delta));
                updateTransform();
            }});

            viewport.addEventListener('mousedown', (event) => {{
                if (event.button !== 0 || event.target.closest('.flowchart-node-wrapper, .tooltip, .ref-popup')) return;
                isPanning = true;
                viewport.style.cursor = 'grabbing';
                startX = event.clientX - panX;
                startY = event.clientY - panY;
            }});

            viewport.addEventListener('mousemove', (event) => {{
                if (!isPanning) return;
                panX = event.clientX - startX;
                panY = event.clientY - startY;
                updateTransform();
            }});

            window.addEventListener('mouseup', () => {{
                if(isPanning) {{
                    isPanning = false;
                    viewport.style.cursor = 'grab';
                }}
            }});

            document.querySelectorAll('.flowchart-node-wrapper').forEach(wrapper => {{
                wrapper.addEventListener('click', (event) => {{
                    event.stopPropagation();
                    const node = wrapper.querySelector('.flowchart-node');
                    const tooltip = node.querySelector('.tooltip');
                    const isActive = tooltip.classList.contains('is-visible');
                    
                    closeAllPopups();

                    if (!isActive) {{
                        node.classList.add('is-active');
                        tooltip.classList.add('is-visible');
                        const rect = tooltip.getBoundingClientRect();
                        if (rect.top < 0) {{
                            tooltip.classList.add('tooltip-below');
                        }}
                    }}
                }});
            }});

            document.querySelectorAll('.tooltip-ref').forEach(ref => {{
                ref.addEventListener('click', (event) => {{
                    event.stopPropagation();
                    const refPopup = ref.querySelector('.ref-popup');
                    if (refPopup) refPopup.classList.toggle('is-visible');
                }});
            }});

            document.addEventListener('mousedown', (event) => {{
                 if (!event.target.closest('.flowchart-node-wrapper, .tooltip, .ref-popup')) {{
                    closeAllPopups();
                }}
            }});

            const elementsToAnimate = document.querySelectorAll('.flowchart-container > *');
            elementsToAnimate.forEach((el, index) => {{
                el.style.animationDelay = `${{index * 0.2}}s`;
                el.classList.add('animate-in');
            }});
        }}}});
    </script>
</body>
</html>
        """