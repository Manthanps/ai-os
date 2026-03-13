def understand_prompt(prompt):
    prompt = prompt.lower().strip()

    # Folder
    if "create folder" in prompt:
        return "create_folder", prompt.split("folder")[-1].strip()

    if "delete folder" in prompt:
        return "delete_folder", prompt.split("folder")[-1].strip()

    # File
    if "create file" in prompt:
        return "create_file", prompt.split("file")[-1].strip()

    if "delete file" in prompt or "delete " in prompt:
        return "delete_file", prompt.split("delete")[-1].strip()

    # Copy & Move
    if "copy" in prompt and "to" in prompt:
        parts = prompt.split("copy")[-1].split("to")
        return "copy", (parts[0].strip(), parts[1].strip())

    if "move" in prompt and "to" in prompt:
        parts = prompt.split("move")[-1].split("to")
        return "move", (parts[0].strip(), parts[1].strip())

    # Zip & Extract
    if "zip" in prompt:
        return "zip", prompt.split("zip")[-1].strip()

    if "extract" in prompt:
        return "extract", prompt.split("extract")[-1].strip()

    # Website
    if prompt.startswith("open "):
        return "open_website", prompt.replace("open", "").strip()

    return "chat", prompt
