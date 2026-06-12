import os
from dotenv import load_dotenv

load_dotenv("../.env")

if os.getenv("GROQ_API_KEY"):
    from app.api.chat_groq import router
else:
    from app.api.chat_gemini import router

__all__ = ["router"]