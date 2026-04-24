import customtkinter as ctk
import json 
import os
#from question import QuestionPage

class SettingsOverlay(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, width=250, fg_color="#444444")  # gray background

        self.parent = parent
        self.controller = controller
        self.question_page = getattr(controller, "question_page", None)  # safe reference
        self.user_answers = self.load_user_answers()

        # Place overlay on right
        self.place(relx=1, rely=0, anchor="ne", relheight=1)

        # Close when clicking outside
        self.click_binding = self.parent.bind("<Button-1>", self.click_outside)

        # Layout
        ctk.CTkLabel(
            self,
            text="Settings",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=20, padx=20, anchor="w")

        # Show Update Form only if user has completed questionnaire
        if getattr(self.controller, "session", {}).get("questionnaire_completed", True) and self.controller.__class__.__name__ == "AppController":
            ctk.CTkButton(
                self,
                text="Update Form",
                command=self.open_update_form
            ).pack(pady=10, padx=20, anchor="w")
            
            ctk.CTkButton(
                self,
                text="Home",
                command=self.go_home
            ).pack(pady=10, padx=20, anchor="w")

        ctk.CTkButton(
            self,
            text="Close App",
            fg_color="#8B0000",  # dark red
            hover_color="#5A0000",
            command=self.close_app
        ).pack(pady=10, padx=20, anchor="w")

        # Spacer
        ctk.CTkLabel(self, text="").pack(expand=True)

        ctk.CTkButton(
            self,
            text="Close",
            fg_color="gray",
            command=self.destroy_overlay
        ).pack(pady=20, padx=20, anchor="s")

    def click_outside(self, event):
        print (self.controller.__class__.__name__)
        if not self.winfo_exists():
            return
        x1, y1 = self.winfo_rootx(), self.winfo_rooty()
        x2, y2 = x1 + self.winfo_width(), y1 + self.winfo_height()
        if not (x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2):
            self.destroy_overlay()
    def load_user_answers(self):
        session = getattr(self.controller, "session", {})
        username = session.get("username")
        filepath = "answers.json"
        if not os.path.exists(filepath):
            return {}
        with open(filepath, "r") as f:
            data = json.load(f)
        return data.get(username, {})
    
    def destroy_overlay(self):
        if getattr(self, "click_binding", None):
            try:
                self.parent.unbind("<Button-1>", self.click_binding)
            except Exception:
                pass
            self.click_binding = None
        if self.winfo_exists():
            self.destroy()

    def open_update_form(self):
        from question import QuestionPage

        # Always create a fresh QuestionPage to avoid stale widget references
        if self.question_page is not None:
            try:
                self.question_page.destroy()
            except Exception:
                pass

        selected_options = list(self.user_answers.keys()) or []
        self.question_page = QuestionPage(
            self.parent,
            self.controller,
            selected_options
        )
        self.destroy_overlay()

        if self.controller.current_page:
            self.controller.current_page.destroy()

        self.controller.current_page = UpdatePage(
            parent=self.parent,
            controller=self.controller,
            question_page=self.question_page,
            user_answers=self.user_answers
        )
        self.controller.current_page.pack(fill="both", expand=True)

    def return_to_question(self):
        for child in self.parent.winfo_children():
            if isinstance(child, UpdatePage):
                child.destroy()
        if self.question_page:
            self.question_page.pack(fill="both", expand=True)

    def close_app(self):
        try:
            # Optional: save anything here before exit
            print("Closing app gracefully...")

            root = self.winfo_toplevel()

            # Proper Tkinter shutdown sequence
            root.quit()      # stop mainloop
            root.destroy()   # destroy all widgets

        except Exception as e:
            print(f"Error during shutdown: {e}")
    def go_home(self):
        # Close overlay first
        self.destroy_overlay()

        # Destroy current page if it exists
        if getattr(self.controller, "current_page", None):
            try:
                self.controller.current_page.destroy()
            except Exception:
                pass

        # Go back to chat page
        self.controller.show_page("chat")


class UpdatePage(ctk.CTkFrame):
    def __init__(self, parent, controller, question_page, user_answers):
        super().__init__(parent)

        self.controller = controller
        self.question_page = question_page
        self.user_answers = user_answers

        self.create_top_bar()
        self.create_scroll_area()

    # -----------------------
    # TOP BAR (matches ChatPage)
    # -----------------------
    def create_top_bar(self):

        top_bar = ctk.CTkFrame(self, height=60)
        top_bar.pack(fill="x")

        ctk.CTkLabel(
            top_bar,
            text="Student Benefit Analyzer",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left", padx=20, pady=15)

        ctk.CTkButton(
            top_bar,
            text="Settings",
            command=self.open_settings
        ).pack(side="right", padx=20, pady=15)

    def open_settings(self):
        SettingsOverlay(self.master, self.controller)

    # -----------------------
    # SCROLL AREA (NO CANVAS)
    # -----------------------
    def create_scroll_area(self):

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Title
        ctk.CTkLabel(
            self.scroll_frame,
            text="Update Form",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=20)

        # Sections
        for section_name, questions in self.question_page.questions.items():

            section_box = ctk.CTkFrame(self.scroll_frame, corner_radius=10)
            section_box.pack(fill="x", pady=10)

            ctk.CTkLabel(
                section_box,
                text=section_name,
                font=ctk.CTkFont(size=18, weight="bold")
            ).pack(anchor="w", padx=15, pady=(10, 5))

            ctk.CTkButton(
                section_box,
                text="Start Section",
                fg_color="#2B7FFF",
                command=lambda s=section_name: self.start_section(s)
            ).pack(anchor="w", padx=15, pady=5)

            dropdown = ctk.CTkOptionMenu(
                section_box,
                values=questions,
                command=lambda q, s=section_name: self.start_from_question(s, q)
            )
            dropdown.pack(anchor="w", padx=15, pady=(5, 10))

        # Bottom spacing
        ctk.CTkLabel(self.scroll_frame, text="").pack(pady=10)

    # -----------------------
    # LOGIC (unchanged)
    # -----------------------

    def start_section(self, section):
        qp = self.question_page

        qp.selected_options = [section]
        qp.current_step = 1
        qp.current_question_index = 0

        qp.update_mode = False
        qp.section_update_mode = True
        qp.target_question = None

        qp.refresh_current_question()

        if hasattr(qp, "get_current_question") and hasattr(qp, "update_progress"):
            qp.question_label.configure(text=qp.get_current_question())
            qp.update_progress()

        if hasattr(qp, "answer_frame"):
            for widget in qp.answer_frame.winfo_children():
                widget.destroy()

        if hasattr(qp, "render_current_answers"):
            qp.render_current_answers()
        elif hasattr(qp, "create_answer_buttons"):
            qp.create_answer_buttons()

        self.destroy()
        qp.pack(fill="both", expand=True)
        self.controller.current_page = qp

    def start_from_question(self, section, question):
        qp = self.question_page

        qp.selected_options = [section]
        qp.current_step = 1
        qp.current_question_index = qp.questions[section].index(question)

        qp.update_mode = True
        qp.section_update_mode = False
        qp.target_question = question

        qp.refresh_current_question()

        self.destroy()
        qp.pack(fill="both", expand=True)
        self.controller.current_page = qp