import customtkinter as ctk
from settings import SettingsOverlay

class ChatPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_chat_area()
        self.create_input_bar()

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
            text="Settings",
            command=self.open_settings
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")
    
    def open_settings(self):
        SettingsOverlay(self.master, self)

    def create_chat_area(self):
        self.chat_frame = ctk.CTkScrollableFrame(self)
        self.chat_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)

        self.chat_frame.grid_columnconfigure(0, weight=1)

        # Example starter message
        self.add_message("Welcome to Student Benefit Analyzer!", sender="system")

    def add_message(self, message, sender="user"):
        bubble = ctk.CTkFrame(self.chat_frame, corner_radius=15)

        if sender == "user":
            bubble.configure(fg_color="#2B7FFF")
            anchor = "e"
            padx = (100, 10)
        else:
            bubble.configure(fg_color="#3A3A3A")
            anchor = "w"
            padx = (10, 100)

        bubble.pack(fill="none", padx=padx, pady=5, anchor=anchor)

        label = ctk.CTkLabel(
            bubble,
            text=message,
            wraplength=400,
            justify="left"
        )
        label.pack(padx=15, pady=10)

    def create_input_bar(self):
        input_frame = ctk.CTkFrame(self, height=70)
        input_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        input_frame.grid_columnconfigure(1, weight=1)

        # Upload Button
        upload_btn = ctk.CTkButton(
            input_frame,
            text="Upload",
            width=100
        )
        upload_btn.grid(row=0, column=0, padx=(10, 5), pady=10)

        # Entry
        self.message_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Type your message here..."
        )
        self.message_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=10)

        # Send Button
        send_btn = ctk.CTkButton(
            input_frame,
            text="Send",
            width=100
        )
        send_btn.grid(row=0, column=2, padx=(5, 10), pady=10)

    