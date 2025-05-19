from utils.pdf_to_image_converter import convert_pdf_to_images
import base64

def process_pdf_to_images(pdf_path, image_dir, poppler_path=None):
    return convert_pdf_to_images(pdf_path, image_dir, poppler_path)

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")
