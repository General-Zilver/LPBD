import json
import os

Users_names = "users.json"

def existing_users():
    if not os.path.exists(Users_names):
        return {}
    with open (Users_names, "r") as file:
        return json.load(file)
    
def sign_up(username, password):
    users = existing_users()

    if username in users:
        return False  # user already exists

    users[username] = {
        "password": password,
        "completed_questionnaire": False
    }
    store_users(users)
    return True
    
    
def store_users(users):
    with open(Users_names, "w") as file:
        json.dump(users, file)
 
def login(username, password):
    users = existing_users()
    if username in users and users[username]["password"] == password:
        return True
    return False

def is_new_user(username):
    users = existing_users()
    return not users.get(username, {}).get("completed_questionnaire", False)

def mark_questionnaire_completed(username):
    users = existing_users()
    if username in users:
        users[username]["completed_questionnaire"] = True
        store_users(users)