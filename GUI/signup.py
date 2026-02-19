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

    if username  in users:
        return False #user already exist
    
    users[username] = password
    store_users(users)
    return True
    
    
def store_users(users):
    with open(Users_names, "w") as file:
        json.dump(users, file)
 