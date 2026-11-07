# Project working rules

- Use native Windows. Do not run local Docker, WSL or virtual machines. Close browser pages, contexts and browsers created for a task when finished.
- Preserve upstream MIT attribution. Current behavior is documented in README.md, README.en.md and docs/; do not restore removed experimental providers or weights.
- Offline validation: `python -m unittest discover -s tests -q` and `node --test tests/test_dsh_binding.mjs`, with requirements-native.lock.txt installed.
- Do not operate a real game without user authorization. Normal automation is restricted to the explicitly authorized writable slot 3, with verified save backups and original-save hashes. Do not edit health, items, rooms, unlocks or saves to manufacture success.
- Keep the real-time provider local and shadow disabled. Strategic inference belongs to the separate DSH plugin. Agent tools select locally validated offers, never arbitrary code or key commands.
- Startup is observation only. Confirm actual stable normal pause before stopping a live controller. Do not repeatedly force foreground or auto-resume after service recovery.
- Credentials, machine configuration, raw sessions, saves and dependency binaries remain private and excluded from Git. Publish only reviewed media and sanitized evidence; distinguish historical, replay and live results.
- Do not delegate work to additional agents unless the user explicitly authorizes it.
