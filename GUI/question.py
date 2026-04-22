from answers import save_answers
import customtkinter as ctk
from tkinter import filedialog
from chat import ChatPage
from settings import SettingsOverlay
import json 
with open("institutions.json", "r") as f:
    INSTITUTIONS = json.load(f)


class QuestionPage(ctk.CTkFrame):

    def __init__(self, parent, controller, selected_options):
        super().__init__(parent)
        self.controller = controller
        self.update_mode = False 
        self.target_question = None 
        self.section_update_mode = False

        if selected_options is None:
            selected_options = controller.session.get("selected_options",[])

        self.selected_options = selected_options
        self.current_step = 1
        self.current_question_index = 0

        # Store answers in memory before writing JSON
        self.user_answers = {}

        self.questions = {
            "Profile": [
                "What is your full legal name?",
                "What is your date of birth?",
                "What county and zip code do you live in?",
                "What is your gender?",
                "Are you a U.S citizen or permanent resident?",
                "What is your residency status?(In-state/ Out-of-state/ International)",
                "Are you a veteran or active-duty military?",
                "Do you have dependents?",
                "Are you a first-generation college student?",
            ],
            "Academic": [    
                "What is your institution name?",
                "What is your current year/classification? (Freshman / Sophomore / Junior / Senior / Graduate)",
                "Are you enrolled full-time or part-time?",
                "What is your major or intended major?",
                "What is your current GPA?",
                "Do you have access to a student email address?",
                "Are you enrolled in an accredited institution?"
            ],
            "Health & Wellness": [
                "Do you currently have health insurance?",
                "Are you covered under a parent or guardian's plan?",
                "Do you take any regular medications?",
                "Do you have a disability registered with your institution?",
                "Are you registered with your campus health center?",
                "Are you aware of campus mental health or counseling services?"
            ],
            "Insurance": [
                "Do you have car insurance?",
                "Do you have renter's insurance?",
                "Have you filed any claims in the last year?"
            ],
            "Financial Aid & Scholarships": [
                "What is your current employment status?",
                "What is your estimated household income range? (Under $20k / $20k-$40k / $40k-$60k / $60k-$80k / $80k+)",
                "Have you completed the FAFSA for this academic year?",
                "Do you know your Student Aid Index (SAI) or expected family contribution?",
                "Are you Pell Grant eligible?",
                "Have you received work-study funding?",
                "Are you currently receiving any scholarships?",
                "If yes, what is the total annual scholarship amount?",
                "Are you aware of departmental scholarships specific to your major?",
                "Have you visited your campus financial aid office this academic year?"
            ],
            "Housing & Food": [
                "Do you live on campus, off campus, or with family?",
                "Do you currently have a meal plan?",
                "Have you experienced food insecurity during your time as a student?",
                "Have you experienced housing insecurity during your time as a student?",
            ],
            "Technology & Access": [
                "Do you have a personal laptop or computer?",
                "Do you have reliable internet access at home?",
                "Are you aware of any software or hardware programs offered by your institution?"
            ],
            "Other": [
                "Is there anything else about your situation that you think might be relevant to finding benefits? (open text field)"
            ]
        }

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_content()

    # Top Bar
    def create_top_bar(self):

        top_bar = ctk.CTkFrame(self, height=60)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top_bar,
            text="Student Benefit Analyzer",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(top_bar, height=15)
        self.progress_bar.grid(row=1, column=1, padx=20, pady=20, sticky="ew")

        self.progress_label = ctk.CTkLabel(
            top_bar,
            text="",
            font=ctk.CTkFont(size=14)
        )
        self.progress_label.grid(row=0, column=1, sticky="s", pady=(5, 0))

        ctk.CTkButton(
            top_bar,
            text="Settings",
            command=self.open_settings
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")

        self.update_progress()

    def open_settings(self):
        SettingsOverlay(self.master, self)

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
            text=f"Section {self.current_step} of {total_steps}: {current_section}"
        )

    # Content
    def create_content(self):

        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            main_frame,
            text="Tell us about yourself!",
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w"
        ).pack(pady=(30, 10), padx=60, anchor="w")

        question_card = ctk.CTkFrame(main_frame, corner_radius=15)
        question_card.pack(padx=40, pady=20, fill="both", expand=True)

        self.question_label = ctk.CTkLabel(
            question_card,
            text=self.get_current_question(),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=800
        )

        self.question_label.pack(pady=(25, 15), padx=20, anchor="w")

        input_row = ctk.CTkFrame(question_card, fg_color="transparent")
        input_row.pack(padx=20, pady=10, fill="x")

        input_row.grid_columnconfigure(0, weight=1)
        # ALWAYS create StringVar
        self.answer_var = ctk.StringVar()
        self.answer_var.trace_add("write", self.update_dropdown)

        # Entry (used for ALL questions)
        self.answer_entry = ctk.CTkEntry(
            input_row,
            textvariable=self.answer_var,
            placeholder_text="Type your answer here...",
            height=40
        )
        self.answer_entry.grid(row=0, column=0, padx=(0, 10), sticky="ew")

        # Dropdown (used ONLY for institution)
        self.dropdown = ctk.CTkScrollableFrame(input_row, height=150)
        self.dropdown.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.dropdown.grid_remove()
        ctk.CTkButton(
            input_row,
            text="Upload Document",
            width=150,
            command=self.upload_document
        ).grid(row=0, column=1)

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

        # Always create it, but don't show yet
        self.save_close_button = ctk.CTkButton(
            button_row,
            text="Save & Close",
            width=160,
            fg_color="#2E8B57",
            hover_color="#1E5F3A",
            command=self.save_and_close
        )
        if self.update_mode:
            self.next_button.configure(text="Finish")
            self.section_update_mode = False  # single question mode
            self.save_close_button.grid_forget()
        elif self.section_update_mode:
            self.next_button.configure(text="Finish")

            if not self.save_close_button.winfo_ismapped():
                self.save_close_button.grid(row=0, column=2, padx=10)

        else:
            #if hasattr(self, "save_close_button") and self.save_close_button.winfo_ismapped():
            self.save_close_button.grid_forget()
        self.next_button.grid(row=0, column=1, padx=10)
        # self.bind("<Return>", lambda event: self.next_action())
        self.focus_set()

        # self.answer_entry.bind("<Return>", lambda event: self.next_action())
        self.answer_entry.bind("<Return>", lambda event: self.on_enter())
        self.update_next_button_text()

    def is_institution_question(self):
        return self.get_current_question() == "What is your institution name?"

    def select_institution(self, school_name):
        self.answer_var.set(school_name)
        self.dropdown.grid_remove()

    def get_selected_institution(self):
        value = self.answer_var.get().lower()

        for inst in INSTITUTIONS:
            names = [inst["name"]] + inst.get("aliases", [])
            for name in names:
                if value == name.lower():
                    return inst  # canonical

        return {
            "name": self.answer_var.get(),
            "aliases": [],
            "domain": "",
            "state": ""
        }

    def update_dropdown(self, *args):
        if not self.is_institution_question():
            return

        query = self.answer_var.get().lower()

        # Clear previous results
        for widget in self.dropdown.winfo_children():
            widget.destroy()

        if not query:
            self.dropdown.grid_remove()
            return

        matches = []

        for inst in INSTITUTIONS:
            names = [inst["name"]] + inst.get("aliases", [])
            for name in names:
                if query in name.lower():
                    matches.append(inst["name"])
                    break

        matches = list(dict.fromkeys(matches))[:10]  # dedupe + limit

        if not matches:
            self.dropdown.grid_remove()
            return

        self.dropdown.grid()

        for school in matches:
            btn = ctk.CTkButton(
                self.dropdown,
                text=school,
                anchor="w",
                command=lambda s=school: self.select_institution(s)
            )
            btn.pack(fill="x", padx=5, pady=2)

    # Question Logic
    def get_current_question(self):
        if not self.selected_options or self.current_step > len(self.selected_options):
            return "No more questions."

        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        if not section_questions:
            return f"No questions for {current_section}"

        return section_questions[self.current_question_index]

    # Upload
    def upload_document(self):

        file_path = filedialog.askopenfilename()

        if file_path:
            print("Selected file:", file_path)

    # Next Button
    def next_action(self):
        

        if self.is_institution_question():
            answer = self.get_selected_institution()
        else:
            answer = self.answer_entry.get()
        question = self.get_current_question()
        current_section = self.selected_options[self.current_step - 1]

        username = self.controller.session["username"]

        # Save to JSON
        save_answers(username, question, current_section, answer)

        # Store locally
        if getattr(self, "update_mode", False):
            print("Single question updated")
            self.controller.show_page("chat")
            return
        if current_section not in self.user_answers:
            self.user_answers[current_section] = {}

        self.user_answers[current_section][question] = answer

        section_questions = self.questions.get(current_section, [])

        # Next question
        if self.current_question_index < len(section_questions) - 1:
            self.current_question_index += 1

        else:
            # Next section
            if self.current_step < len(self.selected_options):
                self.current_step += 1
                self.current_question_index = 0
            else:
                print("All sections completed!")
                # Mark questionnaire completed
                from auth import mark_questionnaire_completed

                username = self.controller.session["username"]
                mark_questionnaire_completed(username)

                # Navigate via controller
                self.controller.session["questionnaire_completed"] = True  
                self.controller.show_page("chat")
                return

        #self.answer_entry.delete(0, "end")
        #self.question_label.configure(text=self.get_current_question())
        self.current_question_index = max(0, self.current_question_index)
        self.refresh_current_question()
        self.update_progress()
        self.update_next_button_text()
        print("Q Index:", self.current_question_index)
        print("Step:", self.current_step)
        print("Section:", self.selected_options[self.current_step - 1])
        #self.update_progress()
        #self.update_next_button_text()

    # Back Button
    def back_action(self):

        if self.current_question_index > 0:
            self.current_question_index -= 1

        elif self.current_step > 1:
            self.current_step -= 1

            previous_section = self.selected_options[self.current_step - 1]

            self.current_question_index = len(
                self.questions.get(previous_section, [])
            ) - 1
        else:
            print("Already at first question")
            return

        self.answer_entry.delete(0, "end")

        self.question_label.configure(text=self.get_current_question())

        self.update_progress()
        self.update_next_button_text()

    def update_next_button_text(self):

        # UPDATE MODE
        if self.update_mode:
            self.next_button.configure(text="Finish")
            self.save_close_button.grid_forget()

            return
        # SECTION UPDATE MODE (full section edit)
        if self.section_update_mode:

            current_section = self.selected_options[self.current_step - 1]
            section_questions = self.questions.get(current_section, [])

            if self.current_question_index < len(section_questions) - 1:
                self.next_button.configure(text="Next")
            elif self.current_step < len(self.selected_options):
                next_section = self.selected_options[self.current_step]
                self.next_button.configure(text=f"Next: {next_section}")
            else:
                self.next_button.configure(text="Finish")
            if not self.save_close_button.winfo_ismapped():
                self.save_close_button.grid(row=0, column=2, padx=10)
            return

        # NORMAL MODE → hide button if visible
        if hasattr(self, "save_close_button") and self.save_close_button.winfo_ismapped():
            #self.save_close_button.grid_forget()
            if not self.save_close_button.winfo_ismapped():
                self.save_close_button.grid(row=0, column=2, padx=10)
            return


        if not self.selected_options or self.current_step > len(self.selected_options):
            self.next_button.configure(text="Finish")
            return

        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        if self.current_question_index < len(section_questions) - 1:
            self.next_button.configure(text="Next")
        elif self.current_step < len(self.selected_options):
            next_section = self.selected_options[self.current_step]
            self.next_button.configure(text=f"Next: {next_section}")
        else:
            self.next_button.configure(text="Finish")
    
    # Inside QuestionPage class
    def refresh_current_question(self):
        if not self.winfo_exists():
            return
        if not hasattr(self, "question_label") or not self.question_label.winfo_exists():
            return

        if not self.selected_options:
            self.question_label.configure(text="No section selected")
            return
        question = self.get_current_question()
        self.question_label.configure(text=question)

        self.answer_var.set("")
        self.dropdown.grid_remove()
        if self.is_institution_question():
            self.answer_entry.configure(
                placeholder_text="Enter you institution name..."
            )
        else:
            self.answer_entry.configure(
                placeholder_text="Type your answer here..."
            )

        current_section = self.selected_options[self.current_step - 1]
        section_questions = self.questions.get(current_section, [])

        if not section_questions:
            self.question_label.configure(text=f"No questions for {current_section}")
            return

        if self.current_question_index >= len(section_questions):
            self.question_label.configure(text="No more questions")
            return

        # Update question label
        self.question_label.configure(text=section_questions[self.current_question_index])
        
        # Clear entry
        self.answer_entry.delete(0, "end")

        # Update progress bar and button text
        self.update_progress()
        self.update_next_button_text()

    def save_and_close(self):
        answer = self.answer_entry.get()
        question = self.get_current_question()
        current_section = self.selected_options[self.current_step - 1]

        username = self.controller.session["username"]

        # Save exactly like next_action
        from answers import save_answers
        save_answers(username, question, current_section, answer)

        print("Saved and exiting update mode")

        self.controller.show_page("chat")

    def on_enter(self):
        # In update mode, Enter should NOT do anything except maybe ignore or optional save

        self.next_action()