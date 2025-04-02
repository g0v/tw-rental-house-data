import cv2
import base64
import numpy as np
import logging
import os
from paddleocr import PaddleOCR
from paddleocr.ppocr.utils.logging import get_logger

# disable paddleocr debug log
ppocr_logger = get_logger()
ppocr_logger.setLevel(logging.ERROR)

paddle_ocr_en = PaddleOCR(lang='en')
paddle_ocr_zh = PaddleOCR(lang='chinese_cht')

def convert_base64_to_img(base64_str, output_path=None):
    """
    Convert base64 string to image file.
        
    Args:
        base64_str (str): Base64 encoded string of image
        output_path (str, optional): Path to save the image. If None, image won't be saved.
            
    Returns:
        numpy.ndarray: Image as numpy array
    """

    # Magic bytes for common image formats
    MAGIC_BYTES = {
        b'\xff\xd8\xff': 'jpg',
        b'\x89\x50\x4e\x47': 'png',
        b'\x47\x49\x46\x38': 'gif',
        b'\x42\x4d': 'bmp',
        b'\x52\x49\x46\x46': 'webp'
    }

    # Remove header if present (e.g., "data:image/jpeg;base64,")
    file_type = None
    if ',' in base64_str and ';base64,' in base64_str:
        header, base64_str = base64_str.split(',', 1)
        # Try to extract file type from header
        if 'image/' in header:
            file_type = header.split('image/')[1].split(';')[0]

    # Decode base64 string
    try:
        img_data = base64.b64decode(base64_str)

        # If file type wasn't detected from header, detect it from magic bytes
        if not file_type:
            for magic, ext in MAGIC_BYTES.items():
                if img_data.startswith(magic):
                    file_type = ext
                    break

        img_array = np.frombuffer(img_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        # Save the image if output path is provided
        if output_path and img is not None:
            # Add appropriate extension if not present
            if file_type and not output_path.lower().endswith(f".{file_type.lower()}"):
                base_path, ext = os.path.splitext(output_path)
                if not ext:
                    output_path = f"{output_path}.{file_type}"

            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            cv2.imwrite(output_path, img)

        return img
    except Exception as e:
        print(f"Error converting base64 to image: {e}")
        return None


def ocr_via_paddle(image, char_whitelist='0123456789F/.,', chop_right=0, use_zh=False): 
    """
    Extract digits from image using PaddleOCR with simplified processing.

    Args:
        image: Image as numpy array
        char_whitelist (str): Characters to keep in the result
        chop_right (int): Number of pixels to remove from right side of image
        
    Returns:
        str: Recognized digits and specified special characters
    """

    paddle_ocr = paddle_ocr_zh if use_zh else paddle_ocr_en

    # Chop right side if needed
    if chop_right > 0:
        height, width = image.shape[:2]
        image = image[:, :width - chop_right]

    # Save preprocessed image for debugging
    cv2.imwrite('preprocessed_paddle.png', image)

    # Run PaddleOCR with detection and classification disabled
    # This treats the image as a single text line for simple digit recognition
    result = paddle_ocr.ocr(image, det=False, cls=False)

    # Extract text from results (simplified format with det=False)
    if result and len(result) and len(result[0]):
        recognized_text, _prop = result[0][0]  # Get the text
        # Filter to keep only allowed characters
        filtered_text = ""
        for char in recognized_text:
            if char in char_whitelist:
                filtered_text += char
        return filtered_text.strip()

    return ""

def base64_to_image(base64_str):
    """
    Convert a base64 string to a CV2 image.
    
    Args:
        base64_str (str): Base64 encoded string of image
        
    Returns:
        numpy.ndarray: Image as numpy array (CV2 format)
    """
    # Remove header if present (e.g., "data:image/jpeg;base64,")
    if ',' in base64_str and ';base64,' in base64_str:
        base64_str = base64_str.split(',', 1)[1]

    # Decode base64 string
    try:
        # Decode base64 to binary data
        img_data = base64.b64decode(base64_str)

        # Convert binary data to image
        img_array = np.frombuffer(img_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        return img
    except Exception as e:
        logging.error("Error converting base64 to image: %s", e)
        return None

def parse_floor(base64_img):
    """"
    Parse the floor information from the base64 image."
    """
    img = base64_to_image(base64_img)
    if img is None:
        return None

    digit_str = ocr_via_paddle(img, char_whitelist='0123456789/F-~')
    zh_str = ocr_via_paddle(img, char_whitelist='棟加', use_zh=True)

    digit_tokens = digit_str.split('/')
    answer = ''

    if not len(digit_tokens):
        return ''

    if zh_str:
        if zh_str == '棟':
            answer = '整棟/'
        else:
            answer = '頂樓加蓋/'
        answer += digit_tokens[len(digit_tokens) - 1]
    else:
        answer = digit_str

    if '~' in answer:
        answer = answer.replace('~', '-')

    return answer

def parse_ping(base64_img):
    """"
    Parse the ping information from the base64 image."
    """
    img = base64_to_image(base64_img)
    if img is None:
        return None

    digit_str = ocr_via_paddle(img, char_whitelist='0123456789.', chop_right=18)
    return digit_str

def parse_price(base64_img):
    """"
    Parse the price information from the base64 image."
    """
    img = base64_to_image(base64_img)
    if img is None:
        return None

    digit_str = ocr_via_paddle(img, char_whitelist='0123456789,.')
    return digit_str
