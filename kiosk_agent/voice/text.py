import re


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def clean_spoken_text(text: str) -> str:
    """Remove visual-only formatting while preserving natural punctuation."""
    clean = _EMOJI_PATTERN.sub("", text)
    clean = re.sub(r"[*_#`\[\]{}<>]", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def split_spoken_text(text: str, max_chars: int = 220) -> list[str]:
    """Create small independently playable chunks without cutting words."""
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?؟؛])\s+", text)
        if part.strip()
    ]
    chunks: list[str] = []
    for sentence in sentences or [text]:
        while len(sentence) > max_chars:
            split_at = sentence.rfind(" ", 0, max_chars + 1)
            split_at = split_at if split_at > 0 else max_chars
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks[:8]
