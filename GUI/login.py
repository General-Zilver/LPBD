import customtkinter as ctk
from signup import sign_up

class LoginPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_login_card()

    def create_top_bar(self):
        top_bar = ctk.CTkFrame(self, height=60)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top_bar,
            text="Student Benefit Analyzer",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        ctk.CTkButton(
            top_bar,
            text="Sign Up",
            command=self.sign_up_button
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")

    def create_login_card(self):
        center_frame = ctk.CTkFrame(self)
        center_frame.grid(row=1, column=0, sticky="nsew")
        center_frame.grid_rowconfigure(0, weight=1)
        center_frame.grid_columnconfigure(0, weight=1)

        # Increased width and height for a bigger card
        login_card = ctk.CTkFrame(center_frame, width=450, height=450, corner_radius=15)
        login_card.grid(row=0, column=0)
        login_card.grid_propagate(False)

        ctk.CTkLabel(
            login_card,
            text="Login",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(40, 25))

        # Add horizontal padding (padx) so input bars aren't touching the edges
        self.username_entry = ctk.CTkEntry(login_card, placeholder_text="Username", width=300)
        self.username_entry.pack(pady=15, padx=25)

        self.password_entry = ctk.CTkEntry(login_card, placeholder_text="Password", show="*", width=300)
        self.password_entry.pack(pady=10, padx=25)
        
        self.users_confirmation = ctk.CTkLabel(login_card, text="")
        self.users_confirmation.pack(pady=10, padx=25)

        # Frame for "Forgot Password?" button aligned right
        forgot_frame = ctk.CTkFrame(login_card, fg_color="transparent")
        forgot_frame.pack(fill="x", pady=(0, 15), padx=25)  # match entry padding

        ctk.CTkLabel(forgot_frame, text="").pack(side="left", expand=True)

        ctk.CTkButton(
            forgot_frame,
            text="Forgot Password?",
            width=140,
            height=30,
            fg_color="transparent",
            hover_color="#E0E0E0",
            command=lambda: print("Forgot Password clicked")
        ).pack(side="right")

        ctk.CTkButton(login_card, text="Login", width=300, height=35).pack(pady=25, padx=25)

    def sign_up_button(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        if sign_up(username, password): 
            self.users_confirmation.configure(text="Account Created", text_color="blue")
        else:
            self.users_confirmation.configure(text="Username in use, try again", text_color="red")