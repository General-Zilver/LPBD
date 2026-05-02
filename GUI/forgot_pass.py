import smtplib
from email.mime.text import MIMEText

def reset_email_link(email, token):
    reset_link = f"http://localhost:5000/reset_password?token={token}"

    msg = MIMEText(f"Reset your password: {reset_link}")
    msg["Subject"] = "Password Reset"
    msg["From"] = "support@myapp.com"
    msg["To"] = email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login("support@myapp.com", "App Password")
        server.send.message(msg)