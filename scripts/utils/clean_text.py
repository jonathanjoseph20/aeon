import re
import quopri

def clean_email_text(text):
    try:
        text = quopri.decodestring(
            text.encode("utf-8", errors="ignore")
        ).decode("utf-8", errors="ignore")
    except Exception:
        pass

    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"unsubscribe.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"visit us", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)

    return text.strip()