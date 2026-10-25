# Public release verification — 2026-10-25

## Source and privacy boundary

The release is an allowlisted snapshot of the existing controller source, not a clone of the private ESPHome repository. It retains the original four-relay ESP32 LILYGO framework, current three-controller sequences, shared event protocol and existing regression tests. Generic example identities replace deployed device names; Fog / BIG Spider replace physical installation labels. The public repository's initial MIT-license commit is preserved. Private source history and unrelated home-device configurations were not imported.

Only source, example configuration, tests and documentation are published. No real secrets file, firmware, resolved configuration dump, log, screenshot or network capture is included. The secrets template covers all six required references, plus two optional web-authentication entries. Its API key placeholder is deliberately invalid. The only literal IPv4 addresses are `192.0.2.1` (documentation target) and `255.255.255.255` (protocol broadcast).

## Completed checks

- **ESPHome 2026.10.0, Python 3.13:** schema validation and C++ generation passed for all three numbered controllers, the controller 1 compatibility alias and the hardware-only starter.
- **Full ESP-IDF firmware compilation:** all three numbered controllers built successfully with disposable test credentials. Generated firmware and temporary credentials were deleted after validation; none is published.
- **Native C++ regression tests:** passed with `-Wall -Wextra -Werror` and AddressSanitizer/UndefinedBehaviorSanitizer. Coverage includes event round trips, malformed packet rejection, sensor timing boundaries, independent inputs and clock rollover.
- **Resolved-configuration regressions:** passed for contact pins, inversion/pull-ups, simulation/debounce/trip limits, local mappings, event filters, 3.5/15-second delays, immediate manual sequence starts, output/cooldown timing, Busy state and Stop All cancellation. Release assertions also verify API/native OTA encryption and `web_server.ota: false`.
- **Gitleaks 8.30.1:** no findings in release files, the staged release diff or complete public commit history. Scanner binary was obtained from the official release and checked against its published SHA-256 checksum.
- **Additional privacy review:** checked literals, URLs, MAC-address patterns, local filesystem paths, previous device names and physical-location labels. URLs are official documentation/source links or generic example addresses. Git author addresses use GitHub no-reply addresses; the existing license attribution is retained.
- **Repository hygiene:** checked whitespace, documentation links, required secret-template coverage and ignore rules for real/nested secrets, firmware and build artifacts. The example secrets file remains includable.

Reproduce configuration/code-generation checks with `python tests/validate-release.py --generate`; add `--compile` for full firmware builds. See the README for native test commands. The runner creates an isolated snapshot and never reads deployment secrets. CI runs native tests, validation and generation without repository secrets or firmware uploads.

## Limits and preserved behavior

No physical device was flashed or bench-tested as part of this release. GPIO5 retains ESPHome's warning because the original board uses that strapping pin for K4. Validate actual board and prop interfaces before use.

All three numbered configurations retain the enabled boot relay cycle. Manual relay switches bypass sequence timing, Stop All acts locally, and UDP triggers are unauthenticated and unreliable by design. The web UI retains password-free access unless you configure optional authentication. Normal web firmware uploads are disabled; the active fallback captive portal still permits HTTP recovery uploads. The README documents these behaviors and commissioning steps.

Secret scanning and static review cannot prove an absence of every possible sensitive value. Do not publish deployment credentials, compiled firmware, logs or later site-specific edits without reviewing them again.
