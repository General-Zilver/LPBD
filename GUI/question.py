import customtkinter as ctk
from tkinter import filedialog


class QuestionPage(ctk.CTkFrame):
    def __init__(self, parent, selected_options):
        super().__init__(parent)

        self.selected_options = selected_options
        self.current_step = 1

        # Questions:
        self.current_question_index = 0

        self.questions = {
            "Profile": [
                "What is your full legal name?",
                "What is your date of birth?",
                "What is your current address?",
                "What is your gender?",
                "Please describe your health history.",
                "What is your current employment status?"
            ],
            "Health": [
                "Do you currently have health insurance?",
                "Are you covered under a parent/guardian plan?",
                "Do you take any regular medications?"
            ],
            "Insurance": [
                "Do you have car insurance?",
                "Do you have renter's insurance?",
                "Have you filed any claims in the last year?"
            ]
        }

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_content()

    #Top bar

    def create_top_bar(self):
        top_bar = ctk.CTkFrame(self, height=60)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(1, weight=1)

        # Title
        ctk.CTkLabel(
            top_bar,
            text="Student Benefit Analyzer",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(top_bar, height=15)
        self.progress_bar.grid(row=1, column=1, padx=20, pady=20, sticky="ew")
        # Progress Text Label
        self.progress_label = ctk.CTkLabel(
            top_bar,
            text="",
            font=ctk.CTkFont(size=14)
        )
        self.progress_label.grid(row=0, column=1, sticky="s", pady=(5, 0))

        # Settings Button
        ctk.CTkButton(
            top_bar,
            text="Settings"
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")

        self.update_progress()

    def update_progress(self):
        total_steps = len(self.selected_options)

        if total_steps == 0:
            self.progress_bar.set(0)
            self.progress_label.configure(text="No sections selected")
            return

        progress_value = self.current_step / total_steps
        self.progress_bar.set(progress_value)

        current_section = self.selected_options[self.current_step - 1]
        self.progress_label.configure(
            text=f"Step {self.current_step} of {total_steps}: {current_section}"
        )
    # Content

    def create_content(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)

        # Page Title
        ctk.CTkLabel(
            main_frame,
            text="Tell us about yourself!",
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w"
        ).pack(pady=(30, 10), padx=60, anchor="w")

        # Card Section
        question_card = ctk.CTkFrame(main_frame, corner_radius=15)
        question_card.pack(padx=40, pady=20, fill="both", expand=True)

        # Question Text
        self.question_label = ctk.CTkLabel(
            question_card,
            text=self.get_current_question(),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w"
        )
        self.question_label.pack(pady=(25, 15), padx=20, anchor="w")

        # Input Row
        input_row = ctk.CTkFrame(question_card, fg_color="transparent")
        input_row.pack(padx=20, pady=10, fill="x")

        input_row.grid_columnconfigure(0, weight=1)

        self.answer_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="Type your answer here...",
            height=40
        )
        self.answer_entry.grid(row=0, column=0, padx=(0, 10), sticky="ew")

        ctk.CTkButton(
            input_row,
            text="Upload Document",
            width=150,
            command=self.upload_document
        ).grid(row=0, column=1)

        # Bottom Buttons
        button_row = ctk.CTkFrame(question_card, fg_color="transparent")
        button_row.pack(pady=(30, 20))

        ctk.CTkButton(
            button_row,
            text="Back",
            width=120,
            fg_color="gray",
            command=self.back_action
        ).grid(row=0, column=0, padx=10)

        self.next_button = ctk.CTkButton(
            button_row,
            text="Next",
            width=160,
            command=self.next_action
        )
        self.next_button.grid(row=0, column=1, padx=10)

    # Logic

    def get_current_question(self):
        if not self.selected_options:
            return "No options selected."

        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        if not section_questions:
            return f"No questions available for {current_section}."

        return section_questions[self.current_question_index]
    def upload_document(self):
        file_path = filedialog.askopenfilename()
        print("Selected file:", file_path)

    def next_action(self):
        answer = self.answer_entry.get()

        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        # Move to next question inside section
        if self.current_question_index < len(section_questions) - 1:
            self.current_question_index += 1

        else:
            # Move to next section
            if self.current_step < len(self.selected_options):
                self.current_step += 1
                self.current_question_index = 0
            else:
                print("All sections completed!")
                return

        self.answer_entry.delete(0, "end")
        self.question_label.configure(text=self.get_current_question())
        self.update_progress()
        self.update_next_button_text()

    def back_action(self):
        if self.current_question_index > 0:
            self.current_question_index -= 1

        elif self.current_step > 1:
            self.current_step -= 1
            previous_section = self.selected_options[self.current_step - 1]
            self.current_question_index = len(self.questions.get(previous_section, [])) - 1

        else:
            print("Already at the first question.")
            return

        self.answer_entry.delete(0, "end")
        self.question_label.configure(text=self.get_current_question())
        self.update_progress()

    def update_next_button_text(self):
        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        # If NOT last question in section
        if self.current_question_index < len(section_questions) - 1:
            self.next_button.configure(text="Next")
            return

        # If last question in section
        if self.current_step < len(self.selected_options):
            next_section = self.selected_options[self.current_step]
            self.next_button.configure(text=f"Next: {next_section}")
        else:
            self.next_button.configure(text="Finish")