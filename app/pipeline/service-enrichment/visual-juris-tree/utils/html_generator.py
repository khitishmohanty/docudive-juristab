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
        """Determines if text should be black or white for good contrast."""
        try:
            hex_color = hex_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return 'black' if luminance > 0.6 else 'white'
        except Exception:
            return 'black'

    def _format_tooltip_text(self, text: str) -> str:
        """Finds patterns like 'Reason 1:' and makes them bold."""
        escaped_text = html.escape(text)
        formatted_text = re.sub(r'(Reason\s*\d*:)', r'<strong>\1</strong>', escaped_text, flags=re.IGNORECASE)
        return formatted_text

    def _render_node_html(self, node: dict, is_root: bool = False) -> str:
        """Renders a single flowchart node and its expandable children into an HTML string."""
        if not node:
            return ""

        node_id = html.escape(node.get('id', ''))
        node_type = html.escape(node.get('type', ''))
        raw_title = node.get('title', '')
        
        tag_html = ""
        display_title = html.escape(raw_title)

        if ':' in raw_title:
            parts = [part.strip() for part in raw_title.split(':', 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                tag_text, title_text = parts
                display_title = html.escape(title_text)
                colors = self.color_palette.get(node_type, self.color_palette['default'])
                bg_color = colors['border']
                text_color = self._get_text_color_for_bg(bg_color)
                tag_html = f'<div class="node-tag" style="background-color: {bg_color}; color: {text_color};">{html.escape(tag_text)}</div>'
        
        expander_html = ""
        children_html = ""
        if node.get('children'):
            expander_html = f'<div class="node-expander" data-node-id="{node_id}">+</div>'
            children_html = self._render_children_html(node.get('children', []), node.get('id', ''))
        
        wrapper_id = 'id="root-node-wrapper"' if is_root else ''

        tooltip_data = node.get('tooltip', {})
        tooltip_what = self._format_tooltip_text(tooltip_data.get('what', ''))
        tooltip_who = self._format_tooltip_text(tooltip_data.get('who', ''))
        tooltip_why = self._format_tooltip_text(tooltip_data.get('why', ''))

        reference_data = node.get('reference', {})
        ref_text = html.escape(reference_data.get('refText', ''))
        ref_popup_text = html.escape(reference_data.get('refPopupText', ''))

        return f"""
        <div {wrapper_id} class="flowchart-node-wrapper">
            <div class="flowchart-node {node_type}" data-node-id="{node_id}">
                {tag_html}
                <span>{display_title}</span>
                <div class="tooltip">
                    <div class="popup-close-btn">&times;</div>
                    <div class="tooltip-item"><strong>What:</strong><div class="tooltip-content">{tooltip_what}</div></div>
                    <div class="tooltip-item"><strong>Who:</strong><div class="tooltip-content">{tooltip_who}</div></div>
                    <div class="tooltip-item"><strong>Why:</strong><div class="tooltip-content">{tooltip_why}</div></div>
                    <span class="tooltip-ref">
                        {ref_text}
                        <div class="ref-popup">
                            <div class="popup-close-btn">&times;</div>
                            {ref_popup_text}
                        </div>
                    </span>
                </div>
                {expander_html}
            </div>
        </div>
        {children_html}
        """

    def _render_children_html(self, children: list, parent_id: str) -> str:
        """Renders the children of a node inside a collapsible container."""
        if not children:
            return ""

        is_main_branch = any(child.get('type') == 'node-primary-branch' for child in children)
        branch_container_class = "flex flex-row gap-16 w-full flowchart-branch" if is_main_branch else \
                                 ("flex flex-col md:flex-row gap-16 w-full" if len(children) > 1 else "flex flex-col items-center gap-10 w-full")

        child_wrapper_class = "flex-1 flex flex-col items-center gap-10" if len(children) > 1 else "w-full"

        child_branches = [f'<div class="{child_wrapper_class}">{self._render_node_html(child)}</div>' for child in children]
        
        return f"""
        <div class="node-children-container" id="children-of-{parent_id}">
            <div class="children-content">
                <div class="w-px h-16 bg-gray-400 mx-auto"></div>
                <div class="{branch_container_class}">
                    {''.join(child_branches)}
                </div>
            </div>
        </div>
        """

    def generate_html_tree(self, json_data: dict) -> str:
        """Generates the complete HTML string for the interactive flowchart."""
        flowchart_data = json_data.get('flowchart', {})
        title = html.escape(flowchart_data.get('title', 'JuriTree Flowchart'))
        subtitle = html.escape(flowchart_data.get('subtitle', ''))
        root_node = flowchart_data.get('rootNode')
        final_outcome = flowchart_data.get('finalOutcome')

        root_html = self._render_node_html(root_node, is_root=True) if root_node else ''
        final_outcome_html = self._render_node_html(final_outcome) if final_outcome else ''
        
        interstitial_connector = '<div class="w-px h-16 bg-gray-400 mx-auto"></div>' if root_html and final_outcome_html else ''

        node_style_rules = "".join([f".{node_type} {{ border-color: {colors['border']}; }}\n" for node_type, colors in self.color_palette.items()])
        
        # --- MODIFICATION: Separated JS into its own string to avoid f-string parsing errors ---
        javascript_code = """
        document.addEventListener('DOMContentLoaded', () => {
            const viewport = document.getElementById('viewport');
            const zoomContainer = document.getElementById('zoom-container');
            const expandAllToggle = document.getElementById('expand-all-toggle');
            const controlsContainer = document.getElementById('controls-container');

            const closeAllPopups = () => {
                document.querySelectorAll('.tooltip').forEach(t => {
                    t.classList.remove('is-visible', 'tooltip-below');
                    t.style.left = ''; t.style.right = ''; t.style.transform = '';
                });
                document.querySelectorAll('.ref-popup.is-visible').forEach(p => p.classList.remove('is-visible'));
                document.querySelectorAll('.overflow-visible-temp').forEach(el => el.classList.remove('overflow-visible-temp'));
                document.querySelectorAll('.is-active-node').forEach(n => n.classList.remove('is-active-node'));
            };
            
            const positionControls = () => {
                const rootNodeWrapper = document.getElementById('root-node-wrapper');
                if (!rootNodeWrapper || !controlsContainer) return;
                
                const rootRect = rootNodeWrapper.getBoundingClientRect();
                const viewportRect = viewport.getBoundingClientRect();
                
                const top = rootRect.top + (rootRect.height / 2) - (controlsContainer.offsetHeight / 2) - viewportRect.top;
                const left = rootRect.right + 15 - viewportRect.left;

                controlsContainer.style.top = `${top}px`;
                controlsContainer.style.left = `${left}px`;
                controlsContainer.classList.add('is-visible');
            };

            document.querySelectorAll('.popup-close-btn').forEach(btn => {
                btn.addEventListener('click', (event) => { event.stopPropagation(); closeAllPopups(); });
            });

            document.querySelectorAll('.node-expander').forEach(expander => {
                expander.addEventListener('click', (event) => {
                    event.stopPropagation();
                    const nodeId = expander.getAttribute('data-node-id');
                    const childrenContainer = document.getElementById(`children-of-${nodeId}`);
                    if (childrenContainer) {
                        childrenContainer.classList.toggle('is-expanded');
                        expander.textContent = childrenContainer.classList.contains('is-expanded') ? '−' : '+';
                    }
                });
            });

            document.querySelectorAll('.flowchart-node').forEach(node => {
                node.addEventListener('click', (event) => {
                    if (event.target.closest('.node-expander, .tooltip-ref, .popup-close-btn')) return;
                    const tooltip = node.querySelector(':scope > .tooltip');
                    if (tooltip.classList.contains('is-visible')) return;
                    closeAllPopups();
                    tooltip.classList.add('is-visible');
                    const rect = tooltip.getBoundingClientRect();
                    const viewportWidth = window.innerWidth;
                    if (rect.top < 0) tooltip.classList.add('tooltip-below');
                    if (rect.right > viewportWidth) {
                        tooltip.style.left = 'auto'; tooltip.style.right = '5px'; tooltip.style.transform = 'none';
                    } else if (rect.left < 0) {
                        tooltip.style.left = '5px'; tooltip.style.transform = 'none';
                    }
                    node.closest('.flowchart-node-wrapper').classList.add('is-active-node');
                    let parent = tooltip.parentElement;
                    while(parent) {
                        if (window.getComputedStyle(parent).overflow === 'hidden') parent.classList.add('overflow-visible-temp');
                        if (parent.id === 'zoom-container') break;
                        parent = parent.parentElement;
                    }
                });
            });

            document.querySelectorAll('.tooltip-ref').forEach(ref => {
                 ref.addEventListener('click', (event) => {
                    event.stopPropagation();
                    const refPopup = ref.querySelector('.ref-popup');
                    if (refPopup) refPopup.classList.toggle('is-visible');
                 });
            });
            
            document.querySelectorAll('.ref-popup').forEach(popup => {
                popup.addEventListener('click', (event) => { event.stopPropagation(); });
            });
            
            expandAllToggle.addEventListener('change', () => {
                const isExpanded = expandAllToggle.checked;
                document.querySelectorAll('.node-children-container').forEach(c => c.classList.toggle('is-expanded', isExpanded));
                document.querySelectorAll('.node-expander').forEach(e => e.textContent = isExpanded ? '−' : '+');
            });
            
            const setFlowchartWidth = () => {
                const contentContainer = document.getElementById('flowchart-content');
                const mainBranchContainer = contentContainer.querySelector('.flowchart-branch');
                if(mainBranchContainer) {
                    const fullWidth = mainBranchContainer.scrollWidth;
                    contentContainer.style.minWidth = (fullWidth + 50) + 'px';
                }
            };
            setFlowchartWidth();
            window.addEventListener('resize', () => {
                setFlowchartWidth();
                positionControls();
            });
            
            setTimeout(positionControls, 100);

            let scale = 1, panX = 0, panY = 0, isPanning = false, startX = 0, startY = 0;
            const updateTransform = () => { 
                zoomContainer.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`; 
                requestAnimationFrame(positionControls);
            };
            viewport.addEventListener('mousedown', (event) => {
                if (event.button !== 0 || event.target.closest('.flowchart-node-wrapper, .tooltip, #controls-container')) return;
                isPanning = true; viewport.style.cursor = 'grabbing';
                startX = event.clientX - panX; startY = event.clientY - panY;
            });
            window.addEventListener('mouseup', () => { isPanning = false; viewport.style.cursor = 'grab'; });
            viewport.addEventListener('mousemove', (event) => { if (!isPanning) return; panX = event.clientX - startX; panY = event.clientY - startY; updateTransform(); });
            viewport.addEventListener('wheel', (event) => {
                if (event.ctrlKey) {
                    event.preventDefault();
                    scale += event.deltaY > 0 ? -0.05 : 0.05; scale = Math.max(0.2, Math.min(2, scale)); updateTransform();
                }
            });
            document.addEventListener('mousedown', (event) => { if (!event.target.closest('.flowchart-node-wrapper, .tooltip, #controls-container')) closeAllPopups(); });
        });
        """

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}: {subtitle}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        html, body {{
            width: 100%; height: 100%; margin: 0; padding: 0;
        }}
        body {{ font-family: 'Poppins', sans-serif; background-color: #f0f2f5; color: black; }}
        .viewport {{ width: 100%; height: 100%; cursor: grab; overflow: auto; }}
        .zoom-container {{ display: inline-block; transition: transform 0.2s ease-out; transform-origin: top left; padding: 2rem; }}
        #flowchart-content {{ display: flex; flex-direction: column; align-items: center; width: 100%; }}
        .flowchart-node-wrapper {{ position: relative; margin-top: 20px; width: 100%; display: flex; justify-content: center;}}
        .flowchart-node-wrapper.is-active-node {{ z-index: 100; }}
        .flowchart-node {{
            border: 2px solid #b0b0b0; border-radius: 50px; padding: 0.75rem 1.25rem;
            text-align: center; position: relative; transition: all 0.3s ease; max-width: 500px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); cursor: pointer;
            font-size: 0.875rem; font-weight: 500; user-select: none;
            color: black; background-color: transparent; padding-bottom: 2rem;
        }}
        .flowchart-node:hover {{ transform: translateY(-4px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.07); }}
        {node_style_rules}
        .node-tag {{
            position: absolute; top: -35px; left: 50%; transform: translateX(-50%);
            padding: 0.25rem 0.85rem; border-radius: 9999px; font-size: 0.8rem;
            font-weight: 600; z-index: 5; white-space: nowrap; border: 1px solid rgba(0,0,0,0.1);
        }}
        .node-expander {{
            position: absolute; bottom: -12px; left: 50%; transform: translateX(-50%);
            width: 24px; height: 24px; background-color: #718096; color: white;
            border-radius: 50%; border: 2px solid white;
            font-size: 18px; font-weight: 600;
            z-index: 10; cursor: pointer;
            transition: background-color 0.2s;
            display: flex; align-items: center; justify-content: center;
            padding-bottom: 1px;
        }}
        .node-expander:hover {{ background-color: #2d3748; }}
        .node-children-container {{ display: grid; grid-template-rows: 0fr; transition: grid-template-rows 0.5s ease-in-out; overflow: hidden; }}
        .node-children-container.is-expanded {{ grid-template-rows: 1fr; }}
        .children-content {{ min-height: 0; opacity: 0; transition: opacity 0.4s ease-in-out 0.1s; padding-top: 40px; }}
        .node-children-container.is-expanded .children-content {{ opacity: 1; }}
        .tooltip {{
            visibility: hidden; opacity: 0; width: 320px;
            background-color: #F2F2F4; color: black;
            text-align: left; padding: 1rem; border-radius: 0.5rem;
            position: absolute; z-index: 50;
            bottom: 125%; left: 50%; transform: translateX(-50%);
            transition: opacity 0.3s; pointer-events: none;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.1);
            border: none; font-size: 0.8rem;
            user-select: text;
        }}
        .tooltip.tooltip-below {{ bottom: auto; top: 125%; }}
        .tooltip.is-visible {{ visibility: visible; opacity: 1; pointer-events: auto; }}
        .tooltip::after {{
            content: ""; position: absolute; top: 100%; left: 50%; margin-left: -5px;
            border-width: 5px; border-style: solid;
            border-color: #F2F2F4 transparent transparent transparent;
        }}
        .tooltip.tooltip-below::after {{ top: auto; bottom: 100%; border-color: transparent transparent #F2F2F4 transparent; }}
        .tooltip-item {{ margin-bottom: 0.75rem; }}
        .tooltip-item:last-of-type {{ margin-bottom: 0; }}
        .tooltip-item > strong {{ display: block; margin-bottom: 0.35rem; font-weight: 600; color: #1f2937; }}
        .tooltip-content {{ color: #958D8D; }}
        .tooltip-ref {{
            display: block; margin-top: 0.75rem; padding-top: 0.75rem;
            border-top: 1px solid #d1d5db; font-style: italic; color: #6B7280;
            position: relative; cursor: help;
        }}
        .ref-popup {{
             visibility: hidden; opacity: 0; width: 350px;
             background-color: #F2F2F4; color: #958D8D;
             border: none; box-shadow: 0 5px 10px rgba(0,0,0,0.2);
             text-align: left; padding: 1rem; border-radius: 0.375rem;
             position: absolute; z-index: 60; bottom: 0; left: 105%;
             transition: opacity 0.3s; font-size: 0.8rem; user-select: text;
        }}
        .ref-popup.is-visible {{ visibility: visible; opacity: 1; pointer-events: auto; }}
        .popup-close-btn {{
            position: absolute; top: 5px; right: 10px; width: 20px; height: 20px;
            font-size: 1.5rem; line-height: 20px; color: #aaa; text-align: center;
            cursor: pointer; transition: color 0.2s;
        }}
        .popup-close-btn:hover {{ color: #333; }}
        .overflow-visible-temp {{ overflow: visible !important; }}
        #controls-container {{
            position: absolute;
            top: -9999px; left: -9999px;
            z-index: 1000; display: flex; align-items: center; gap: 10px;
            transition: opacity 0.3s; opacity: 0;
        }}
        #controls-container.is-visible {{ opacity: 1; }}
        .toggle-switch-label {{ font-size: 14px; font-weight: 500; color: #808080; }}
        .toggle-switch {{ position: relative; display: inline-block; width: 50px; height: 28px; }}
        .toggle-switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #ccc; transition: .4s; border-radius: 28px;
        }}
        .slider:before {{
            position: absolute; content: ""; height: 20px; width: 20px;
            left: 4px; bottom: 4px; background-color: white;
            transition: .4s; border-radius: 50%;
        }}
        input:checked + .slider {{ background-color: #48BB78; }}
        input:checked + .slider:before {{ transform: translateX(22px); }}
    </style>
</head>
<body>
    <div id="controls-container">
        <label class="toggle-switch-label" for="expand-all-toggle">Expand All</label>
        <label class="toggle-switch">
            <input type="checkbox" id="expand-all-toggle">
            <span class="slider"></span>
        </label>
    </div>
    <div id="viewport" class="viewport">
        <div id="zoom-container" class="zoom-container">
            <div id="flowchart-content">
                <div class="w-full">{root_html}</div>
                {interstitial_connector}
                <div class="w-full">{final_outcome_html}</div>
            </div>
        </div>
    </div>
    <script>{javascript_code}</script>
</body>
</html>
        """