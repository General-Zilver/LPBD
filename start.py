import customtkinter as ctk
from login import LoginPage
from main import WelcomePage

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Student Benefit Analyzer")
        self.geometry("650x500")

        # Load login page
        login_page = LoginPage(self)
        login_page.pack(fill="both", expand=True)
        # main_page = WelcomePage(self)
        # main_page.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = App()
    app.mainloop()
