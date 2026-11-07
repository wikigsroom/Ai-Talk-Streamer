"""Audit a normal victory against native events, progression and protected saves."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir")
    args = parser.parse_args()
    process = json.loads((ROOT / "controller-process.json").read_text(encoding="utf-8-sig"))
    folder = Path(args.log_dir or process["log_directory"])
    protection = json.loads((ROOT / "save-protection.json").read_text(encoding="utf-8"))
    install = json.loads((ROOT / "game-install.json").read_text(encoding="utf-8"))
    manifest = json.loads(Path(protection["baseline_manifest"]).read_text(encoding="utf-8"))
    originals = [row for row in manifest["files"] if Path(row["source"]).suffix.lower() == ".dat"]
    changed = [row["source"] for row in originals if not Path(row["source"]).exists()
        or hashlib.sha256(Path(row["source"]).read_bytes()).hexdigest() != row["sha256"]]
    events = [json.loads(line) for line in (folder / "experiment_runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    victory_path = folder / "victory.json"
    victory = json.loads(victory_path.read_text(encoding="utf-8")) if victory_path.exists() else None
    progress = [row for row in events if row.get("type") == "game_progress"
        and (not victory or row.get("start_seed") == victory["start_seed"])]
    native_log = Path(install["save_root"]) / "log.txt"
    native_events = []
    for line in native_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[IsaacJev] NATIVE_GAME_END " in line:
            native_events.append(json.loads(line.split("[IsaacJev] NATIVE_GAME_END ", 1)[1]))
    corroborated = bool(victory and any(row.get("is_game_over") is False
        and row.get("start_seed") == victory["start_seed"] and row.get("frame") == victory["frame"]
        and row.get("callback") == "MC_POST_GAME_END" for row in native_events))
    with urllib.request.urlopen("http://127.0.0.1:9529/api/status", timeout=5) as response:
        status = json.load(response)
    source = ROOT / "mods/IsaacJev/main.lua"
    deployed = Path(install["game_root"]) / "mods/IsaacJev/main.lua"
    stages = sorted({row["stage"] for row in progress})
    full_normal_progress = set(range(1, 7)).issubset(stages)
    local_only = status.get("active_provider_name") == "local" and status.get("remote_call_count") == 0
    deployed_matches = source.read_bytes() == deployed.read_bytes()
    result = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "completed": bool(corroborated and not changed and full_normal_progress and local_only
            and protection["allowed_slot"] == 3 and deployed_matches),
        "native_log_corroborates_victory": corroborated,
        "victory": victory,
        "stages_observed": stages, "full_normal_floor_progress_verified": full_normal_progress,
        "local_only_verified": local_only,
        "rooms_observed": len({(row["stage"], row["room_index"]) for row in progress}),
        "protected_save_files_checked": len(originals), "protected_saves_unchanged": not changed,
        "changed_protected_saves": changed, "allowed_slot": protection["allowed_slot"],
        "autopilot_enabled": status["autopilot_enabled"],
        "active_provider": status.get("active_provider_name"),
        "remote_call_count": status.get("remote_call_count"),
        "local_decision_count": status.get("local_decision_count"),
        "mod_version": status.get("mod_version"),
        "deployed_mod_matches_source": deployed_matches,
        "mod_sha256": hashlib.sha256(deployed.read_bytes()).hexdigest(),
        "game_log": str(native_log), "log_directory": str(folder),
    }
    (folder / "full-run-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if corroborated:
        (folder / "native-ending-evidence.txt").write_text(native_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
