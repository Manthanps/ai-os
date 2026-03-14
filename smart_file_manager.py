#!/usr/bin/env python3
"""
smart_file_manager.py
A terminal-based file system automation tool for macOS, Linux, and Windows.
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def ok(msg: str) -> None:
    print(f"[✓] {msg}")


def warn(msg: str) -> None:
    print(f"[!] {msg}")


def _backup_dir_from(args_backup: str | None) -> Path | None:
    if args_backup:
        return Path(args_backup).expanduser()
    env = os.environ.get("SFM_BACKUP_DIR")
    if env:
        return Path(env).expanduser()
    return None


def _ensure_backup_dir(backup_dir: Path | None) -> Path | None:
    if backup_dir is None:
        return None
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    except PermissionError:
        warn("Permission denied creating backup directory.")
        return None


def _require_login_password() -> bool:
    if os.name == "posix":
        if shutil.which("sudo"):
            subprocess.run(["sudo", "-k"], check=False)
            res = subprocess.run(["sudo", "-v"])
            if res.returncode == 0:
                return True
            warn("Authentication failed.")
            return False
        warn("sudo not available; cannot verify login password.")
        return False
    if os.name == "nt":
        warn("Login password verification is not supported on Windows by this tool.")
        return True
    return True


def _trash_dir() -> Path:
    if os.name == "posix":
        if sys.platform == "darwin":
            return Path.home() / ".Trash"
        return Path.home() / ".local" / "share" / "Trash" / "files"
    return Path.home() / "SmartTrash"


def _safe_name(name: str) -> str:
    return name.replace("|", "%7C")


def _log_trash(orig: Path, trashed: Path, backup: Path | None) -> None:
    log_path = Path.home() / ".smart_file_manager_trash.log"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    b = str(backup) if backup else ""
    line = f"{stamp}|{_safe_name(str(orig))}|{_safe_name(str(trashed))}|{_safe_name(b)}\n"
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _backup_copy(src: Path, backup_dir: Path) -> Path | None:
    ts = time.strftime("%Y%m%d_%H%M%S")
    if src.is_dir():
        zip_name = f"{src.name}_{ts}.zip"
        zip_path = backup_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in src.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(src))
        return zip_path
    else:
        dst = backup_dir / f"{src.stem}_{ts}{src.suffix}"
        shutil.copy2(src, dst)
        return dst


def _move_to_trash(path: Path) -> Path:
    trash = _trash_dir()
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / path.name
    if target.exists():
        ts = time.strftime("%Y%m%d_%H%M%S")
        target = trash / f"{path.stem}_{ts}{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def _restore_from_log(target: str) -> None:
    log_path = Path.home() / ".smart_file_manager_trash.log"
    if not log_path.exists():
        warn("No trash log found.")
        return
    key = target.strip().lower()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        parts = line.split("|")
        if len(parts) < 4:
            continue
        orig = parts[1].replace("%7C", "|")
        trashed = parts[2].replace("%7C", "|")
        backup = parts[3].replace("%7C", "|")
        if key in {orig.lower(), Path(orig).name.lower()} or Path(orig).name.lower() == key:
            orig_path = Path(orig)
            trashed_path = Path(trashed)
            backup_path = Path(backup) if backup else None
            if trashed_path.exists():
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(trashed_path), str(orig_path))
                ok(f"Restored from trash: {orig_path}")
                return
            if backup_path and backup_path.exists():
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                if backup_path.suffix == ".zip":
                    orig_path.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(backup_path, "r") as zf:
                        zf.extractall(orig_path)
                else:
                    shutil.copy2(backup_path, orig_path)
                ok(f"Restored from backup: {orig_path}")
                return
            warn("No restore source found for that entry.")
            return
    warn("No matching entry found in trash log.")


class FileManager:
    def create_file(self, filename: str) -> None:
        path = Path(filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            ok(f"File created: {path}")
        except PermissionError:
            warn("Permission denied.")

    def create_folder(self, foldername: str) -> None:
        path = Path(foldername)
        try:
            path.mkdir(parents=True, exist_ok=True)
            ok(f"Folder created: {path}")
        except PermissionError:
            warn("Permission denied.")

    def list_files(self, directory: str) -> None:
        path = Path(directory)
        if not path.exists():
            warn("Directory not found.")
            return
        for entry in sorted(path.iterdir()):
            print(entry.name)

    def read_file(self, filename: str) -> None:
        path = Path(filename)
        try:
            print(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def append_to_file(self, filename: str, text: str) -> None:
        path = Path(filename)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
            ok(f"Appended to: {path}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def copy_file(self, source: str, destination: str) -> None:
        src = Path(source)
        dst = Path(destination)
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.copy2(src, dst)
            ok(f"File copied to: {dst}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def copy_folder(self, source: str, destination: str) -> None:
        src = Path(source)
        dst = Path(destination)
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            ok(f"Folder copied to: {dst}")
        except FileNotFoundError:
            warn("Folder not found.")
        except PermissionError:
            warn("Permission denied.")

    def move_file(self, source: str, destination: str) -> None:
        src = Path(source)
        dst = Path(destination)
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.move(str(src), str(dst))
            ok(f"File moved to: {dst}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def move_folder(self, source: str, destination: str) -> None:
        self.move_file(source, destination)

    def rename_file(self, old_name: str, new_name: str) -> None:
        src = Path(old_name)
        dst = Path(new_name)
        try:
            src.rename(dst)
            ok(f"File renamed to: {dst}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def rename_folder(self, old_name: str, new_name: str) -> None:
        self.rename_file(old_name, new_name)

    def delete_file(self, filename: str, backup_dir: Path | None) -> None:
        path = Path(filename)
        try:
            if not path.exists():
                warn("File not found.")
                return
            if not _require_login_password():
                return
            backup = _backup_copy(path, backup_dir) if backup_dir else None
            trashed = _move_to_trash(path)
            _log_trash(path, trashed, backup)
            ok(f"File moved to trash: {trashed}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def delete_folder(self, foldername: str, backup_dir: Path | None) -> None:
        path = Path(foldername)
        try:
            if not path.exists():
                warn("Folder not found.")
                return
            if not _require_login_password():
                return
            backup = _backup_copy(path, backup_dir) if backup_dir else None
            trashed = _move_to_trash(path)
            _log_trash(path, trashed, backup)
            ok(f"Folder moved to trash: {trashed}")
        except FileNotFoundError:
            warn("Folder not found.")
        except PermissionError:
            warn("Permission denied.")

    def search_file(self, directory: str, filename: str) -> None:
        root = Path(directory)
        if not root.exists():
            warn("Directory not found.")
            return
        matches = [p for p in root.rglob("*") if p.is_file() and p.name == filename]
        if not matches:
            warn("No matches found.")
            return
        for m in matches:
            print(m)

    def search_by_extension(self, directory: str, extension: str) -> None:
        root = Path(directory)
        ext = extension if extension.startswith(".") else f".{extension}"
        if not root.exists():
            warn("Directory not found.")
            return
        matches = [p for p in root.rglob(f"*{ext}") if p.is_file()]
        if not matches:
            warn("No matches found.")
            return
        for m in matches:
            print(m)

    def file_properties(self, filename: str) -> None:
        path = Path(filename)
        try:
            stats = path.stat()
            info = {
                "path": str(path.resolve()),
                "size_bytes": stats.st_size,
                "modified": time.ctime(stats.st_mtime),
                "created": time.ctime(stats.st_ctime),
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
            }
            for k, v in info.items():
                print(f"{k}: {v}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def make_readonly(self, filename: str) -> None:
        path = Path(filename)
        try:
            os.chmod(path, stat.S_IREAD)
            ok(f"Made read-only: {path}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def make_writable(self, filename: str) -> None:
        path = Path(filename)
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            ok(f"Made writable: {path}")
        except FileNotFoundError:
            warn("File not found.")
        except PermissionError:
            warn("Permission denied.")

    def zip_folder(self, foldername: str) -> None:
        path = Path(foldername)
        if not path.exists():
            warn("Folder not found.")
            return
        zip_path = path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in path.rglob("*"):
                zf.write(file, file.relative_to(path))
        ok(f"Zipped to: {zip_path}")

    def unzip_file(self, zipfile_path: str) -> None:
        path = Path(zipfile_path)
        if not path.exists():
            warn("Zip file not found.")
            return
        target = path.with_suffix("")
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(target)
        ok(f"Unzipped to: {target}")


class ShareManager:
    def generate_local_share_link(self, path: str) -> None:
        p = Path(path).resolve()
        if not p.exists():
            warn("Path not found.")
            return
        # Best-effort local share link (file://) plus local IP hint
        link = f"file://{p}"
        ip_hint = self._local_ip_hint()
        print(f"Local link: {link}")
        if ip_hint:
            print(f"Local IP: {ip_hint}")

    def _local_ip_hint(self) -> str:
        system = os.name
        try:
            if system == "posix":
                # macOS
                if shutil.which("ipconfig"):
                    out = subprocess.check_output(["ipconfig", "getifaddr", "en0"], text=True).strip()
                    return out
                # Linux fallback
                out = subprocess.check_output(["hostname", "-I"], text=True).strip().split()
                return out[0] if out else ""
            # Windows
            out = subprocess.check_output(["ipconfig"], text=True)
            for line in out.splitlines():
                if "IPv4 Address" in line:
                    return line.split(":")[-1].strip()
        except Exception:
            return ""
        return ""

    def start_file_server(self, directory: str, port: int) -> None:
        path = Path(directory)
        if not path.exists():
            warn("Directory not found.")
            return
        ok(f"Starting HTTP server on port {port} (Ctrl+C to stop)")
        subprocess.run(["python3", "-m", "http.server", str(port)], cwd=str(path))

    def upload_to_cloud(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            warn("Path not found.")
            return
        warn("Cloud upload is a placeholder. Implement your provider here.")


class Organizer:
    def auto_organize(self, directory: str) -> None:
        root = Path(directory).expanduser().resolve()
        if not root.exists():
            warn("Directory not found.")
            return
        categories = {
            "Images": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"],
            "Videos": [".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm"],
            "Documents": [".pdf", ".doc", ".docx", ".txt", ".ppt", ".pptx", ".xls", ".xlsx"],
            "Code": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".rs", ".go", ".html", ".css", ".json", ".yml", ".yaml"],
            "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        }
        for file in root.iterdir():
            if not file.is_file():
                continue
            moved = False
            for folder, exts in categories.items():
                if file.suffix.lower() in exts:
                    target_dir = root / folder
                    target_dir.mkdir(exist_ok=True)
                    shutil.move(str(file), str(target_dir / file.name))
                    moved = True
                    break
            if not moved:
                continue
        ok("Auto-organize complete.")


def watch_folder(directory: str) -> None:
    path = Path(directory)
    if not path.exists():
        warn("Directory not found.")
        return
    ok(f"Watching: {path} (Ctrl+C to stop)")
    previous = {p: p.stat().st_mtime for p in path.rglob("*")}
    try:
        while True:
            time.sleep(1)
            current = {p: p.stat().st_mtime for p in path.rglob("*")}
            added = current.keys() - previous.keys()
            removed = previous.keys() - current.keys()
            modified = [p for p in current if p in previous and current[p] != previous[p]]
            for p in added:
                print(f"[+] Created: {p}")
            for p in removed:
                print(f"[-] Deleted: {p}")
            for p in modified:
                print(f"[~] Modified: {p}")
            previous = current
    except KeyboardInterrupt:
        ok("Stopped watching.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smart File Manager")
    parser.add_argument("--backup-dir", help="Network backup folder for deleted items")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("create-file").add_argument("path")
    sub.add_parser("create-folder").add_argument("path")
    sub.add_parser("list").add_argument("path")
    sub.add_parser("read").add_argument("path")
    p = sub.add_parser("append")
    p.add_argument("path")
    p.add_argument("text")

    p = sub.add_parser("copy")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("move")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("rename")
    p.add_argument("old")
    p.add_argument("new")

    sub.add_parser("delete").add_argument("path")
    sub.add_parser("restore").add_argument("target")
    p = sub.add_parser("search")
    p.add_argument("dir")
    p.add_argument("name")
    p = sub.add_parser("search-ext")
    p.add_argument("dir")
    p.add_argument("ext")

    sub.add_parser("props").add_argument("path")
    sub.add_parser("readonly").add_argument("path")
    sub.add_parser("writable").add_argument("path")
    sub.add_parser("zip").add_argument("path")
    sub.add_parser("unzip").add_argument("path")

    p = sub.add_parser("share")
    p.add_argument("path")
    p = sub.add_parser("serve")
    p.add_argument("dir")
    p.add_argument("--port", type=int, default=8000)
    p = sub.add_parser("upload")
    p.add_argument("path")

    p = sub.add_parser("organize")
    p.add_argument("dir")
    p = sub.add_parser("watch")
    p.add_argument("dir")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    fm = FileManager()
    sm = ShareManager()
    org = Organizer()

    cmd = args.command
    if cmd == "create-file":
        fm.create_file(args.path)
    elif cmd == "create-folder":
        fm.create_folder(args.path)
    elif cmd == "list":
        fm.list_files(args.path)
    elif cmd == "read":
        fm.read_file(args.path)
    elif cmd == "append":
        fm.append_to_file(args.path, args.text)
    elif cmd == "copy":
        if Path(args.src).is_dir():
            fm.copy_folder(args.src, args.dst)
        else:
            fm.copy_file(args.src, args.dst)
    elif cmd == "move":
        if Path(args.src).is_dir():
            fm.move_folder(args.src, args.dst)
        else:
            fm.move_file(args.src, args.dst)
    elif cmd == "rename":
        if Path(args.old).is_dir():
            fm.rename_folder(args.old, args.new)
        else:
            fm.rename_file(args.old, args.new)
    elif cmd == "delete":
        backup_dir = _ensure_backup_dir(_backup_dir_from(args.backup_dir))
        if Path(args.path).is_dir():
            fm.delete_folder(args.path, backup_dir)
        else:
            fm.delete_file(args.path, backup_dir)
    elif cmd == "search":
        fm.search_file(args.dir, args.name)
    elif cmd == "search-ext":
        fm.search_by_extension(args.dir, args.ext)
    elif cmd == "props":
        fm.file_properties(args.path)
    elif cmd == "readonly":
        fm.make_readonly(args.path)
    elif cmd == "writable":
        fm.make_writable(args.path)
    elif cmd == "zip":
        fm.zip_folder(args.path)
    elif cmd == "unzip":
        fm.unzip_file(args.path)
    elif cmd == "share":
        sm.generate_local_share_link(args.path)
    elif cmd == "serve":
        sm.start_file_server(args.dir, args.port)
    elif cmd == "upload":
        sm.upload_to_cloud(args.path)
    elif cmd == "organize":
        org.auto_organize(args.dir)
    elif cmd == "watch":
        watch_folder(args.dir)
    elif cmd == "restore":
        _restore_from_log(args.target)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
