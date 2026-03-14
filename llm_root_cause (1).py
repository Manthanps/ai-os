"""LLM-based root-cause analysis using local Ollama models."""

import json
import os
import subprocess
from typing import Dict, List

DEFAULT_MODEL = os.environ.get("DEBUGGER_LLM_MODEL", "qwen2.5:7b")

SYSTEM_PROMPT = (
    "You are a debugging assistant. Given recent logs and structured findings, "
    "return a JSON array of root-cause hypotheses. Each item must have: "
    "reason (string) and confidence (0-1 float). Keep reasons concise. "
    "Return ONLY JSON."
)


def _extract_json(text: str):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def generate_root_cause(logs: List[str], findings: List[Dict], model: str = None) -> List[Dict]:
    model = model or DEFAULT_MODEL
    prompt = SYSTEM_PROMPT + "\n\n" + "Findings:\n" + json.dumps(findings) + "\n\nLogs:\n"
    prompt += "\n".join(logs)
    prompt += "\n\nJSON:"  # signal for model

    try:
        output = subprocess.check_output(["ollama", "run", model, prompt], text=True, timeout=45)
    except Exception:
        return []

    data = _extract_json(output)
    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason", "")).strip()
        try:
            confidence = float(item.get("confidence", 0))
        except Exception:
            confidence = 0.0
        if reason:
            results.append({"reason": reason, "confidence": round(confidence, 2)})
    return results
