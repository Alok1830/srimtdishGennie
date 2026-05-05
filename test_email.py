import os
from dotenv import load_dotenv
from django.core.mail import send_mail
from django.conf import settings
import django

# Load env
load_dotenv(".env")

# Minimal Django settings to test email
settings.configure(
    EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
    EMAIL_HOST=os.environ.get("EMAIL_HOST", "smtp.gmail.com"),
    EMAIL_PORT=int(os.environ.get("EMAIL_PORT", 587)),
    EMAIL_USE_TLS=True,
    EMAIL_HOST_USER=os.environ.get("EMAIL_HOST_USER", ""),
    EMAIL_HOST_PASSWORD=os.environ.get("EMAIL_HOST_PASSWORD", ""),
    DEFAULT_FROM_EMAIL=os.environ.get("EMAIL_HOST_USER", ""),
)
django.setup()

print("Testing SMTP Connection...")
print(f"User: {settings.EMAIL_HOST_USER}")

try:
    send_mail(
        "Test Email from Django",
        "If you receive this, SMTP is working.",
        settings.DEFAULT_FROM_EMAIL,
        [settings.EMAIL_HOST_USER], # send to self
        fail_silently=False,
    )
    print("SUCCESS: Email sent successfully!")
except Exception as e:
    print(f"FAILED: {type(e).__name__} - {e}")
