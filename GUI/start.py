import customtkinter as ctk
import sys
import threading
from pathlib import Path

from controller import AppController

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import ollama_client


def wake_ollama():
    ok, err = ollama_client.start_server()
    if ok:
        ollama_client.warmup()
    elif err:
        print(f"Ollama startup warning: {err}")


ctk.set_appearance_mode("dark")

root = ctk.CTk()
root.geometry("900x600")

threading.Thread(target=wake_ollama, daemon=True).start()

app = AppController(root)

root.mainloop()
