# ollama_client.py -- Talks to the local Ollama server for LLM inference.
# Used by match.py for benefit matching, the GUI chat page, and the
# matching pipeline embedder.

import requests

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "llama3:8b"
EMBED_MODEL = "nomic-embed-text"


# Checks if Ollama is running and the requested model is pulled.
# Returns (True, None) on success or (False, "error message") on failure.
def check_ollama(model=DEFAULT_MODEL):
    try:
        r = requests.get(OLLAMA_BASE, timeout=3)
        if not r.ok:
            return False, "Ollama server returned an error."
    except requests.ConnectionError:
        return False, "Ollama is not running. Start it with: ollama serve"

    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return False, "Could not list Ollama models."

    if not any(model in m for m in models):
        return False, f"Model '{model}' not found. Pull it with: ollama pull {model}"

    return True, None

import time 
# Sends a one-shot prompt to Ollama and returns the full response text.
# Good for matching where there's no conversation history.
def generate(prompt, system=None, model=DEFAULT_MODEL, retries = 2):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    for attempt in range(retries):
        try:
            r = requests.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=120)
            r.raise_for_status()
            return r.json()["response"]
        except requests.ConnectionError:
            raise ConnectionError("Ollama is not running. Start it with: ollama serve")
        except requests.Timeout:
            if attempt == retries - 1:
                raise TimeoutError("Ollama took too long to respond.")
            time.sleep(2)


# Sends a multi-turn chat request to Ollama and returns the assistant's reply.
# messages is a list of {"role": "system"/"user"/"assistant", "content": "..."}.
def chat(messages, model=DEFAULT_MODEL, retries=2):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    for attempt in range(retries):
        try:
            r = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120)
            r.raise_for_status()
            return r.json()["message"]["content"]
        except requests.ConnectionError:
            raise ConnectionError("Ollama is not running. Start it with: ollama serve")
        except requests.Timeout:
            if attempt == retries - 1:
                raise TimeoutError("Ollama took too long to respond.")
            time.sleep(2)

# Embeds a text string using the given model and returns the vector.
# Uses /api/embed which returns {"embeddings": [[floats]]}.
def embed(text, model=EMBED_MODEL):
    payload = {
        "model": model,
        "input": text,
    }

    try:
        r = requests.post(f"{OLLAMA_BASE}/api/embed", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"][0]
    except requests.ConnectionError:
        raise ConnectionError("Ollama is not running. Start it with: ollama serve")
    except requests.Timeout:
        raise TimeoutError("Ollama took too long to respond.")


# Pulls a model from Ollama's registry. Blocks until the download finishes.
def pull_model(model):
    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/pull",
            json={"name": model, "stream": False},
            timeout=600,
        )
        r.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError("Ollama is not running. Start it with: ollama serve")
    except requests.Timeout:
        raise TimeoutError("Model pull timed out after 10 minutes.")


# Tells Ollama to unload a model from memory immediately.
# Sends a generate request with keep_alive=0 which triggers unload.
def unload_model(model):
    try:
        requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=10,
        )
    except Exception:
        pass
