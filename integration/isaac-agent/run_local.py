"""Run the native, local-only Isaac controller from this dedicated workspace."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def main() -> None:
    os.chdir(ROOT)
    config = json.loads((ROOT / "config" / "decision_provider.json").read_text(encoding="utf-8"))
    if config.get("selected_provider") != "local" or config.get("shadow_enabled") is not False:
        raise SystemExit("Local startup requires selected_provider=local and shadow_enabled=false.")
    if "--autopilot" in sys.argv:
        protection_path = ROOT / "save-protection.json"
        protection = json.loads(protection_path.read_text(encoding="utf-8")) if protection_path.exists() else {}
        if protection.get("allowed_slot") != 3 or protection.get("autopilot_allowed") is not True:
            raise SystemExit("Autopilot is locked until the fresh rightmost save slot has been confirmed.")
        install = json.loads((ROOT / "game-install.json").read_text(encoding="utf-8"))
        if protection.get("game_root") != install["game_root"]:
            raise SystemExit("The verified save slot belongs to a different game installation.")
        save_root = Path(install["save_root"])
        options = (save_root / "options.ini").read_text(encoding="utf-8")
        if "SteamCloud=0" not in options.splitlines():
            raise SystemExit("Local test storage is required before automatic control.")
        if "PauseOnFocusLost=0" not in options.splitlines():
            raise SystemExit("Background control requires PauseOnFocusLost=0 in the selected save settings.")
        if not (save_root / "persistentgamedata3.dat").is_file():
            raise SystemExit("The isolated third save slot has not been created.")
        manifest = json.loads(Path(protection["baseline_manifest"]).read_text(encoding="utf-8"))
        for record in manifest["files"]:
            source = Path(record["source"])
            if source.suffix.lower() == ".dat" and (
                not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]
            ):
                raise SystemExit("An existing save differs from the protected baseline; automatic control is blocked.")
        import psutil

        game = psutil.Process(protection["verified_game_pid"])
        if (Path(game.exe()) != Path(install["game_root"]) / install["executable"]
                or game.create_time() != protection["verified_game_created_at"]):
            raise SystemExit("The game process changed; confirm the isolated third slot before automatic control.")
    sys.path.insert(0, str(ROOT / "src"))
    from isaac_jev.cli import main as controller_main

    controller_main()


if __name__ == "__main__":
    main()
