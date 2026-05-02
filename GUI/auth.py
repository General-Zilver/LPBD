import json
import os
import re
import secrets

Users_names = "users.json"

#email validation
def valid_email(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(pattern, email) is not None

#Load users
def load_users():
    if not os.path.exists(Users_names):
        return {}
    with open(Users_names, "r") as file:
        return json.load(file)
#save users  
def save_users(users):
    with open(Users_names, "w") as file:
        json.dump(users, file, indent=4)

#sign up email, also rejects invalid emails and duplicates
def sign_up(email, password):
    if not valid_email(email):
        return False, "Please enter a valid email address"
    
    users = load_users()

    if email in users:
        return False, "An account with this email already exists"
    
    users[email] = {
        "password": password,
        "completed_questionnaire": False
    }

    save_users(users)
    return True, "Account succesfully created"

#login email, with email and password, and rejects invalid emails and passwords
def login(email, password):
    if not valid_email(email):
        return False, "please enter a valid email address"
    
    users = load_users()

    if email not in users:
        return False, "No account found with this email address"
    
    if users[email]["password"] != password:
        return False, "Incorrect password"
        
    return True, "Login succesful"
#Questionnaire tracking, checks if the user has done the questionnaire and updates it when finished
def new_user(email):
    users = load_users()
    return not users.get(email, {}).get("completed_questionnaire", False)

def questionnaire_tracking(email):
    users = load_users()
    if email in users:
        users[email]["completed_questionnaire"] = True
        save_users(users)

#forgot password, generates a reset token and stores it in users.json. is used to send password reset links
def reset_token(email):
    users = load_users()
    
    if email not in users:
        return None
    
    token = secrets.token_urlsafe(32)
    users[email]["reset_token"] = token
    save_users(users)
    return token
#verifies the token and which email it belongs to
def verify_token(token):
    users = load_users()
    for email, data in users.items():
        if data.get("reset_token") == token:
            return email
        return None
#resets password and gets rid of the token
def reset_password(email, new_password):
    users = load_users()
    if email in users:
        users[email]["password"] = new_password
        users[email].pop("reset_token", None)
        return True
    return False