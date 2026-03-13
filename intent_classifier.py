import difflib
import re

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

_spacy_nlp = None
_transformer = None
def _config_path():
    import os
    return os.path.join(os.path.dirname(__file__), "nlp_config.json")


def _load_config():
    try:
        import json
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "use_spacy": True,
            "use_transformers": True,
            "transformer_model": "distilbert-base-uncased",
            "spacy_model": "en_core_web_sm",
        }


def _load_spacy():
    global _spacy_nlp
    if _spacy_nlp is not None:
        return _spacy_nlp
    try:
        import spacy
        cfg = _load_config()
        if not cfg.get("use_spacy", True):
            _spacy_nlp = None
            return _spacy_nlp
        _spacy_nlp = spacy.load(cfg.get("spacy_model", "en_core_web_sm"))
    except Exception:
        _spacy_nlp = None
    return _spacy_nlp


def _load_transformer():
    global _transformer
    if _transformer is not None:
        return _transformer
    try:
        cfg = _load_config()
        if not cfg.get("use_transformers", True):
            _transformer = None
            return _transformer
        from transformers import pipeline
        model_name = cfg.get("transformer_model", "distilbert-base-uncased")
        _transformer = pipeline("zero-shot-classification", model=model_name)
    except Exception:
        _transformer = None
    return _transformer


INTENTS = {
    "OPEN_APP": ["open app", "launch", "start app", "open"],
    "CLOSE_APP": ["close app", "quit app", "close", "quit"],
    "SEARCH_WEB": ["search web", "search", "google", "find on web"],
    "FIND_FILE": ["find file", "search file", "locate file", "find"],
    "WORK_MODE": ["study mode", "coding mode", "relax mode", "work mode"],
    "RUN_MODEL": ["run model", "run heart model", "predict patient risk"],
}


def _fuzzy_score(text, phrase):
    if fuzz is not None:
        return fuzz.partial_ratio(text, phrase) / 100.0
    return difflib.SequenceMatcher(None, text, phrase).ratio()


def _spacy_score(text, phrase):
    nlp = _load_spacy()
    if not nlp:
        return 0.0
    try:
        if getattr(nlp.vocab, "vectors_length", 0) == 0:
            return 0.0
        doc = nlp(text)
        term = nlp(phrase)
        return doc.similarity(term)
    except Exception:
        return 0.0


def _transformer_intent(text):
    classifier = _load_transformer()
    if not classifier:
        return None
    labels = list(INTENTS.keys())
    try:
        result = classifier(text, labels)
        if result and result.get("labels"):
            return {
                "intent": result["labels"][0],
                "confidence": float(result["scores"][0]),
            }
    except Exception:
        return None
    return None


def classify(text):
    t = text.lower().strip()
    best_intent = None
    best_score = 0.0
    params = {}

    # 1) Transformer (if enabled) for coarse intent
    tf_result = _transformer_intent(t)
    if tf_result and tf_result["confidence"] >= 0.6:
        best_intent = tf_result["intent"]
        best_score = tf_result["confidence"]

    # 2) Rule + fuzzy + spaCy similarity
    for intent, phrases in INTENTS.items():
        for phrase in phrases:
            score = 1.0 if phrase in t else max(_fuzzy_score(t, phrase), _spacy_score(t, phrase))
            if score > best_score:
                best_score = score
                best_intent = intent

    if best_intent == "OPEN_APP":
        # If user didn't mention app/application as a token, assume web open instead.
        if not _has_app_token(t):
            best_intent = "SEARCH_WEB"
            params["query"] = _extract_search_query(t)
        else:
            params["app"] = _extract_app_name(text)
    elif best_intent == "CLOSE_APP":
        params["app"] = _extract_app_name(text)
    elif best_intent == "SEARCH_WEB":
        params["query"] = _extract_search_query(t)
    elif best_intent == "FIND_FILE":
        params["query"] = t.replace("find", "").replace("file", "").replace("search", "").strip()
    elif best_intent == "WORK_MODE":
        if "study" in t:
            params["mode"] = "STUDY"
        elif "coding" in t:
            params["mode"] = "CODING"
        elif "relax" in t:
            params["mode"] = "RELAX"
    elif best_intent == "RUN_MODEL":
        if "heart" in t:
            params["model"] = "heart"
        elif "risk" in t:
            params["model"] = "risk"

    return {"intent": best_intent, "confidence": round(best_score, 2), "parameters": params}


def nlp_status():
    cfg = _load_config()
    return {
        "use_spacy": cfg.get("use_spacy", True),
        "use_transformers": cfg.get("use_transformers", True),
        "spacy_loaded": _load_spacy() is not None,
        "transformer_loaded": _load_transformer() is not None,
        "spacy_model": cfg.get("spacy_model", "en_core_web_sm"),
        "transformer_model": cfg.get("transformer_model", "distilbert-base-uncased"),
    }


def _extract_app_name(text):
    t = text
    for token in ["please", "plz", "open", "close", "quit", "the"]:
        t = re.sub(rf"\\b{re.escape(token)}\\b", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\\bapp\\b", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\\bapplication\\b", " ", t, flags=re.IGNORECASE)
    t = " ".join(t.split())
    return t.strip()


def _has_app_token(text):
    return bool(re.search(r"\\bapp\\b", text)) or bool(re.search(r"\\bapplication\\b", text))


def _extract_search_query(text):
    t = text
    for token in ["please", "plz", "search", "google", "open", "the"]:
        t = t.replace(token, " ")
    t = " ".join(t.split())
    return t.strip()
