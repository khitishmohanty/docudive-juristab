from bs4 import BeautifulSoup, NavigableString
import re

class HtmlParser:
    """ A utility class to parse and manipulate HTML content. """
    
    def extract_text(self, html_content: str) -> str:
        """
        Extracts plain text from the given HTML content.

        Args:
            html_content (str): The HTML content to parse.

        Returns:
            str: The extracted text, with tags removed.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)

    def _build_hierarchy(self, content_root):
        """Builds a nested list data structure from the flat source HTML."""
        if not content_root:
            return [], "Document"

        # Try to find a title for the document
        first_header = content_root.find('block', class_='section-header')
        title = "Document"
        if first_header:
            name_tag = first_header.find('inline', class_='section-name')
            if name_tag:
                title = name_tag.get_text(strip=True)

        hierarchy = []
        parent_stack = []
        id_counters = {}

        for element in content_root.find_all(recursive=False):
            if element.name == 'block' and 'section-header' in element.get('class', []):
                level_match = re.search(r'section-level-(\d+)', ' '.join(element.get('class', [])))
                level = int(level_match.group(1)) if level_match else 1

                # Generate a unique, hierarchical ID
                if level > len(id_counters):
                    id_counters[level] = 1
                else:
                    id_counters[level] += 1
                # Reset counters for deeper levels
                for l in range(level + 1, len(id_counters) + 1):
                    id_counters[l] = 0
                
                id_parts = [str(id_counters.get(i, 0)) for i in range(1, level + 1)]
                unique_id = f"section-{''.join(id_parts)}"

                node = {
                    'id': unique_id,
                    'level': level,
                    'heading_tag': element,
                    'content_tags': [],
                    'children': []
                }

                while parent_stack and parent_stack[-1]['level'] >= level:
                    parent_stack.pop()

                if parent_stack:
                    parent_stack[-1]['children'].append(node)
                else:
                    hierarchy.append(node)
                
                parent_stack.append(node)
            elif parent_stack:
                parent_stack[-1]['content_tags'].append(element)
        
        return hierarchy, title

    def _generate_toc_html(self, soup, nodes):
        """Recursively generates the Table of Contents HTML."""
        if not nodes:
            return None
        
        ul = soup.new_tag('ul')
        for node in nodes:
            li = soup.new_tag('li')
            a = soup.new_tag('a', href=f"#{node['id']}")
            
            # Clean up heading text for TOC display
            heading_text_parts = [tag.get_text(strip=True) for tag in node['heading_tag'].find_all('inline')]
            a.string = ' '.join(filter(None, heading_text_parts)) or "Untitled Section"
            
            li.append(a)
            
            if node['children']:
                # Add class to the LI if it has children, making it collapsible
                li['class'] = 'toc-collapsible'
                li.append(self._generate_toc_html(soup, node['children']))
            
            ul.append(li)
        return ul

    def _generate_main_content_html(self, soup, nodes):
        """Recursively generates the main content area HTML."""
        container = soup.new_tag('div')
        for node in nodes:
            # The collapsible header div
            header_div = soup.new_tag('div', attrs={
                'class': f"collapsible level-{node['level']}",
                'id': node['id']
            })
            # Add the original heading content inside the header
            header_div.extend(node['heading_tag'].contents)
            container.append(header_div)

            # The content div that gets toggled
            content_div = soup.new_tag('div', attrs={'class': 'content'})
            
            # Add associated content (paragraphs, lists, etc.)
            for content_tag in node['content_tags']:
                content_div.append(content_tag)
                
            # Recursively add children's content
            if node['children']:
                content_div.append(self._generate_main_content_html(soup, node['children']))
            
            container.append(content_div)
            
        return container


    def create_juriscontent_html(self, html_content: str) -> str:
        """
        Creates a styled, hierarchical, and collapsible HTML file with a two-panel layout.
        This function transforms the source HTML into a structured, interactive view.

        Args:
            html_content (str): The original HTML content.

        Returns:
            str: The modified and styled HTML as a string.
        """
        # 1. Pre-process the HTML to robustly find the content root
        content_root = None
        # Use regex to find content within the <doc> tag, as BeautifulSoup struggles with the malformed source
        match = re.search(r'<doc class="akbn-root">(.*?)</doc>', html_content, re.DOTALL)
        if match:
            inner_html = match.group(1)
            # Parse only the extracted, relevant HTML
            content_soup = BeautifulSoup(inner_html, 'html.parser')
            # The content_root is now the body of this new, clean soup object
            content_root = content_soup.body
            
        hierarchy, title = self._build_hierarchy(content_root)
        
        # 2. Create the new, final HTML document from the template
        final_soup = BeautifulSoup(f"""
            <!DOCTYPE html><html lang="en"><head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Collapsible Hierarchical View</title>
                <script src="https://cdn.tailwindcss.com"></script>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    body {{ font-family: 'Inter', sans-serif; background-color: #ffffff; overflow: hidden; }}
                    .main-container {{ display: flex; position: relative; }}
                    #toc-panel {{ width: 300px; flex-shrink: 0; background-color: #ffffff; border-right: 1px solid #e5e7eb; transition: width 0.3s ease-in-out; overflow: hidden; font-size: 14px; }}
                    .main-container.toc-collapsed #toc-panel {{ width: 0; }}
                    #toc-content {{ padding: 1.5rem; height: 100vh; overflow-y: auto; white-space: normal; }}
                    #toc-toggle {{ position: absolute; top: 1rem; left: 300px; transform: translateX(-50%); z-index: 10; background-color: #fff; border: 1px solid #e5e7eb; border-radius: 50%; width: 2.5rem; height: 2.5rem; display: flex; align-items: center; justify-content: center; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: left 0.3s ease-in-out; }}
                    .main-container.toc-collapsed #toc-toggle {{ left: 1.25rem; transform: translateX(0); }}
                    #toc-toggle svg {{ transition: transform 0.3s ease-in-out; }}
                    .main-container.toc-collapsed #toc-toggle svg {{ transform: rotate(180deg); }}
                    #toc-list a {{ text-decoration: none; color: #374151; display: block; padding: 0.25rem 0.5rem; border-radius: 0.375rem; }}
                    #toc-list ul {{ padding-left: 1rem; }}
                    #toc-list li.toc-collapsible > ul {{ display: none; }}
                    #toc-list li.toc-collapsible.active > ul {{ display: block; }}
                    #toc-list li.toc-collapsible > a {{ position: relative; }}
                    #toc-list li.toc-collapsible > a::before {{
                        content: '\\203A';
                        position: absolute;
                        left: -0.75rem;
                        top: 50%;
                        transform: translateY(-50%) rotate(0deg);
                        transition: transform 0.2s ease-in-out;
                        font-weight: bold;
                    }}
                    #toc-list li.toc-collapsible.active > a::before {{
                        transform: translateY(-50%) rotate(90deg);
                    }}
                    #main-content {{ flex-grow: 1; padding: 2rem; overflow-y: auto; height: 100vh; font-family: 'Poppins', sans-serif; font-size: 14px; }}
                    .collapsible {{ cursor: pointer; transition: background-color 0.3s ease; padding: 0.5rem; border-radius: 0.25rem;}}
                    .content {{
                        overflow: hidden;
                        padding-left: 2rem;
                        max-height: 0;
                        transition: max-height 0.3s ease-out;
                    }}
                    .content.no-transition {{
                        transition: none !important;
                    }}
                    .collapsible::before {{ content: '\\203A'; color: #6b7280; display: inline-block; margin-right: 0.5rem; transition: transform 0.3s ease; font-weight: bold; font-size: 1.25em; line-height: 1; }}
                    .collapsible.active::before {{ transform: rotate(90deg); }}
                    .level-1 {{ margin-left: 0; }} .level-2 {{ margin-left: 1.5rem; }} .level-3 {{ margin-left: 3rem; }} .level-4 {{ margin-left: 4.5rem; }} .level-5 {{ margin-left: 6rem; }}
                    .content p, .content ul, .content block {{ margin-left: 0; padding-left: 0; }}
                    .content .subclause, .content ul li {{ display: block; position: relative; padding-left: 2.5em; margin-bottom: 0.5rem; }}
                    .content .subclause > .number, .content ul li > .li-label {{ position: absolute; left: 0; top: 0; width: 2.5em; text-align: left; }}
                    .content .subclause > p, .content ul li > p {{ margin: 0; }}
                    /* Table Styles */
                    .content table {{
                        width: 100%;
                        border-collapse: collapse;
                        margin-top: 1rem;
                        margin-bottom: 1rem;
                    }}
                    .content th, .content td {{
                        border: 1px solid #d1d5db; /* Light grey gridlines */
                        padding: 0.5rem 0.75rem;
                        text-align: left;
                    }}
                    .content th, .content thead td {{
                        font-weight: 600;
                    }}
                </style></head><body class="text-gray-800">
                <div class="main-container">
                    <div id="toc-panel">
                        <div id="toc-content">
                            <h2 class="text-xl font-bold mb-4">Navigator</h2>
                            <div id="toc-list"></div>
                        </div>
                    </div>
                    <button id="toc-toggle" title="Toggle Table of Contents">
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
                    </button>
                    <div id="main-content">
                        <div class="max-w-4xl mx-auto p-6">
                            <div id="output"></div>
                        </div>
                    </div>
                </div>
                <script>
                    document.addEventListener('DOMContentLoaded', function () {{
                        const mainContainer = document.querySelector('.main-container');
                        const tocToggle = document.getElementById('toc-toggle');
                        tocToggle.addEventListener('click', () => {{ mainContainer.classList.toggle('toc-collapsed'); }});
                        
                        document.body.addEventListener('click', function(event) {{
                            // Handles collapsing for the main content panel
                            const collapsible = event.target.closest('.collapsible');
                            if (collapsible) {{
                                collapsible.classList.toggle('active');
                                const content = collapsible.nextElementSibling;
                                const isOpening = !(content.style.maxHeight && content.style.maxHeight !== '0px');

                                // Find all open parent content elements
                                const parents = [];
                                let parent = content.parentElement.closest('.content');
                                while(parent) {{
                                    if (parent.style.maxHeight && parent.style.maxHeight !== '0px') {{
                                        parents.push(parent);
                                    }}
                                    parent = parent.parentElement.closest('.content');
                                }}

                                // Add class to disable parent transitions, forcing them to snap
                                parents.forEach(p => p.classList.add('no-transition'));
                                
                                if (isOpening) {{
                                    const childHeight = content.scrollHeight;
                                    // Instantly resize parents to make room
                                    parents.forEach(p => {{
                                        p.style.maxHeight = (parseInt(p.style.maxHeight, 10) + childHeight) + 'px';
                                    }});
                                    // Animate the child
                                    content.style.maxHeight = childHeight + 'px';
                                }} else {{
                                    const childHeight = content.scrollHeight;
                                    // Instantly resize parents
                                    parents.forEach(p => {{
                                        p.style.maxHeight = Math.max(0, (parseInt(p.style.maxHeight, 10) - childHeight)) + 'px';
                                    }});
                                    // Animate the child
                                    content.style.maxHeight = '0px';
                                }}

                                // Remove the class to re-enable transitions after the browser has repainted
                                setTimeout(() => {{
                                    parents.forEach(p => p.classList.remove('no-transition'));
                                }}, 50);
                            }}

                            // Handles link clicks in the Table of Contents
                            const tocLink = event.target.closest('#toc-list a');
                            if (tocLink) {{
                                event.preventDefault();
                                const parentLi = tocLink.parentElement;

                                // Toggle the active class on the parent LI if it's collapsible
                                if (parentLi.classList.contains('toc-collapsible')) {{
                                    parentLi.classList.toggle('active');
                                }}
                                
                                const targetId = tocLink.getAttribute('href').substring(1);
                                const targetElement = document.getElementById(targetId);

                                if (targetElement) {{
                                    // Expand all parent sections of the target element in the main content
                                    let parent = targetElement.closest('.content');
                                    while(parent) {{
                                        const parentCollapsible = parent.previousElementSibling;
                                        if (parentCollapsible && parentCollapsible.classList.contains('collapsible') && !parentCollapsible.classList.contains('active')) {{
                                            parentCollapsible.click();
                                        }}
                                        parent = parent.parentElement.closest('.content');
                                    }}
                                    
                                    // Ensure the target itself is expanded if it's also a collapsible
                                    if(targetElement.classList.contains('collapsible') && !targetElement.classList.contains('active')){{
                                        targetElement.click();
                                    }}
                                    
                                    targetElement.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                                }}
                            }}
                        }});
                    }});
                </script></body></html>
            """, 'html.parser')

        # 3. Generate and insert the Table of Contents
        toc_list_div = final_soup.find('div', id='toc-list')
        toc_html = self._generate_toc_html(final_soup, hierarchy)
        if toc_html:
            toc_list_div.append(toc_html)

        # 4. Generate and insert the main collapsible content
        output_div = final_soup.find('div', id='output')
        main_content_html = self._generate_main_content_html(final_soup, hierarchy)
        if main_content_html:
            output_div.append(main_content_html)
        
        return str(final_soup)