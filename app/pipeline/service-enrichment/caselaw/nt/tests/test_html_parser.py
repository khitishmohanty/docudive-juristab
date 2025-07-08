from src.html_parser import HtmlParser

def test_extract_text_from_html():
    """Test the extract_text method of HtmlParser."""
    html_content = "<html><body><p>Hello, World!</p></body></html>"
    expected_text = "Hello, World!"
    
    parser = HtmlParser()
    extracted_text = parser.extract_text(html_content)
    
    assert extracted_text == expected_text, f"Expected '{expected_text}', but got '{extracted_text}'"