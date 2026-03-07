import customtkinter as ctk
from tkinter import filedialog
from settings import SettingsOverlay


class ChatPage(ctk.CTkFrame):

    def __init__(self, parent,controller):
        super().__init__(parent)
        self.controller = controller

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_chat_area()
        self.create_input_bar()

    # -----------------------
    # Top Bar
    # -----------------------

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
        SettingsOverlay(self.master, self.controller)

    # -----------------------
    # Chat Area
    # -----------------------

    def create_chat_area(self):

        self.chat_frame = ctk.CTkScrollableFrame(self)
        self.chat_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)

        self.chat_frame.grid_columnconfigure(0, weight=1)

        self.add_message(
            "Welcome to Student Benefit Analyzer!\nAsk me about your eligible benefits.",
            sender="system"
        )

    def add_message(self, message, sender="user"):

        bubble = ctk.CTkFrame(self.chat_frame, corner_radius=15)

        if sender == "user":
            bubble.configure(fg_color="#2B7FFF")
            anchor = "e"
            padx = (120, 10)

        elif sender == "system":
            bubble.configure(fg_color="#3A3A3A")
            anchor = "w"
            padx = (10, 120)

        bubble.pack(fill="none", padx=padx, pady=6, anchor=anchor)

        label = ctk.CTkLabel(
            bubble,
            text=message,
            wraplength=420,
            justify="left"
        )

        label.pack(padx=15, pady=10)

        self.chat_frame._parent_canvas.yview_moveto(1)

    # -----------------------
    # Input Bar
    # -----------------------

    def create_input_bar(self):

        input_frame = ctk.CTkFrame(self, height=70)
        input_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        input_frame.grid_columnconfigure(1, weight=1)

        upload_btn = ctk.CTkButton(
            input_frame,
            text="Upload",
            width=100,
            command=self.upload_file
        )

        upload_btn.grid(row=0, column=0, padx=(10, 5), pady=10)

        self.message_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Type your message here..."
        )

        self.message_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=10)

        self.message_entry.bind("<Return>", self.send_message)

        send_btn = ctk.CTkButton(
            input_frame,
            text="Send",
            width=100,
            command=self.send_message
        )

        send_btn.grid(row=0, column=2, padx=(5, 10), pady=10)

    # -----------------------
    # Chat Logic
    # -----------------------

    def send_message(self, event=None):

        message = self.message_entry.get().strip()

        if message == "":
            return

        self.add_message(message, sender="user")

        self.message_entry.delete(0, "end")

        # Placeholder system response
        response = self.generate_response(message)

        self.add_message(response, sender="system")

    # -----------------------
    # Basic AI Response
    # -----------------------

    def generate_response(self, message):

        message = message.lower()

        if "benefit" in message:
            return "I can help you find student benefits based on your profile."

        elif "scholarship" in message:
            return "You may qualify for several scholarship programs."

        elif "insurance" in message:
            return "Some insurance discounts may apply to students."

        else:
            return "Ask me about scholarships, benefits, or student programs."

    # -----------------------
    # File Upload
    # -----------------------

    def upload_file(self):

        file_path = filedialog.askopenfilename()

        if file_path:
            self.add_message(f"Uploaded file:\n{file_path}", sender="system")