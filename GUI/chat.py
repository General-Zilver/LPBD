import customtkinter as ctk
from tkinter import filedialog
from settings import SettingsOverlay
import threading
import queue
import json
import sys
import os
from pathlib import Path
import subprocess

# Add project root so we can import ollama_client
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import ollama_client

# Sentinel pushed to the line queue when the subprocess stream ends
_STREAM_DONE = object()

# Chat message caps
_MAX_LINES = 25
_MAX_CHARS = 2000
_LOG_FILENAMES = {
    "map": "map.log",
    "scrape": "scrape_all.log",
    "match": "match.log",
}


class ChatPage(ctk.CTkFrame):

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.conversation = []
        self.sending = False

        Path("logs").mkdir(exist_ok=True)

        # Pre-load the Ollama model in the background so the first chat/match is fast
        threading.Thread(target=ollama_client.warmup, daemon=True).start()

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
            PROJECT_ROOT / "answers.json",
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

    # Loads matched_benefits.json for LLM context
    def _load_benefits(self) -> list[dict] | None:
        candidates = [
            PROJECT_ROOT / "matched_benefits.json",
            Path(__file__).resolve().parent / "matched_benefits.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                # Envelope shape: {"results": [...], "last_updated": ..., ...}
                if isinstance(data, dict) and "results" in data:
                    results = data["results"]
                elif isinstance(data, list):
                    results = data
                else:
                    continue

                if results:
                    summary = []
                    for b in results[:20]:
                        name = b.get("benefit_name", "Unknown")
                        desc = b.get("summary", b.get("description", ""))
                        summary.append(f"- {name}: {desc}")
                    return "\n".join(summary)
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

    def add_message(self, message: str, sender: str = "user") -> None:

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

        self._scroll_chat_to_bottom()

    # Posts a bubble containing a clickable button (for report links)
    def _add_report_button(self, report_file: str) -> None:
        bubble = ctk.CTkFrame(self.chat_frame, corner_radius=15)
        bubble.configure(fg_color="#3A3A3A")
        bubble.pack(fill="none", padx=(10, 120), pady=6, anchor="w")

        ctk.CTkButton(
            bubble,
            text=f"Open report: {report_file}",
            command=lambda f=report_file: self._open_report(f),
            fg_color="#2B7FFF",
            hover_color="#1A5FCC",
            width=260,
        ).pack(padx=15, pady=10)

        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self) -> None:
        def scroll() -> None:
            if not self.winfo_exists():
                return
            self.chat_frame.update_idletasks()
            self.chat_frame._parent_canvas.yview_moveto(1)

        self.after_idle(scroll)
        self.after(25, scroll)

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
        self.map_btn = ctk.CTkButton(
            input_frame,
            text="Map",
            width=80,
            fg_color="green",
            hover_color="#006400",
            command=self.run_map
        )
        self.map_btn.grid(row=0, column=0, padx=5, pady=10)

        # SCRAPE (Yellow)
        self.scrape_btn = ctk.CTkButton(
            input_frame,
            text="Scrape",
            width=80,
            fg_color="#FFD700",
            text_color="black",
            hover_color="#E6C200",
            command=self.run_scrape
        )
        self.scrape_btn.grid(row=0, column=1, padx=5, pady=10)

        # MATCH (Purple)
        self.match_btn = ctk.CTkButton(
            input_frame,
            text="Match",
            width=80,
            fg_color="#800080",
            hover_color="#5A005A",
            command=self.run_match
        )
        self.match_btn.grid(row=0, column=2, padx=5, pady=10)

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

    # -----------------------
    # Pipeline Execution
    # -----------------------

    def _set_pipeline_buttons_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.map_btn, self.scrape_btn, self.match_btn):
            btn.configure(state=state)

    def _open_report(self, filename: str) -> None:
        path = Path(filename).resolve()
        if not path.exists():
            self.add_message(f"Report not found at {path}", sender="system")
            return
        if os.name == "nt":
            os.startfile(str(path))
        else:
            import webbrowser
            webbrowser.open(path.as_uri())

    def run_pipeline_command(
        self,
        label: str,
        command: list[str],
        report_stage: str,
        report_file: str,
    ) -> None:
        self._set_pipeline_buttons_state(False)
        self.add_message(f"[{label}] Starting...", sender="system")
        log_path = PROJECT_ROOT / "logs" / _LOG_FILENAMES.get(
            report_stage,
            f"{report_stage}.log",
        )
        log_path.parent.mkdir(exist_ok=True)
        try:
            log_path.write_text(
                f"[{label}] Command: {' '.join(command)}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(PROJECT_ROOT),
            )
        except Exception as e:
            self.add_message(f"[{label}] Failed to start: {e}", sender="system")
            self._set_pipeline_buttons_state(True)
            return

        line_queue: queue.Queue = queue.Queue()
        tail_buffer: list[str] = []

        # Reader thread: reads stdout line by line, pushes to queue
        def reader():
            try:
                log_file = None
                try:
                    log_file = open(log_path, "a", encoding="utf-8")
                except OSError:
                    pass
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\n")
                    if log_file:
                        log_file.write(line + "\n")
                        log_file.flush()
                    line_queue.put(line)
            except Exception:
                pass
            finally:
                if "log_file" in locals() and log_file:
                    log_file.close()
                line_queue.put(_STREAM_DONE)

        threading.Thread(target=reader, daemon=True).start()

        # Polling loop on the main thread
        empty_polls_after_exit = 0

        def drain_queue():
            nonlocal empty_polls_after_exit
            if not self.winfo_exists():
                self._set_pipeline_buttons_state(True)
                return

            batch: list[str] = []
            done = False
            while True:
                try:
                    item = line_queue.get_nowait()
                except queue.Empty:
                    break
                if item is _STREAM_DONE:
                    done = True
                    break
                batch.append(item)
                tail_buffer.append(item)

            if not done and not batch and proc.poll() is not None:
                empty_polls_after_exit += 1
                if empty_polls_after_exit >= 3:
                    done = True
            elif batch:
                empty_polls_after_exit = 0

            # Keep only last 10 lines for error reporting
            if len(tail_buffer) > 10:
                del tail_buffer[:-10]

            if batch:
                self._post_capped(label, batch, report_stage)

            if done:
                self._finish_pipeline_run(
                    label, report_stage, report_file, proc, tail_buffer
                )
            else:
                self.after(100, drain_queue)

        self.after(100, drain_queue)

    def _post_capped(self, label: str, lines: list[str], report_stage: str) -> None:
        # Cap at _MAX_LINES lines and _MAX_CHARS characters
        out: list[str] = []
        char_count = 0
        overflow = 0
        for raw in lines:
            prefixed = f"[{label}] {raw}"
            if len(out) >= _MAX_LINES - 1 or char_count + len(prefixed) > _MAX_CHARS:
                overflow = len(lines) - len(out)
                break
            out.append(prefixed)
            char_count += len(prefixed) + 1  # +1 for newline

        if overflow > 0:
            log_name = _LOG_FILENAMES.get(report_stage, f"{report_stage}.log")
            out.append(f"... {overflow} more lines written to logs/{log_name}")

        self.add_message("\n".join(out), sender="system")

    def _finish_pipeline_run(
        self,
        label: str,
        report_stage: str,
        report_file: str,
        proc: subprocess.Popen,
        tail_buffer: list[str],
    ) -> None:
        try:
            proc.wait()
            code = proc.returncode

            if code == 0:
                self.add_message(f"[{label}] Complete (exit 0).", sender="system")
            else:
                tail_text = "\n".join(tail_buffer[-10:])
                self.add_message(
                    f"[{label}] Failed (exit {code}). Last lines:\n{tail_text}",
                    sender="system",
                )

            # Generate the HTML report via viewer.build
            if code == 0:
                report_built = False
                try:
                    viewer_result = subprocess.run(
                        [sys.executable, "-m", "viewer.build", report_stage],
                        check=False,
                        capture_output=True,
                        text=True,
                        cwd=str(PROJECT_ROOT),
                    )
                    if viewer_result.returncode != 0:
                        self.add_message(
                            f"[{label}] Report generation warning:\n{viewer_result.stderr}",
                            sender="system",
                        )
                    else:
                        report_built = True
                except Exception as e:
                    self.add_message(
                        f"[{label}] Could not generate report: {e}",
                        sender="system",
                    )

                # Check for the report file and show a button to open it
                report_path = PROJECT_ROOT / report_file
                if report_built and report_path.exists():
                    self.add_message(
                        f"[{label}] Report ready:\n{report_path}",
                        sender="system",
                    )
                    self._add_report_button(str(report_path))
                else:
                    self.add_message(
                        f"[{label}] Report was not created: {report_file}",
                        sender="system",
                    )

            # Reload benefits after a successful match run
            if report_stage == "match" and code == 0:
                self.benefits_context = self._load_benefits()
                count = 0
                bpath = PROJECT_ROOT / "matched_benefits.json"
                if bpath.exists():
                    try:
                        with open(bpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict) and "results" in data:
                            count = len(data["results"])
                        elif isinstance(data, list):
                            count = len(data)
                    except Exception:
                        pass
                self.add_message(
                    f"[Match] Loaded {count} benefits into chat context.",
                    sender="system",
                )

        except Exception as e:
            self.add_message(f"[{label}] Internal error: {e}", sender="system")
        finally:
            self._set_pipeline_buttons_state(True)

    def run_map(self) -> None:
        self.run_pipeline_command(
            label="Map",
            command=[sys.executable, "map.py", "--max-pages", "15"],
            report_stage="map",
            report_file="map_report.html",
        )

    def run_scrape(self) -> None:
        self.run_pipeline_command(
            label="Scrape",
            command=[sys.executable, "scrape_all.py"],
            report_stage="scrape",
            report_file="scrape_report.html",
        )

    def run_match(self) -> None:
        user = self.controller.session.get("username", "default_user")
        self.run_pipeline_command(
            label="Match",
            command=[sys.executable, "match.py", "--user", user],
            report_stage="match",
            report_file="benefits.html",
        )
