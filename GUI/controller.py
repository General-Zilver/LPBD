import os
import json
import customtkinter as ctk

from login import LoginPage
from signup import SignupPage
from main import WelcomePage
from question import QuestionPage
from chat import ChatPage
from forgot import ForgotPage
from auth import existing_users
from auth import mark_questionnaire_completed

class AppController:
    def __init__(self, root):
        self.root = root

        # store session/user data
        self.session = {
            "username": None,
            "is_new_user": False,
            "answers": {}
        }

        # navigation history
        self.history = []

        self.current_page = None

        # folder to store user answers
        self.answers_folder = "answers"
        if not os.path.exists(self.answers_folder):
            os.makedirs(self.answers_folder)

        # start app
        self.show_page("login")

    def clear_page(self):
        if self.current_page:
            self.current_page.destroy()

    def show_page(self, page_name):
        self.clear_page()
        self.history.append(page_name)

        if page_name == "login":
            self.current_page = LoginPage(self.root, self)

        elif page_name == "signup":
            self.current_page = SignupPage(self.root, self)

        elif page_name == "main":
            self.current_page = WelcomePage(self.root, self)

        elif page_name == "question":
            selected_options = self.session.get("selected_options", [])
            self.question_page = QuestionPage(self.root, self, selected_options)
            self.current_page = self.question_page

        elif page_name == "chat":
            self.current_page = ChatPage(self.root, self)

        elif page_name == "forgot":
            self.current_page = ForgotPage(self.root, self)

        self.current_page.pack(fill="both", expand=True)

    def go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            previous = self.history.pop()
            self.show_page(previous)

    # --- Add this method ---
    from auth import existing_users, mark_questionnaire_completed

    def is_new_user(self, username):
        """Return True if user has not completed questionnaire yet"""
        users = existing_users()
        return not users.get(username, {}).get("completed_questionnaire", False)

    def mark_user_complete(self, username):
        """Mark questionnaire completed for this user"""
        mark_questionnaire_completed(username)