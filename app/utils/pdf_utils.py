import fitz

def _create_temp_page_pdf(pdf_document: fitz.Document, page_index: int, temp_pdf_page_path: str) -> None:
    """Creates a temporary single-page PDF."""
    single_page_doc = fitz.open()
    single_page_doc.insert_pdf(pdf_document, from_page=page_index, to_page=page_index)
    single_page_doc.save(temp_pdf_page_path)
    single_page_doc.close()