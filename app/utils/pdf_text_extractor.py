import os
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract
from difflib import SequenceMatcher
import fitz # PyMuPDF 

def extract_text_from_pdf_page(pdf_path: str, page_number: int) -> str:
    """Attempt to extract text from a given PDF page (machine-readable)."""
    # page_number here is 0-indexed for PdfReader
    reader = PdfReader(pdf_path)
    if 0 <= page_number < len(reader.pages):
        text = reader.pages[page_number].extract_text()
        return text or ""
    return ""

def extract_text_from_ocr(pdf_path: str, page_number: int, poppler_path=None) -> str:
    """Render a single page as image and perform OCR to extract text."""
    # page_number is 0-indexed input. convert_from_path expects 1-indexed pages.
    # If pdf_path is a single-page PDF, page_number should be 0, so first/last_page = 1.
    images = convert_from_path(
        pdf_path,
        dpi=300,
        first_page=page_number + 1,
        last_page=page_number + 1,
        poppler_path=poppler_path,
        thread_count=1 # Can help with some intermittent issues on Windows
    )
    return pytesseract.image_to_string(images[0]) if images else ""

def is_fidelity_preserved(text1: str, text2: str, threshold: float = 0.9) -> bool:
    """Check if text2 is similar enough to text1 using SequenceMatcher."""
    return SequenceMatcher(None, text1.strip(), text2.strip()).ratio() >= threshold

def extract_text_and_links_with_fitz(pdf_path: str, page_number: int) -> tuple[str, list[dict]]:
    """
    Extracts full page text and a list of hyperlinks (URL, anchor text, and rectangle)
    from a given PDF page using PyMuPDF (fitz).
    page_number is 0-indexed.
    """
    doc = None
    page_text_content = ""
    hyperlinks_data = []
    try:
        doc = fitz.open(pdf_path)
        if 0 <= page_number < doc.page_count:
            page = doc.load_page(page_number)
            page_text_content = page.get_text("text") or ""
            
            links = page.get_links() # Returns a list of link dicts from fitz
            for link_dict in links:
                if link_dict.get('kind') == fitz.LINK_URI: # Check if it's a URI link
                    uri = link_dict.get('uri')
                    rect = link_dict.get('from_rect') # The fitz.Rect object of the link
                    
                    # Attempt to extract text only from the link's rectangle
                    link_anchor_text = page.get_text("text", clip=rect).strip() if rect else "N/A"
                    
                    if uri:
                        hyperlinks_data.append({
                            "text": link_anchor_text,
                            "url": uri,
                            "rect": [rect.x0, rect.y0, rect.x1, rect.y1] if rect else None
                        })
    except Exception as e:
        print(f"Error processing PDF page {page_number} with fitz in {pdf_path}: {e}")
        # page_text_content and hyperlinks_data will retain their default empty/initial values
    finally:
        if doc:
            doc.close()
            
    return page_text_content, hyperlinks_data