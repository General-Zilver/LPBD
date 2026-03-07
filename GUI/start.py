import customtkinter as ctk
from controller import AppController

ctk.set_appearance_mode("dark")

root = ctk.CTk()
root.geometry("900x600")

app = AppController(root)

root.mainloop()