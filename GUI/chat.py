import customtkinter as ctk
from tkinter import filedialog
from settings import SettingsOverlay
import threading
import json
import sys
from pathlib import Path
import subprocess

# Add project root so we can import ollama_client
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ollama_client


class ChatPage(ctk.CTkFrame):

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.conversation = []
        self.sending = False

        # Load user profile and matched benefits for LLM context
        self.user_profile = self._load_answers()
        self.benefits_context = self._load_benefits()

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_chat_area()
        self.create_input_bar()

    # Loads answers.json to give the LLM the student's profile info
    def _load_answers(self):
        user = self.controller.session.get("username")

        candidates = [
            Path(__file__).resolve().parent.parent / "answers.json",
            Path(__file__).resolve().parent / "answers.json",
        ]

        for path in candidates:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    if not data or user not in data:
                        continue

                    answers = data[user]

                    lines = []
                    for question, section_map in answers.items():
                        for section, answer in section_map.items():
                            if answer:
                                lines.append(f"- {question} {answer}")

                    if lines:
                        return "\n".join(lines)

                except Exception:
                    pass

        return None

    # Loads matched_benefits.json to give the LLM context about the user's benefits
    def _load_benefits(self):
        candidates = [
            Path(__file__).resolve().parent.parent / "matched_benefits.json",
            Path(__file__).resolve().parent / "matched_benefits.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        benefits = json.load(f)
                    if benefits:
                        summary = []
                        for b in benefits[:20]:
                            name = b.get("benefit_name", "Unknown")
                            desc = b.get("description", "")
                            summary.append(f"- {name}: {desc}")
                        return "\n".join(summary)
                except Exception:
                    pass
        return None

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

        input_frame.grid_columnconfigure(4, weight=1)

        upload_btn = ctk.CTkButton(
            input_frame,
            text="Upload",
            width=100,
            command=self.upload_file
        )

        upload_btn.grid(row=0, column=3, padx=(5, 5), pady=10)

        self.message_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Type your message here..."
        )

        self.message_entry.grid(row=0, column=4, sticky="ew", padx=5, pady=10)

        self.message_entry.bind("<Return>", self.send_message)

        send_btn = ctk.CTkButton(
            input_frame,
            text="Send",
            width=100,
            command=self.send_message
        )
        # MAP (Green)
        map_btn = ctk.CTkButton(
            input_frame,
            text="Map",
            width=80,
            fg_color="green",
            hover_color="#006400",
            command=self.run_map
        )
        map_btn.grid(row=0, column=0, padx=5, pady=10)

        # SCRAPE (Yellow)
        scrape_btn = ctk.CTkButton(
            input_frame,
            text="Scrape",
            width=80,
            fg_color="#FFD700",
            text_color="black",
            hover_color="#E6C200",
            command=self.run_scrape
        )
        scrape_btn.grid(row=0, column=1, padx=5, pady=10)

        # MATCH (Purple)
        match_btn = ctk.CTkButton(
            input_frame,
            text="Match",
            width=80,
            fg_color="#800080",
            hover_color="#5A005A",
            command=self.run_match
        )
        match_btn.grid(row=0, column=2, padx=5, pady=10)

        send_btn.grid(row=0, column=5, padx=(5, 10), pady=10)

    # Sends the user's message and kicks off an Ollama call in a background thread
    def send_message(self, event=None):
        message = self.message_entry.get().strip()
        if message == "" or self.sending:
            return

        self.add_message(message, sender="user")
        self.message_entry.delete(0, "end")
        self.sending = True
        self.add_message("Thinking...", sender="system")

        # Build the system prompt with benefit context if available
        system_msg = "You are a helpful student benefit advisor. Answer questions clearly and concisely."
        if self.benefits_context:
            system_msg += f"\n\nHere are the student's matched benefits:\n{self.benefits_context}"

        self.conversation.append({"role": "user", "content": message})

        thread = threading.Thread(target=self._call_ollama, daemon=True)
        thread.start()

    # Runs in a background thread so the GUI doesn't freeze
    def _call_ollama(self):
        try:
            system_content = "You are a helpful student benefit advisor. Answer questions clearly and concisely."
            if self.user_profile:
                system_content += f"\n\nHere is the student's profile:\n{self.user_profile}"
            if self.benefits_context:
                system_content += f"\n\nHere are the student's matched benefits:\n{self.benefits_context}"
            messages = [{"role": "system", "content": system_content}]
            messages.extend(self.conversation)

            reply = ollama_client.chat(messages)
            self.conversation.append({"role": "assistant", "content": reply})
            if self.winfo_exists():
                self.after(0, lambda: self._show_reply(reply))
        except ConnectionError:
            self.after(0, lambda: self._show_reply(
                "Ollama is not running. Please start it and make sure phi3:mini is pulled:\n"
                "  ollama pull phi3:mini"
            ))
        except Exception as e:
            self.after(0, lambda: self._show_reply(f"Error: {e}"))

    # Updates the UI with the LLM response (replaces the "Thinking..." bubble)
    def _show_reply(self, text):
        if not self.winfo_exists():
            return
        try:
            self.sending = False
            # Remove the "Thinking..." bubble (last widget in chat_frame)
            children = self.chat_frame.winfo_children()
            if children:
                children[-1].destroy()
            self.add_message(text, sender="system")
        except:
            pass
    # -----------------------
    # File Upload
    # -----------------------

    def upload_file(self):

        file_path = filedialog.askopenfilename()

        if file_path:
            self.add_message(f"Uploaded file:\n{file_path}", sender="system")

    def run_map(self):
        self.add_message("Running map.py...", sender="system")
        threading.Thread(target=lambda: subprocess.run(["python", "map.py"]), daemon=True).start()

    def run_scrape(self):
        self.add_message("Running scrape_all.py...", sender="system")
        threading.Thread(target=lambda: subprocess.run(["python", "scrape_all.py"]), daemon=True).start()

    def run_match(self):
        user = self.controller.session.get("username", "default_user")

        self.add_message(f"Running match_it.py for user: {user}", sender="system")

        threading.Thread(
            target=lambda: subprocess.run(
                ["python", "match_it.py", "--user", user]
            ),
            daemon=True
        ).start()