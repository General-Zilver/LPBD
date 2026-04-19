from PIL import Image
import pytesseract

#reads image and covers it to text using OCR
def Image_read(x):
    img = Image.open(x)
    text = pytesseract.image_to_string(img)
    return text