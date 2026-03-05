import customtkinter as ctk

class SettingsOverlay(ctk.CTkFrame):
    def __init__(self, parent, question_page):
        super().__init__(parent, width=250, fg_color="#444444")  # gray background

        self.parent = parent
        self.question_page = question_page

        # Place overlay on right
        self.place(relx=1, rely=0, anchor="ne", relheight=1)

        # Close when clicking outside
        self.parent.bind("<Button-1>", self.click_outside)

        # Layout
        ctk.CTkLabel(
            self,
            text="Settings",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=20, padx=20, anchor="w")

        ctk.CTkButton(
            self,
            text="Update Form",
            command=self.open_update_form
        ).pack(pady=10, padx=20, anchor="w")

        # Spacer to push Close button to bottom
        ctk.CTkLabel(self, text="").pack(expand=True)

        ctk.CTkButton(
            self,
            text="Close",
            fg_color="gray",
            command=self.destroy_overlay
        ).pack(pady=20, padx=20, anchor="s")

    def click_outside(self, event):
        if not self.winfo_exists():
            # Overlay already destroyed, do nothing
            return

        # Close if click outside overlay
        x1, y1 = self.winfo_rootx(), self.winfo_rooty()
        x2, y2 = x1 + self.winfo_width(), y1 + self.winfo_height()
        if not (x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2):
            self.destroy_overlay()

    def destroy_overlay(self):
        # Unbind safely
        if getattr(self, "click_binding", None):
            try:
                self.parent.unbind("<Button-1>", self.click_binding)
            except Exception:
                pass
            self.click_binding = None

        if self.winfo_exists():
            self.destroy()
        

    def open_update_form(self):
        self.destroy_overlay()
        self.question_page.pack_forget()
        UpdatePage(
            parent=self.parent,
            question_page=self.question_page,
            close_callback=self.return_to_question
        )

    def return_to_question(self):
        # Destroy UpdatePage and show QuestionPage
        for child in self.parent.winfo_children():
            if isinstance(child, UpdatePage):
                child.destroy()
        self.question_page.pack(fill="both", expand=True)


class UpdatePage(ctk.CTkFrame):
    def __init__(self, parent, question_page, close_callback):
        super().__init__(parent)

        self.question_page = question_page
        self.close_callback = close_callback

        self.pack(fill="both", expand=True)

        # Scrollable Canvas
        canvas = ctk.CTkCanvas(self, bg="#444444", highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(self, orientation="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")

        canvas.configure(yscrollcommand=scrollbar.set)

        self.inner_frame = ctk.CTkFrame(canvas, fg_color="#444444", corner_radius=0)
        canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")

        self.inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Page Title
        ctk.CTkLabel(
            self.inner_frame,
            text="Update Form",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=20)

        # Sections
        for section, questions in self.question_page.questions.items():
            frame = ctk.CTkFrame(self.inner_frame, fg_color="#444444", corner_radius=0)
            frame.pack(padx=20, pady=10, fill="x")

            ctk.CTkLabel(
                frame,
                text=section,
                font=ctk.CTkFont(size=18, weight="bold")
            ).pack(anchor="w", padx=10, pady=(10,5))

            ctk.CTkButton(
                frame,
                text="Start Section",
                command=lambda s=section: self.start_section(s)
            ).pack(anchor="w", padx=15, pady=5)

            dropdown = ctk.CTkOptionMenu(
                frame,
                values=questions,
                command=lambda q, s=section: self.start_from_question(s, q)
            )
            dropdown.pack(anchor="w", padx=15, pady=(5,10))

        # Back button at bottom
        ctk.CTkButton(
            self.inner_frame,
            text="Back",
            fg_color="gray",
            command=self.close_callback
        ).pack(pady=20)

    def start_section(self, section):
        qp = self.question_page
        qp.selected_options = [section]  # only this section
        qp.current_step = 1
        qp.current_question_index = 0
        qp.question_label.configure(text=qp.get_current_question())
        qp.update_progress()
        self.close_callback()

    def start_from_question(self, section, question):
        qp = self.question_page
        qp.selected_options = [section]  # only this section
        qp.current_step = 1
        qp.current_question_index = qp.questions[section].index(question)
        qp.question_label.configure(text=qp.get_current_question())
        qp.update_progress()
        self.close_callback()