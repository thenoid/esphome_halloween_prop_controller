# ESPHome Halloween prop controller

An MIT-licensed controller for the **original ESP32 LILYGO T-Relay with four relays**. It runs local dry-contact prop sequences, offers Home Assistant and browser controls, and coordinates multiple boards using a small UDP event protocol. Local sequences work without Home Assistant or Wi-Fi.

This release comes from the existing controller project, including its original hardware framework and latest three-board choreography. Device identities and installation labels are generic; credentials belong in your own ignored `secrets.yaml`. See [source and attribution](NOTICE.md) and [release verification](docs/release-verification.md).

## Hardware and wiring

You need one original four-relay ESP32 T-Relay per controller, a suitable **12–24 V DC power supply connected to the board's DC input screw terminals**, voltage-free contact sensors, and a **LILYGO T-U2T or compatible USB-to-serial adapter with 3.3 V logic** for the first flash. Use a 2.4 GHz Wi-Fi network. This configuration uses ESP-IDF and 4 MB flash; it targets neither the T-Relay-S3 nor the eight-relay board.

The output assignments match [LILYGO's ESPHome pin mapping](https://github.com/Xinyuan-LilyGO/LilyGo-T-Relay/blob/main/ESPHome/T-Relay-4-ESP32.yaml). The [original board's labeled pinout](https://github.com/Xinyuan-LilyGO/LilyGo-T-Relay/blob/main/image/T-Relay-en.jpg) identifies the expansion GPIOs, GPIO25 LED and 12–24 V DC input. Power this build through those **DC input terminals**, observing the board's marked polarity. Flash through the T-U2T programming connection (or an appropriately wired compatible serial adapter); a cable to the board's USB-C socket alone cannot program it. Check the actual board revision against the pinout before wiring.

| Function | GPIO | Connection / behavior |
| --- | --- | --- |
| K1 relay | 21 | Active HIGH; fog on controller 3 |
| K2 relay | 19 | Active HIGH; BIG Spider on controller 1 |
| K3 relay | 18 | Active HIGH; fog on controller 1 |
| K4 relay | 5 | Active HIGH; fog on controller 2; onboard strapping-pin connection |
| Contact 1 | 26 | Voltage-free contact between GPIO26 and board GND |
| Contact 2 | 27 | Voltage-free contact between GPIO27 and board GND |
| Contact 3 | 32 | Voltage-free contact between GPIO32 and board GND |
| Contact 4 | 33 | Voltage-free contact between GPIO33 and board GND |

Use GPIO labels, not header position numbers. Inputs use internal pull-ups and inverted logic: closed = ON. GPIO25 drives the onboard LED and is not an input. Unused inputs may remain open. Long outdoor leads need suitable input protection and pull-ups for the installation. **These are bare 3.3 V GPIO inputs**: never connect a powered 5/12/24 V sensor output directly. Relay optocouplers do not isolate these inputs.

The fog machine's original **normally open manual button remains connected**. In this build, the relay's **COM and NO leads are soldered onto the same two contacts on the back of that button**, placing the relay in parallel with it. Use K3 on controller 1, K4 on controller 2, and K1 on controller 3; leave NC unused for these fog triggers. With the relay OFF, COM–NO is open. During a fog sequence, the relay energizes and closes COM–NO for `Fog Duration` (default 10 seconds), simulating a held button press; it then releases and opens COM–NO again. The original button can still close the circuit independently of the controller's timers, cooldowns and Stop All. The relay contacts provide a switch closure, not a 12–24 V power output. They are separate from the controller's GPIO contact inputs.

Confirm the prop's trigger voltage, current and required button-hold duration before connecting it. Firmware ON/OFF describes the relay coil, not whether a prop is safe. Do not assume a fog-machine remote is low voltage; have its interface verified before connecting it.

`Fog Duration` controls the relay-contact closure. The firmware does not monitor fog-machine readiness or confirm actual fog output.

## Features and default routines

| Entry point | Example device name | Local behavior | Remote behavior |
| --- | --- | --- | --- |
| `halloween-controller-1.yaml` | `prop-controller-1` | Contact 1: K3 fog, 10 s ON + 10 s cooldown. Contact 2: K2 BIG Spider, 1 s ON + 25 s cooldown. | Accepted fog start triggers controller 3 after 15 s; accepted spider start triggers controller 2 after 3.5 s. |
| `halloween-controller-2.yaml` | `prop-controller-2` | K4 fog, 10 s ON + 10 s cooldown; local contacts unassigned. | Waits 3.5 s after controller 1 Sequence 2 starts. |
| `halloween-controller-3.yaml` | `prop-controller-3` | K1 fog, 10 s ON + 10 s cooldown; local contacts unassigned. | Waits 15 s after controller 1 Sequence 1 starts. |
| `controller.example.yaml` | `prop-controller-4` | Hardware-only starter: manual relays, contacts and event bus, no prop routines. Startup relay check disabled. | Receives/logs events without running a prop. |

Controller 2 now uses K4 (GPIO5); its existing Fog Duration setting is retained when updating from the K1 configuration.

`halloween-controller.yaml` is a compatibility alias for controller 1. Flash one entry point per board; use the canonical numbered files for new installations.

The table lists initial software defaults, not measurements of an installed machine. Previously saved duration/cooldown settings take precedence after reboot; check the actual UI values before testing. The receiver delays are fixed in YAML: each receiver waits 3.5 or 15 seconds after receiving the matching event, so source-to-output timing also includes network and scheduling latency.

- Four contacts have 50 ms debounce and independent limits of one accepted trip per second. Suppressed trips are discarded; a held contact never repeats and a contact closed at boot does not start a routine.
- **Test Contact** buttons simulate the same sensor path, including local mappings and network events. UI descriptions show which sequence each assigned contact triggers.
- Timed sequence buttons, Busy and Cooling Down indicators, and persistent duration/cooldown settings are available in Home Assistant and the web UI. Durations support 0.1–600 s; cooldowns support 0–600 s. Source fog and spider routines can run concurrently.
- Triggers received while a sequence is busy are discarded, never queued. Receiving boards are busy throughout remote delay, output and cooldown. Their manual **Trigger Fog** starts immediately when idle.
- Four direct manual relay switches are available on each board. They bypass duration and cooldown settings and remain ON until switched OFF, stopped or rebooted. A running sequence's pending OFF timer or startup check can still turn its relay OFF. Generic ON Duration settings for unused channels do not make their manual switches timed.
- **Stop All** cancels that board's startup check, simulations, pending delays, sequences and cooldowns, then switches all outputs OFF. It clears sequence cooldowns, so a new request can start a sequence immediately; contact debounce/trip limits still apply. It does not latch the board into a disabled state, stop other boards, cancel delays they have already accepted, or open a separately held physical fog button. It is a software control, not an emergency stop.
- Encrypted native API and encrypted OTA updates share your API key. Fallback Wi-Fi/captive portal, Wi-Fi signal, IP address and uptime diagnostics are included. Wi-Fi/API loss does not reboot the board automatically.

### Startup behavior and safety

**The preserved default on all three numbered controllers is an enabled relay check on every normal boot/restart, including after OTA.** It energizes K1, K2, K3, K4 in order, one second apart, then de-energizes them in order. Each relay stays energized for about four seconds. Connected props can operate during this check. Normal sequence requests during it are discarded; manual switches can override it.

Disconnect prop loads for first power-up and all bench checks. To disable the check, set `startup_relay_check_enabled: "false"` in each controller's substitutions and rebuild. Every relay uses `ALWAYS_OFF` after GPIO initialization; verify actual power-up behavior electrically, especially GPIO5. Cooldowns reset on reboot. Network loss does not stop a manually energized relay.

Use suitable fuses, enclosures, strain relief, grounding and outdoor protection, and respect the actual DC/AC and motor-inrush ratings of every component. High-current fans/motors require a suitably rated external switching stage; a printed resistive-load rating does not establish motor suitability. Keep moving props clear of people and provide a physical means to disconnect power. Follow the prop manufacturer's fog/fluid, heat, ventilation and duty-cycle instructions.

## Configure and flash

1. Use **ESPHome 2026.10.0** (the pinned validation version). Copy the controller YAML files and the complete `packages/` directory into your ESPHome Device Builder directory, keeping relative paths intact. Or clone this repository for CLI use.
2. Copy `secrets.example.yaml` to `secrets.yaml` beside the controller files. Fill in your 2.4 GHz SSID/password, API encryption key, unique fallback hotspot password and Home Assistant outgoing-connection IP/port. Generate a new API key with `openssl rand -base64 32`. The example's API key placeholder intentionally fails validation. Real secrets, build files and firmware are ignored by Git.
3. Keep the three generic device names for the supplied choreography. If you rename controller 1, also change `source == "prop-controller-1"` in both receivers and update descriptions. Every board on the event network must have a unique name. Change `friendly_name` and `contact_N_label` for your own UI as needed.
4. With props disconnected, validate and compile your chosen file, then install over the programming adapter. Connect TX/RX/GND and boot controls according to the manufacturer's programming header instructions; never apply 5 V serial logic. In Device Builder use **Validate**, then **Install**. CLI equivalents are below; select the correct serial port when prompted.
5. Add the device once under Home Assistant **Settings → Devices & services → ESPHome**, using the board's address and API key if discovery fails. Open `http://prop-controller-1.local/` (or its assigned address) for controller 1's browser UI; substitute the other example name for other boards.
6. Verify the bench checklist before connecting loads. Rebuild/reflash after YAML changes. Controller 1 reads an output's duration when its sequence is requested; controllers 2/3 read Fog Duration when their delayed output starts. Every board reads cooldown when its output timer finishes. Editing a setting does not change an already-running output timer or cooldown.

For the CLI steps below, install **Python 3.13** (the tested version); an older system `python3` may not satisfy the pinned ESPHome package's requirements. Device Builder users do not need a separate local Python installation.

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp secrets.example.yaml secrets.yaml
# Edit secrets.yaml privately before these commands:
esphome config halloween-controller-1.yaml
esphome compile halloween-controller-1.yaml
esphome run halloween-controller-1.yaml
```

The [outgoing API connection](https://esphome.io/components/api/#outgoing-connections) needs Home Assistant 2026.10.0 or later and initial device enrollment. `ha_ip` is your server's IP; the example uses the documentation-only address `192.0.2.1`, which must be replaced. `ha_api_port: 6054` is the Home Assistant listener; the controller's inbound API uses 6053. If you use only the traditional inbound API, remove `api.outgoing_connection` from the shared framework; its host/port secrets then become unused. Local prop operation does not require Home Assistant.

The fallback hotspot is named `Halloween Controller Setup`; its password comes from your secrets. Firmware binaries and resolved configurations contain credentials: do not upload them to issues or releases. Before updating an existing installation, preserve its key or plan serial recovery and Home Assistant re-enrollment. Follow the official [encrypted OTA migration instructions](https://esphome.io/components/ota/esphome/#encryption) for older devices that do not yet offer encrypted OTA.

### Web UI access

The original password-free local web UI behavior is preserved. Anyone able to reach it can operate props. Use a trusted, restricted network; do not expose the UI, API, OTA or UDP port to the Internet. API/OTA encryption does not protect HTTP controls or UDP messages. The public configuration disables firmware uploads in the normal web UI (`web_server.ota: false`); use encrypted native OTA or the serial adapter for updates. **ESPHome still permits plaintext HTTP recovery uploads while the fallback captive portal is active.** Protect the hotspot with a unique password. To remove that recovery path entirely, remove `captive_portal:` as well; doing so also removes browser-based Wi-Fi setup.

For optional web authentication, add this to a controller file and fill in the two optional web secrets:

```yaml
web_server:
  auth:
    type: digest
    username: !secret halloween_web_username
    password: !secret halloween_web_password
```

## Controller networking and customization

Boards broadcast to `255.255.255.255` on UDP **18512** on the same subnet/VLAN. Allow local broadcasts and disable client isolation where required. There is no peer IP list, broker or Home Assistant automation. Event types include contact triggered/released and sequence started/cooling_down/ready. The port is configurable via `controller_event_port` on every board.

Events have **no authentication, acknowledgements, retries or replay protection**. A host on that network can spoof a trigger; packets can be lost or duplicated. Keep this event bus on a trusted network and never use it for safety interlocks. Stopping the source board does not stop receivers. See [event protocol and extension hooks](docs/network-events.md).

The framework owns shared hardware, networking and Stop All. `relay-channel.yaml` provides each contact/relay pair, simulation, trip limiting and OFF timers. Numbered controller files own their prop routines and mappings; `controller.example.yaml` starts without any. Add new sequences in the controller file, publish lifecycle events and extend `controller_stop_sequences` to cancel every routine and cooldown before output shutdown. `remote-event-trigger.yaml` is an optional rule helper.

## Test before use

With all prop loads disconnected:

1. Check each board's startup pattern ends with all relays OFF, or that no relay energizes if you disabled the check. Compare physical contacts with UI ON/OFF states.
2. Controller 1 Contact 1 / **Trigger Fog**: only K3 runs at t=0–10 s. Controller 3 K1 runs at about t=15–25 s; controller 2 stays idle.
3. Controller 1 Contact 2 / **Trigger BIG Spider**: K2 runs at t=0–1 s. Controller 2 K4 runs at about t=3.5–13.5 s; controller 3 stays idle.
4. Repeat with **Test Contact** buttons. Confirm held contacts do not repeat, inputs closed at boot do not trigger, and independent trip limits/cooldowns discard retriggers. Receiver contacts remain unassigned.
5. Press each receiver's local **Stop All** during its pending delay, active output and cooldown. The canceled delay must not fire later. Check immediate manual sequence starts when idle, and cancellation of the startup check and simulations.
6. Change settings, reboot and verify persistence. Try a 2 s source fog duration: controller 3 still starts 15 s after its accepted start. Check disconnected Wi-Fi leaves local timing working with no replay after reconnection. Inspect `controller_events` TX/RX logs privately if a receiver does not respond.

Automated checks use an isolated copy and disposable credentials; they never read your real secrets:

```sh
python tests/validate-release.py --generate
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -I . tests/controller-events-test.cpp -o /tmp/controller-events-test
/tmp/controller-events-test
# Optional full builds; downloads ESP-IDF/toolchains and deletes test firmware:
python tests/validate-release.py --compile
```

CI runs native regression checks plus ESPHome validation and C++ generation for all five entry points. It neither flashes boards nor uploads firmware containing credentials. See [release verification](docs/release-verification.md) for the checks actually completed for this release and the [README audit](docs/readme-audit.md) for the hardware/code evidence and physical verification limits.

## License

Project source and documentation use the existing [MIT license](LICENSE). ESPHome and build-time dependencies retain their own licenses; see [NOTICE.md](NOTICE.md). This is a community project, unaffiliated with LILYGO, ESPHome or any prop manufacturer.
