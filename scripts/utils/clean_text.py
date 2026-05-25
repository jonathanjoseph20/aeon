import re

def clean_email_text(text):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"unsubscribe.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"visit us", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()