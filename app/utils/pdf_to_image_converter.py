import os
from typing import List
from pdf2image import convert_from_path

def convert_pdf_to_images(
    pdf_path: str,
    output_dir: str,
    image_format: str = "jpeg",  # ⬅️ Changed from "jpg" to "jpeg"
    dpi: int = 200,
    poppler_path: str = None
) -> List[str]:
    """
    Converts each page of a PDF into an image.

    Args:
        pdf_path (str): Path to the PDF file.
        output_dir (str): Directory to save image files.
        image_format (str): Image format (jpeg, png). Default is 'jpeg'.
        dpi (int): Resolution in DPI. Default is 200.
        poppler_path (str): Path to poppler/bin (Windows only).

    Returns:
        List[str]: List of paths to the generated image files.
    """
    os.makedirs(output_dir, exist_ok=True)

    images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler_path)

    image_paths = []
    for i, img in enumerate(images):
        image_filename = f"page_{i + 1}.{image_format}"
        image_path = os.path.join(output_dir, image_filename)
        img.save(image_path, format="JPEG")  # Always use "JPEG" format for saving
        image_paths.append(image_path)

    print(f"✅ Converted {len(image_paths)} pages to images in: {output_dir}")
    return image_paths
