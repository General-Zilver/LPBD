import customtkinter as ctk

class ForgotPage(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)

        self.controller = controller

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_reset_card()

    def create_top_bar(self):
        top_bar = ctk.CTkFrame(self, height=60)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top_bar,
            text="Student Benefit Analyzer",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")

    def create_reset_card(self):
        center_frame = ctk.CTkFrame(self)
        center_frame.grid(row=1, column=0, sticky="nsew")
        center_frame.grid_rowconfigure(0, weight=1)
        center_frame.grid_columnconfigure(0, weight=1)

        reset_card = ctk.CTkFrame(center_frame, width=450, height=350, corner_radius=15)
        reset_card.grid(row=0, column=0)
        reset_card.grid_propagate(False)

        ctk.CTkLabel(
            reset_card,
            text="Reset Password",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(40, 20))

        ctk.CTkLabel(
            reset_card,
            text="Enter your email to receive reset instructions.",
            font=ctk.CTkFont(size=14)
        ).pack(pady=(0, 15))

        self.email_entry = ctk.CTkEntry(
            reset_card,
            placeholder_text="Email Address",
            width=300
        )
        self.email_entry.pack(pady=15, padx=25)

        ctk.CTkButton(
            reset_card,
            text="Send Reset Link",
            width=300,
            height=35,
            command=self.send_reset
        ).pack(pady=15, padx=25)

        ctk.CTkButton(
            reset_card,
            text="Back to Login",
            width=300,
            height=30,
            fg_color="transparent",
            hover_color="#E0E0E0",
            command=self.go_back
        ).pack(pady=(10, 20))

    def send_reset(self):
        email = self.email_entry.get()
        print(f"Reset link requested for {email}")
        # later you can implement actual reset logic here

    def go_back(self):
        self.controller.show_page("login")