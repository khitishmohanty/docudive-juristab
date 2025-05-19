import os
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract
from difflib import SequenceMatcher

def extract_text_from_pdf_page(pdf_path: str, page_number: int) -> str:
    """Attempt to extract text from a given PDF page (machine-readable)."""
    reader = PdfReader(pdf_path)
    if page_number < len(reader.pages):
        text = reader.pages[page_number].extract_text()
        return text or ""
    return ""

def extract_text_from_ocr(pdf_path: str, page_number: int, poppler_path=None) -> str:
    """Render a single page as image and perform OCR to extract text."""
    images = convert_from_path(
        pdf_path,
        dpi=300,
        first_page=page_number + 1,
        last_page=page_number + 1,
        poppler_path=poppler_path
    )
    return pytesseract.image_to_string(images[0]) if images else ""

def is_fidelity_preserved(text1: str, text2: str, threshold: float = 0.9) -> bool:
    """Check if text2 is similar enough to text1 using SequenceMatcher."""
    return SequenceMatcher(None, text1.strip(), text2.strip()).ratio() >= threshold
