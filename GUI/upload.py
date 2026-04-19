import json
from file_proccesor import Image_read
from ollama_extract import extract

def save_answer(email, information):
    try:
        with open("answers.json", "r") as f:
            data = json.load(f)
    except:
        data = {}

        if email not in data:
            data[email] = []

        data[email].append(information)

        with open("answers.json", "w") as f:
            json.dump(data, f, indent=4)

def process(email, filepath):
    text = Image_read(filepath)
    extracted = extract(text)
    save_answer(email, extracted)
#reads the image -> OCR -> ollama -> saves to answers.json