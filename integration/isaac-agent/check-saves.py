"""Compare existing save files with the read-only backup baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


root = Path(__file__).resolve().parent
protection = json.loads((root / "save-protection.json").read_text(encoding="utf-8"))
manifest = json.loads(Path(protection["baseline_manifest"]).read_text(encoding="utf-8"))
checked = 0
changed = []
for record in manifest["files"]:
    source = Path(record["source"])
    if source.suffix.lower() != ".dat":
        continue
    checked += 1
    if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
        changed.append(str(source))
print(json.dumps({"save_files_checked": checked, "all_existing_save_files_unchanged": not changed,
                  "changed_files": changed}, ensure_ascii=True, indent=2))
raise SystemExit(1 if changed else 0)
