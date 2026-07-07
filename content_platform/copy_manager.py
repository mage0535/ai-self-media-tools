"""
Copy Manager — content matrix management.

Handles:
- Loading copy files from a matrix directory
- Content rotation and scheduling
- Multi-format adaptation (blog/microblog/forum)
- Locale-specific content selection
"""
import json
import os
import random
from pathlib import Path
from datetime import datetime, date


class CopyMatrix:
    """Manage a content matrix directory with copy files."""

    def __init__(self, matrix_dir):
        self.matrix_dir = Path(matrix_dir)
        self.copy_dir = self.matrix_dir / "copy"
        self.log_path = self.matrix_dir / "publish_log.jsonl"
        self.manifest_path = self.matrix_dir / "manifest.json"
        self.content_rules = self.matrix_dir / "content_rules.json"

    def list_copy_files(self):
        if not self.copy_dir.is_dir():
            return []
        files = []
        for f in sorted(self.copy_dir.glob("*.md")):
            files.append({
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return files

    def load_copy(self, name):
        path = self.copy_dir / name
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def load_all_copies(self):
        if not self.copy_dir.is_dir():
            return {}
        copies = {}
        for f in sorted(self.copy_dir.glob("*.md")):
            copies[f.name] = f.read_text(encoding="utf-8")
        return copies

    def pick_copy(self, day_seed=None):
        files = self.list_copy_files()
        if not files:
            return None, None
        seed = day_seed or (date.today().year * 1000 + date.today().timetuple().tm_yday)
        rng = random.Random(seed)
        chosen = rng.choice(files)
        content = self.load_copy(chosen["name"])
        return chosen["name"], content

    def load_manifest(self):
        if not self.manifest_path.is_file():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def load_content_rules(self):
        if not self.content_rules.is_file():
            return {}
        return json.loads(self.content_rules.read_text(encoding="utf-8"))

    def last_publish_log(self, limit=10):
        if not self.log_path.is_file():
            return []
        entries = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries[-limit:]

    def append_publish_log(self, entry):
        self.matrix_dir.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_publish(self, platform, ok, url="", error=""):
        self.append_publish_log({
            "ts": datetime.now().isoformat(),
            "platform": platform,
            "ok": ok,
            "url": url,
            "error": error[:200] if error else "",
        })

    def recently_published(self, days=3):
        recent = set()
        cutoff = datetime.now().timestamp() - days * 86400
        for entry in self.last_publish_log(200):
            ts_str = entry.get("ts", "")
            try:
                if datetime.fromisoformat(ts_str).timestamp() >= cutoff:
                    recent.add(entry.get("platform", ""))
            except (ValueError, TypeError):
                pass
        return recent


def format_matrix_content(content, platform_type="blog"):
    if platform_type == "auto":
        platform_type = "microblog" if len(content) < 500 else "blog"

    if platform_type == "microblog":
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
        text = " ".join(lines)
        if len(text) > 500:
            text = text[:497] + "..."
        return {"text": text, "title": "", "kind": "microblog"}

    if platform_type == "forum":
        lines = content.split("\n")
        teaser = ""
        for l in lines:
            l = l.strip()
            if l and not l.startswith("#") and not l.startswith(">"):
                teaser = l[:300]
                break
        title = ""
        for l in lines:
            if l.startswith("# "):
                title = l.lstrip("# ").strip()[:80]
                break
        return {"text": teaser, "title": title, "kind": "forum"}

    title = ""
    for l in content.split("\n"):
        if l.startswith("# "):
            title = l.lstrip("# ").strip()[:80]
            break
    return {"text": content, "title": title or "Article", "kind": "blog"}
