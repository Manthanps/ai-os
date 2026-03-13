import aios_unified as unified
import memory_manager


def run_mode(mode):
    mode = mode.upper().strip()
    if mode == "STUDY":
        unified.open_website("study notes")
        unified.open_folder(_notes_folder())
        return {"mode": "STUDY", "status": "started"}
    if mode == "CODING":
        last_project = memory_manager.get_last_project()
        if last_project:
            unified.open_folder(last_project)
        unified.open_app("Visual Studio Code")
        unified.open_website("github")
        return {"mode": "CODING", "status": "started", "project": last_project}
    if mode == "RELAX":
        unified.open_website("youtube")
        unified.open_website("music")
        return {"mode": "RELAX", "status": "started"}
    raise ValueError("Unknown mode. Use STUDY, CODING, or RELAX.")


def _notes_folder():
    return memory_manager.recall_context().get("last_project") or "."
