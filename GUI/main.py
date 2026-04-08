import customtkinter as ctk
from settings import SettingsOverlay



class WelcomePage(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)

        self.controller = controller

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
            text="Settings",
            command=self.open_settings
        ).grid(row=0, column=2, padx=20, pady=15, sticky="e")

    def open_settings(self):
        SettingsOverlay(self.master, self)

    def handle_selection(self):
        selected_options = []

        if self.academic_var.get() == "on":
            selected_options.append("Academic")

        if self.health_var.get() == "on":
            selected_options.append("Health & Wellness")

        if self.insurance_var.get() == "on":
            selected_options.append("Insurance")

        if self.financial_var.get() == "on":
            selected_options.append("Financial Aid & Scholarships")

        if self.housing_var.get() == "on":
            selected_options.append("Housing & Food")

        if self.tech_var.get() == "on":
            selected_options.append("Technology & Access")
        
        if self.other_var.get() == "on":
                    selected_options.append("Other")

        return selected_options

    def create_content(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)

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
        ).pack(pady=(0, 10), padx=100, anchor="w")

        selection_card = ctk.CTkFrame(main_frame, corner_radius=15)
        selection_card.pack(padx=40, pady=20, fill="both", expand=True)
        
        ctk.CTkLabel(
            selection_card,
            text="What are you interested in?",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        ).pack(pady=(20, 10), padx=20, anchor="w")

        options_box = ctk.CTkFrame(selection_card, corner_radius=10)
        options_box.pack(pady=20, padx=40, fill="both")

        # Even spacing
        for i in range(4):  # 4 rows now
            options_box.grid_rowconfigure(i, weight=1)

        for j in range(2):
            options_box.grid_columnconfigure(j, weight=1)
        
        self.academic_var = ctk.StringVar(value="off")
        self.health_var = ctk.StringVar(value="off")
        self.insurance_var = ctk.StringVar(value="off")
        self.financial_var = ctk.StringVar(value="off")
        self.housing_var = ctk.StringVar(value="off")
        self.tech_var = ctk.StringVar(value="off")
        self.other_var = ctk.StringVar(value="off")

        ctk.CTkCheckBox(
            options_box, text="Academic",
            variable=self.academic_var,
            onvalue="on", offvalue="off"
        ).grid(row=0, column=0, padx=20, pady=10, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Health & Wellness",
            variable=self.health_var,
            onvalue="on", offvalue="off"
        ).grid(row=0, column=1, padx=20, pady=10, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Insurance",
            variable=self.insurance_var,
            onvalue="on", offvalue="off"
        ).grid(row=1, column=0, padx=20, pady=10, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Financial Aid & Scholarships",
            variable=self.financial_var,
            onvalue="on", offvalue="off"
        ).grid(row=1, column=1, padx=20, pady=10, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Housing & Food",
            variable=self.housing_var,
            onvalue="on", offvalue="off"
        ).grid(row=2, column=0, padx=20, pady=10, sticky="w")

        ctk.CTkCheckBox(
            options_box, text="Technology & Access",
            variable=self.tech_var,
            onvalue="on", offvalue="off"
        ).grid(row=2, column=1, padx=20, pady=10, sticky="w")

        # 👇 Make "Other" centered across both columns
        ctk.CTkCheckBox(
            options_box, text="Other",
            variable=self.other_var,
            onvalue="on", offvalue="off"
        ).grid(row=3, column=0, columnspan=2, pady=10)        
        
        ctk.CTkButton(
            selection_card,
            text="Select",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=40,
            command=self.to_question_page
        ).pack(pady=(10, 25))

    def to_question_page(self):
        selected_options = self.handle_selection()

        # Always start with Profile
        if "Profile" not in selected_options:
            selected_options.insert(0, "Profile")
        print("SELECTED OPTIONS:", selected_options)
        # Store selection in controller
        self.controller.session["selected_options"] = selected_options

        # Show question page
        self.after(10, lambda: self.controller.show_page("question"))