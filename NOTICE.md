# Source and attribution

The controller YAML, shared event protocol, sensor limiter and regression tests were adapted from the maintainer's existing Halloween controller project. The release uses the latest three-controller implementation at source revision `3b14f66`, with its original four-relay ESP32 hardware framework. It is a sanitized snapshot: private repository history, unrelated home devices, credentials, deployment files and stale intermediate configurations were not imported.

Release adaptations replace installation-specific device identities with `prop-controller-1`, `prop-controller-2` and `prop-controller-3`, replace physical-location labels with routine labels, add the secrets template and isolated validation runner, and document the current ESPHome 2026.10.0 requirements. Relay pins, active levels, sequences, boot checks, timing defaults, event format and password-free web behavior are preserved. Controller 2's 3.5-second delay and controller 3's 15-second delay come from the latest source.

The release explicitly disables firmware uploads in the normal web UI (`web_server.ota: false`); encrypted native OTA and all browser prop controls remain available. ESPHome's active fallback captive portal still permits HTTP recovery uploads, as documented in the README. The minimum ESPHome version is raised to the validated 2026.10.0 version for outgoing API connections.

The repository's pre-existing MIT LICENSE and copyright notice are retained. That license covers this project's source and documentation, not third-party tools or hardware designs.

- **LILYGO / Xinyuan-LilyGO**: relay pin assignments are cross-referenced against the [manufacturer's ESPHome example](https://github.com/Xinyuan-LilyGO/LilyGo-T-Relay/blob/main/ESPHome/T-Relay-4-ESP32.yaml). Hardware, pinout and programming information is linked to the [T-Relay documentation](https://wiki.lilygo.cc/products/t-relay-series/t-relay/). No upstream firmware, drawings or schematic assets are redistributed here.
- **ESPHome contributors**: the project uses [ESPHome](https://github.com/esphome/esphome) and built-in components for GPIO, scripts, UDP, web controls, API and OTA. ESPHome's own [license](https://github.com/esphome/esphome/blob/dev/LICENSE) and those of dependencies remain applicable when building/distributing firmware; the framework and toolchain are not vendored in this repository.
- **Espressif / ESP-IDF and build dependencies**: downloaded by ESPHome during compilation and governed by their respective license notices. Retain applicable notices when redistributing compiled firmware. Published binaries must be built without deployment credentials.

Generic example device names, the limited broadcast address and the documentation-only API target in this repository are intentional examples, not a disclosed installation.
