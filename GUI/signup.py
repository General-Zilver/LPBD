import customtkinter as ctk
from auth import sign_up


class SignupPage(ctk.CTkFrame):

    def __init__(self, parent, controller):
        super().__init__(parent)

        self.controller = controller

        ctk.CTkLabel(self, text="Create Account", font=("Arial", 24)).pack(pady=20)

        self.username = ctk.CTkEntry(self, placeholder_text="Username")
        self.username.pack(pady=10)

        self.password = ctk.CTkEntry(self, placeholder_text="Password", show="*")
        self.password.pack(pady=10)

        self.message = ctk.CTkLabel(self, text="")
        self.message.pack(pady=10)

        ctk.CTkButton(
            self,
            text="Sign Up",
            command=self.create_account
        ).pack(pady=10)

    def create_account(self):

        username = self.username.get()
        password = self.password.get()

        success = sign_up(username, password)

        if success:
            self.message.configure(text="Account created!", text_color="green")
        else:
            self.message.configure(text="User already exists", text_color="red")