import customtkinter as ctk
from login import LoginPage
from main import WelcomePage
from question import QuestionPage
from chat import ChatPage
from forgot import ForgotPage

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Student Benefit Analyzer")
        self.geometry("650x500")

        # Load login page
        #login_page = LoginPage(self)
        #login_page.pack(fill="both", expand=True)
        forgot_page = ForgotPage(self)
        forgot_page.pack(fill="both", expand=True)
        #main_page = WelcomePage(self)
        #main_page.pack(fill="both", expand=True)
        #question_page = QuestionPage(self, ["Profile","Health", "Insurance","Scholarships", "Licenses"])
        #question_page.pack(fill="both", expand=True)
        #chat_page = ChatPage(self)
        #chat_page.pack(fill="both", expand=True)

if __name__ == "__main__":
    app = App()
    app.mainloop()
