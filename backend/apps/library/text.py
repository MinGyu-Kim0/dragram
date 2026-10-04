import hashlib
import unicodedata


def normalize_sentence(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sentence_hash(text):
    return hashlib.sha256(normalize_sentence(text).encode("utf-8")).hexdigest()
