import os
import shutil
import webbrowser
import json
import zipfile

MEMORY_FILE = "memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)

# FILE & FOLDER
def create_folder(name):
    os.makedirs(name, exist_ok=True)
    return f"Folder '{name}' created"

def delete_folder(name):
    shutil.rmtree(name)
    return f"Folder '{name}' deleted"

def create_file(name):
    open(name, "w").close()
    return f"File '{name}' created"


def create_file_with_content(name, content):
    with open(name, "w") as f:
        f.write(content)
    return f"File '{name}' created with content"

def delete_file(name):
    os.remove(name)
    return f"File '{name}' deleted"

# COPY & MOVE
def copy_item(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return f"Copied '{src}' to '{dst}'"

def move_item(src, dst):
    shutil.move(src, dst)
    return f"Moved '{src}' to '{dst}'"

# ZIP & EXTRACT
def zip_item(name):
    with zipfile.ZipFile(f"{name}.zip", 'w') as z:
        if os.path.isdir(name):
            for root, dirs, files in os.walk(name):
                for file in files:
                    z.write(os.path.join(root, file))
        else:
            z.write(name)
    return f"Zipped '{name}'"

def extract_zip(name):
    with zipfile.ZipFile(name, 'r') as z:
        z.extractall()
    return f"Extracted '{name}'"

# WEBSITE WITH MEMORY
def open_website(site):
    memory = load_memory()

    if site in memory:
        browser = memory[site]
        print(f"Opening {site} in preferred browser: {browser}")
    else:
        browser = input(f"Which browser for {site}? ")
        memory[site] = browser
        save_memory(memory)

    url = f"https://www.google.com/search?q={site}"
    webbrowser.open(url)
    return f"Opened {site}"


def find_file(query, root="."):
    results = []
    query_lower = query.lower().strip()
    if not query_lower:
        return results

    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            name_lower = name.lower()
            if query_lower in name_lower:
                full = os.path.join(dirpath, name)
                try:
                    stat = os.stat(full)
                    mtime = stat.st_mtime
                except OSError:
                    mtime = 0
                similarity = _name_similarity(query_lower, name_lower)
                results.append({"path": full, "name": name, "mtime": mtime, "score": similarity})

    results.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)
    return results[:20]


def _name_similarity(a, b):
    if a == b:
        return 1.0
    if a in b:
        return 0.9
    # simple ratio without external deps
    matches = sum(1 for ch in a if ch in b)
    return matches / max(len(a), len(b))
