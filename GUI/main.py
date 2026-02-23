import customtkinter as ctk
from question import QuestionPage

class WelcomePage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_content()

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
            text="Settings"
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")

    def handle_selection(self):
        selected_options = []

        if self.health_var.get() == "on":
            selected_options.append("Health")
        if self.insurance_var.get() == "on":
            selected_options.append("Insurance")
        if self.licensing_var.get() == "on":
            selected_options.append("Licensing")
        if self.scholarships_var.get() == "on":
            selected_options.append("Scholarships")
        if self.other_var.get() == "on":
            selected_options.append("Other")

    def create_content(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)

        # Welcome Text
        ctk.CTkLabel(
            main_frame,
            text="Welcome to the Student Benefit Analyzer",
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w"
        ).pack(pady=(40, 10), padx=60, anchor="w")

        ctk.CTkLabel(
            main_frame,
            text="Tell us about yourself.",
            font=ctk.CTkFont(size=18),
            anchor="w"
        ).pack(pady=(0, 10),padx=100, anchor="w")

        # Selection Section
        selection_card = ctk.CTkFrame(main_frame, corner_radius=15)
        selection_card.pack(padx=10, pady=10, fill="both", expand=True)

        ctk.CTkLabel(
            selection_card,
            text="What are you interested in?",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        ).pack(pady=(20, 10),padx=20,anchor="w")

        # Inner square box for options
        options_box = ctk.CTkFrame(
            selection_card,
            height=250,
            corner_radius=10
        )
        options_box.pack(pady=10,padx=20, fill="x")
        options_box.pack_propagate(False)

        # Configure 2 columns
        options_box.grid_columnconfigure(0, weight=1)
        options_box.grid_columnconfigure(1, weight=1)

        # Variables
        self.health_var = ctk.StringVar(value="off")
        self.insurance_var = ctk.StringVar(value="off")
        self.licensing_var = ctk.StringVar(value="off")
        self.scholarships_var = ctk.StringVar(value="off")
        self.other_var = ctk.StringVar(value="off")

        # Row 1
        ctk.CTkCheckBox(
            options_box, text="Health",
            variable=self.health_var,
            onvalue="on", offvalue="off",
            font=ctk.CTkFont(size=16)
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Insurance",
            variable=self.insurance_var,
            onvalue="on", offvalue="off",
            font=ctk.CTkFont(size=16)
        ).grid(row=0, column=1, padx=20, pady=15, sticky="w")

        # Row 2
        ctk.CTkCheckBox(
            options_box, text="Licensing",
            variable=self.licensing_var,
            onvalue="on", offvalue="off",
            font=ctk.CTkFont(size=16)
        ).grid(row=1, column=0, padx=20, pady=15, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Scholarships",
            variable=self.scholarships_var,
            onvalue="on", offvalue="off",
            font=ctk.CTkFont(size=16)
        ).grid(row=1, column=1, padx=20, pady=15, sticky="w")

        # Row 3
        ctk.CTkCheckBox(
            options_box, text="Other",
            variable=self.other_var,
            onvalue="on", offvalue="off",
            font=ctk.CTkFont(size=16)
        ).grid(row=2, column=0, columnspan=2, pady=15)

        # Select Button
        ctk.CTkButton(
            selection_card,
            text="Select",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=40,
            command=self.handle_selection
        ).pack(pady=(0, 10))
