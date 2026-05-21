import imaplib
import os
from dotenv import load_dotenv
load_dotenv()

mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
mail.login(os.getenv("GMAIL_EMAIL"), os.getenv("GMAIL_PASSWORD"))
print("Connected successfully")
mail.logout()