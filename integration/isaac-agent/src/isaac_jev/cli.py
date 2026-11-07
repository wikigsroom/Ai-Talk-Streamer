from __future__ import annotations

import argparse
from collections import Counter
import signal
import threading
import time
import webbrowser

from .runtime import BridgeRuntime
from .tuning import analyze_episodes, applied_death_counts, load_profile, pending_events, suggest_profile, write_profile
from .web_dashboard import LocalDashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Repentance Jev controller bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9528)
    parser.add_argument("--autopilot", action="store_true", help="Allow Lua to override player input.")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable the live terminal decision dashboard.")
    parser.add_argument("--web-dashboard", action="store_true", help="Serve a live dashboard on localhost instead of relying on terminal redraw.")
    parser.add_argument("--dashboard-port", type=int, default=9529, help="Local web dashboard port (default: 9529).")
    parser.add_argument("--open-dashboard", action="store_true", help="Open the local dashboard in the default browser.")
    parser.add_argument("--log-dir", default="logs", help="Local directory for death trajectories and policy profile.")
    parser.add_argument("--auto-tune", action="store_true", help="Tune the local policy from recorded deaths before starting.")
    parser.add_argument("--macro-horizon-frames", type=int, default=8, help="Remote Jev action validity window in game frames (6-12).")
    args = parser.parse_args()
    if args.auto_tune:
        events = analyze_episodes(f"{args.log_dir}/episodes.jsonl")
        pending = pending_events(events, applied_death_counts(args.log_dir))
        before = load_profile(args.log_dir)
        after = suggest_profile(pending, before)
        if after != before:
            write_profile(args.log_dir, after, {"episodes": len(events), "pending_episodes": len(pending), "death_counts": dict(Counter(str(event.get("cause", "unknown")) for event in events)), "source": "isaac-jev --auto-tune"})
        print(f"Offline tuning: {len(events)} death episodes ({len(pending)} new); profile={'updated' if after != before else 'unchanged'}")
    runtime = BridgeRuntime(args.host, args.port, args.autopilot, log_dir=args.log_dir, macro_horizon_frames=args.macro_horizon_frames)
    runtime.start()
    dashboard = LocalDashboard(runtime.controller, port=args.dashboard_port) if args.web_dashboard else None
    if dashboard:
        dashboard.start()
    host, port = runtime.address
    print(f"Isaac Jev bridge listening on {host}:{port}; autopilot={'on' if args.autopilot else 'off'}")
    print("Press Ctrl+C to stop. F8 in game always returns control to the player.")
    if dashboard:
        print(f"Live dashboard: {dashboard.url}")
        if args.open_dashboard:
            webbrowser.open(dashboard.url)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        if not args.no_dashboard:
            while not stop.wait(0.25):
                status = runtime.controller.status()
                lines = [
                    "\x1b[2J\x1b[HISAAC × JEV — LIVE DECISION DASHBOARD",
                    f"Autopilot: {'ON' if status['autopilot_enabled'] else 'OFF'}  |  frame: {status['latest_frame']}  |  pending: {status['decision_pending']}",
                    f"Decision: {status['latest_mode'] or '-'} / {status['latest_action'] or '-'}  |  target: {status['latest_target'] or '-'}",
                    f"Input: move {status['latest_move'] or '-'}  |  shoot {status['latest_shoot'] or '-'}",
                    f"Source: {status['latest_confidence'] if status['latest_confidence'] is not None else '-'} confidence  |  {status['latest_reason'] or 'waiting for game state'}",
                    f"Latency: last {status['last_decision_latency_ms'] or '-'} ms  |  avg {status['average_decision_latency_ms'] or '-'} ms  |  p95 {status['p95_decision_latency_ms'] or '-'} ms",
                    f"Deaths: {status['telemetry']['episodes_recorded']}  |  causes {status['telemetry']['death_counts']}",
                    f"Repeat penalty: {status['stall_penalty_count']}  |  {'active' if status['stall_penalty_active'] else 'idle'}  |  {status['last_stall_penalty_reason'] or '-'}",
                    f"Movement feedback: stalls {status['movement_stall_count']}  |  stale Jev discarded {status['stale_decisions_discarded']}",
                    f"Restart: {status['latest_state']['restart_phase'] if status['latest_state'] else '-'}  |  count {status['latest_state']['restart_count'] if status['latest_state'] else 0}",
                    f"Bridge: connections {status['bridge_connections']}  |  bytes {status['bridge_received_bytes']}  |  states {status['bridge_received_states']}  |  {status['bridge_error'] or 'healthy'}",
                    "Recent decisions:",
                ]
                lines.extend(f"  f{item['frame']}  {item['source']}  {item['mode']}  {item['action']} → {item['target'] or '-'} ({item['confidence']:.2f})" for item in status['recent_decisions'])
                print("\n".join(lines), end="", flush=True)
        else:
            stop.wait()
    finally:
        if dashboard:
            dashboard.stop()
        runtime.stop()


if __name__ == "__main__":
    main()
