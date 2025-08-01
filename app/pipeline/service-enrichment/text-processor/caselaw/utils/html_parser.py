from bs4 import BeautifulSoup

class HtmlParser:
    """ A utility class to parse and extract text from HTML content. """
    
    def extract_text(self, html_content: str) -> str:
        """
        Extracts text from the given HTML content.

        Args:
            html_content (str): The HTML content to parse.

        Returns:
            str: The extracted text.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)

    def modify_html_font(self, html_content: str) -> str:
        """
        Modifies the HTML to use the 'Poppins' font and returns the updated HTML.
        It adds a link to Google Fonts and sets the font-family for the body.

        Args:
            html_content (str): The original HTML content.

        Returns:
            str: The modified HTML as a string.
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find or create the <head> tag
        head = soup.find('head')
        if not head:
            head = soup.new_tag('head')
            if soup.html:
                soup.html.insert(0, head)
            else:
                soup.insert(0, head)

        # Create and add the link to Google Fonts for Poppins
        font_link_tag = soup.new_tag(
            'link',
            href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap",
            rel="stylesheet"
        )
        head.append(font_link_tag)

        # Create and add a style tag to apply the font to the body
        style_tag = soup.new_tag('style')
        style_tag.string = "body { font-family: 'Poppins', sans-serif; }"
        head.append(style_tag)

        return str(soup)