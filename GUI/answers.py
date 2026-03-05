import json
import os

ANSWERS_FILE = "answers.json"

def saved_answers():
    if not os.path.exists(ANSWERS_FILE):
        return {}
    with open(ANSWERS_FILE, "r") as file:
        return json.load(file)
    
def save_answers(username, section, question, answers):
    all_answers = saved_answers()
    if username not in all_answers:
        all_answers[username] = {}
    if section not in all_answers[username]:
        all_answers[username][section] = {}
    all_answers[username][section][question] = answers
    with open(ANSWERS_FILE, "w") as file:
        json.dump(all_answers, file, indent=4)
    
    