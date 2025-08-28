from bs4 import BeautifulSoup, NavigableString
import re

class HtmlParser:
    """ A utility class to parse and manipulate HTML content into a hierarchical, collapsible format. """

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

    def _get_heading_level(self, element):
        """
        Determines the heading level of an element using a set of heuristics.
        Returns a tuple: (level, heading_text) or (0, None) if not a heading.
        """
        heading_text = element.get_text(strip=True)
        if not heading_text:
            return 0, None
        
        classes = element.get('class', [])

        if element.name == 'block' and 'section-header' in classes:
            level_match = re.search(r'section-level-(\d+)', ' '.join(classes))
            if level_match:
                return int(level_match.group(1)), heading_text
            if re.match(r'^(schedule|part)\s', heading_text, re.IGNORECASE):
                return 1, heading_text
            return 2, heading_text

        if re.match(r'h[1-6]', element.name):
            return int(element.name[1]), heading_text

        heading_candidate = None
        if element.name == 'b':
            heading_candidate = element
        elif element.name in ['p', 'div', 'blockquote']:
            b_tag = element.find('b', recursive=False)
            if b_tag and len(b_tag.get_text(strip=True)) > 0:
                heading_candidate = b_tag
        
        if heading_candidate:
            if re.match(r'^(PART\s*\d+|SCHEDULE\s*\d+|ENDNOTES?)\b', heading_text, re.IGNORECASE):
                return 1, heading_text
            if re.match(r'^(Division\s*\d+|[A-Z]?\d+(\.\d+)*(\—|\.)?(\s|\b))', heading_text, re.IGNORECASE):
                return 2, heading_text

            style = element.get('style', '')
            if isinstance(style, str):
                size_match = re.search(r'font-size\s*:\s*(\d+)%', style)
                if size_match and int(size_match.group(1)) > 150:
                    return 1, heading_text
        
        return 0, None

    def _build_hierarchy(self, html_content):
        """Builds a nested list from the HTML content."""
        soup = BeautifulSoup(html_content, 'html.parser')

        content_root = soup.find('doc', class_=re.compile(r'legislative|akbn-root')) or \
                       soup.find('div', class_='article-text') or \
                       soup.body

        # --- NEW CLEANUP STEP ---
        # Before processing, find all tags with `display:none` and remove that style.
        # This prevents content from being hidden inside the final collapsible sections.
        if content_root:
            for tag in content_root.find_all(style=re.compile(r"display:\s*none", re.IGNORECASE)):
                # More robustly remove just the 'display' part of the style
                style = tag.get('style', '')
                # This regex removes 'display: none !important;' and similar variations
                new_style = re.sub(r'display\s*:\s*none\s*!important\s*;?', '', style, flags=re.IGNORECASE)
                new_style = re.sub(r'display\s*:\s*none\s*;?', '', new_style, flags=re.IGNORECASE)
                if new_style.strip():
                    tag['style'] = new_style.strip()
                else:
                    del tag['style']
        # --- END NEW CLEANUP STEP ---

        title_tag = soup.find('title') or soup.find('shorttitle')
        title = title_tag.get_text(strip=True) if title_tag else "Document"

        hierarchy = []
        parent_stack = []
        current_content_tags = []

        elements = content_root.find_all(True, recursive=False) if content_root else []

        for element in elements:
            if isinstance(element, NavigableString) and not element.strip():
                continue

            level, heading_text = self._get_heading_level(element)

            if level > 0:
                if parent_stack:
                    parent_stack[-1]['content_tags'].extend(current_content_tags)
                current_content_tags = []

                safe_text = re.sub(r'[^a-zA-Z0-9_-]', '', heading_text.replace(" ", "-"))
                unique_id = element.get('id') or f"section-{safe_text[:50]}-{len(hierarchy)}"

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
            else:
                current_content_tags.append(element)
        
        if parent_stack:
            parent_stack[-1]['content_tags'].extend(current_content_tags)
        elif not hierarchy and current_content_tags:
            hierarchy.append({
                'id': 'main-content',
                'level': 1,
                'heading_tag': BeautifulSoup(f"<p><b>{title}</b></p>", 'html.parser').p,
                'content_tags': current_content_tags,
                'children': []
            })
            
        return hierarchy, title

    def _generate_toc_html(self, soup, nodes):
        """Recursively generates the Table of Contents HTML."""
        if not nodes:
            return None
        ul = soup.new_tag('ul')
        for node in nodes:
            li = soup.new_tag('li')
            a = soup.new_tag('a', href=f"#{node['id']}")
            heading_text = node['heading_tag'].get_text(separator=' ', strip=True)
            a.string = heading_text or "Untitled Section"
            li.append(a)
            if node['children']:
                li['class'] = 'toc-collapsible'
                li.append(self._generate_toc_html(soup, node['children']))
            ul.append(li)
        return ul

    def _generate_main_content_html(self, soup, nodes):
        """Recursively generates the main content area HTML."""
        container = soup.new_tag('div')
        for node in nodes:
            header_div = soup.new_tag('div', attrs={
                'class': f"collapsible level-{node['level']}",
                'id': node['id']
            })
            header_div.extend(node['heading_tag'].contents)
            container.append(header_div)

            content_div = soup.new_tag('div', attrs={'class': 'content'})
            for content_tag in node['content_tags']:
                content_div.append(content_tag)
            if node['children']:
                content_div.append(self._generate_main_content_html(soup, node['children']))
            container.append(content_div)
        return container


    def create_juriscontent_html(self, html_content: str, template_content: str) -> str:
        """
        Creates a styled, hierarchical, and collapsible HTML file using a provided template.
        """
        hierarchy, title = self._build_hierarchy(html_content)
        
        formatted_template = template_content.replace('{title}', title)
        final_soup = BeautifulSoup(formatted_template, 'html.parser')

        toc_list_div = final_soup.find('div', id='toc-list')
        toc_html = self._generate_toc_html(final_soup, hierarchy)
        if toc_html:
            toc_list_div.append(toc_html)

        output_div = final_soup.find('div', id='output')
        main_content_html = self._generate_main_content_html(final_soup, hierarchy)
        if main_content_html:
            for child in list(main_content_html.contents):
                output_div.append(child)
        
        return str(final_soup)
