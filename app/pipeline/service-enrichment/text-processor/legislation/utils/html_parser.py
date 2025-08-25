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

    def create_juriscontent_html(self, html_content: str) -> str:
        """
        Creates a styled, hierarchical, and collapsible HTML file ('juriscontent.html').
        This function restructures the HTML for a clean, readable layout and injects
        the necessary CSS and JavaScript for the collapsible functionality.

        Args:
            html_content (str): The original HTML content.

        Returns:
            str: The modified and styled HTML as a string.
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- 1. Find or create the <head> tag ---
        head = soup.find('head')
        if not head:
            head = soup.new_tag('head')
            if soup.html:
                soup.html.insert(0, head)
            else:
                soup.insert(0, head)

        # Clear existing head content to avoid conflicts, then add our elements
        head.clear()
        
        # Add meta viewport for responsive design
        meta_viewport = soup.new_tag('meta', attrs={'name': 'viewport', 'content': 'width=device-width, initial-scale=1.0'})
        head.append(meta_viewport)

        # Add link to Google Fonts for Poppins
        font_link_tag = soup.new_tag(
            'link',
            href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap",
            rel="stylesheet"
        )
        head.append(font_link_tag)

        # --- 2. Add comprehensive CSS for styling and collapsibility ---
        style_tag = soup.new_tag('style')
        style_tag.string = """
            body {
                font-family: 'Poppins', sans-serif;
                line-height: 1.7;
                color: #000000; /* Text color set to black */
                background-color: #f8f9fa;
                margin: 0;
                padding: 20px;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }
            .container {
                max-width: 850px;
                margin: 20px auto;
                background-color: #ffffff;
                padding: 30px 50px;
                border-radius: 8px;
                box-shadow: 0 6px 12px rgba(0,0,0,0.08);
                border: 1px solid #e9ecef;
            }
            h1, h2, h3, h4, h5, h6 {
                font-weight: 600;
                color: #000000; /* Headings color set to black */
                margin-top: 1.5em;
                margin-bottom: 0.5em;
                line-height: 1.3;
            }
            h1 { font-size: 2.1em; padding-bottom: 0.3em;}
            h2 { font-size: 1.8em; }
            h3 { font-size: 1.5em; }
            
            /* -- MODIFIED STYLES FOR COLLAPSIBLE HEADINGS -- */
            .collapsible {
                cursor: pointer;
                user-select: none; /* Prevent text selection on click */
                transition: color 0.2s ease-in-out;
            }
            .collapsible:hover {
                color: #3498db;
            }
            .collapsible::before {
                content: '\\203A'; /* Right-pointing single angle quotation mark */
                color: #000000; /* Icon color set to black */
                font-weight: bold;
                font-size: 1.2em; /* Adjusted size to fit better inline */
                display: inline-block; /* Ensures the icon can be transformed */
                margin-right: 8px; /* Creates space between the icon and the text */
                transform: rotate(0deg);
                transition: transform 0.2s ease-in-out;
            }
            .collapsible.active::before {
                transform: rotate(90deg);
            }
            .content {
                padding-left: 25px; /* Indent the content under the heading */
                display: none; /* Hidden by default */
                overflow: hidden;
            }
            p { margin-bottom: 1.2em; }
            a { color: #3498db; text-decoration: none; }
            a:hover { color: #2980b9; text-decoration: underline; }
            ul, ol { padding-left: 25px; }
            li { margin-bottom: 0.6em; }
            blockquote {
                padding-left: 20px;
                margin-left: 0;
                font-style: italic;
                color: #000000; /* Blockquote text color set to black */
            }

            /* -- NEW STYLES FOR DEFINITION LISTS (enum and content) -- */
            dt, dd {
                display: inline;
            }
            dt {
                font-weight: bold;
            }
            dd {
                margin-left: 0.5em;
            }
            dd::after {
                content: '';
                display: block;
            }
            
            /* Make paragraphs inside certain elements flow inline */
            li p, .subclause > p {
                display: inline;
            }
            
            /* Style enum labels to flow inline and add a space after them */
            li .li-label, .subclause > .number {
                display: inline;
                margin-right: 0.5em; /* Adds space between enum and text */
            }
            
            /* -- NEW STYLES FOR TABLES -- */
            table {
                width: 100%;
                border-collapse: collapse; /* Merges adjacent borders */
                margin-top: 1.5em;
                margin-bottom: 1.5em;
            }
            th, td {
                border: 1px solid #dddddd; /* Light grey border for grid lines */
                padding: 12px;
                text-align: left;
            }
            th, thead td {
                background-color: #f2f2f2; /* Lighter grey background for header */
                font-weight: 600;
            }
        """
        head.append(style_tag)
        
        # --- 3. Restructure the HTML body for hierarchy (Non-Destructive Method) ---
        body = soup.find('body')
        if body:
            # --- Remove all image tags from the body ---
            for img_tag in body.find_all('img'):
                img_tag.decompose()

            heading_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
            
            # Find all headings and wrap their subsequent content
            for heading in body.find_all(heading_tags):
                # Create a wrapper for the content that follows the heading
                content_wrapper = soup.new_tag('div', attrs={'class': 'content'})
                
                # Move all subsequent siblings into the wrapper, until a heading of the same or higher level
                for sibling in list(heading.find_next_siblings()):
                    if sibling.name in heading_tags and heading_tags.index(sibling.name) <= heading_tags.index(heading.name):
                        break
                    content_wrapper.append(sibling.extract())
                
                # Add the collapsible class to the heading
                heading['class'] = heading.get('class', []) + ['collapsible']
                # Place the wrapper immediately after the heading
                heading.insert_after(content_wrapper)
            
            # --- 4. Wrap everything in the final container for styling ---
            container_div = soup.new_tag('div', attrs={'class': 'container'})
            # Move all children of the body into the new container
            container_div.extend(list(body.children))
            # Replace the body's content with the new container
            body.clear()
            body.append(container_div)

            # --- 5. Add JavaScript at the end of the body for interactivity ---
            script_tag = soup.new_tag('script')
            script_tag.string = """
                var coll = document.getElementsByClassName("collapsible");
                for (var i = 0; i < coll.length; i++) {
                    coll[i].addEventListener("click", function() {
                        this.classList.toggle("active");
                        var content = this.nextElementSibling;
                        if (content.style.display === "block") {
                            content.style.display = "none";
                        } else {
                            content.style.display = "block";
                        }
                    });
                }
            """
            body.append(script_tag)

        return str(soup)