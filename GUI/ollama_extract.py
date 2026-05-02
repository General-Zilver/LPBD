import subprocess

def extract(text):
    prompt = f"Extract all meaningful information from this text: \n{text}"
# calls the ollam CLI
    result = subprocess.run(
        ["ollama", "run", "ollama3:8b"], # ollama run ollama 3:8b
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE #capture the models output
    )

    return result.stdout.decode("utf-8")