# Local controller event bus

Each board listens and broadcasts on UDP port 18512 at `255.255.255.255`. Boards must share a subnet with broadcasts allowed. Override `controller_event_port` consistently if needed. `device_name` identifies a source; it must be unique and use lowercase letters, digits and hyphens. Changing a source name requires updating receiver filters too.

Packets are versioned text records, limited to 128 bytes:

```text
HC1|prop-controller-1|sensor.triggered|2|
HC1|prop-controller-1|sequence.started|2|
HC1|prop-controller-2|sequence.ready|1|cooldown_finished
```

| Event | Item | Reason | Meaning |
| --- | --- | --- | --- |
| `sensor.triggered` | Contact 1–4 | empty | Accepted debounced closure before the local routine request |
| `sensor.released` | Contact 1–4 | empty | Debounced opening |
| `sequence.started` | Source sequence 1–4 | empty | First output has started |
| `sequence.cooling_down` | Source sequence 1–4 | empty | Output timers finished; cooldown starts |
| `sequence.ready` | Source sequence 1–4 | `cooldown_finished` | Normal completion |
| `sequence.ready` | Source sequence 1–4 | `stopped` | Active/cooling sequence interrupted by local Stop All |

Sequence numbers are independent of relay numbers. On controller 1, Sequence 1 is K3 Fog and Sequence 2 is K2 BIG Spider. On receivers, Sequence 1 is K4 Fog on controller 2 and K1 Fog on controller 3. Stop All while idle emits no sequence event. Stopping a pending remote delay occurs before that receiver has announced a started event, so it emits no corresponding ready/stopped event. Manual switches and startup checks do not emit lifecycle events.

Contacts share real/simulated input paths, 50 ms debounce and per-input one-second trip limits. A held or boot-closed contact does not repeatedly trigger. Sequence events and incoming packets have no one-second trip limiter. Busy sequences discard new triggers; they never queue them.

Messages are sent once while Wi-Fi is connected, without acknowledgement, retry, replay, forwarding, heartbeat or state synchronization. A late-joining board waits for new events. Unknown versions/types, malformed data and self echoes are ignored. **Packets are unauthenticated and can be spoofed or duplicated on the network.** Limit network access; this protocol is unsuitable for safety interlocks.

## Extend a controller

For a custom local routine, define its scripts and trigger button, then include the following under the controller's existing `packages:` mapping. This example assumes a local `trigger_1` button already exists; it is not a complete controller configuration.

```yaml
packages:
  controller: !include packages/controller-framework.yaml
  contact_2_rule: !include
    file: packages/remote-event-trigger.yaml
    vars:
      remote_source: prop-controller-1
      remote_event: sensor.triggered
      remote_item: "2"
      remote_reason: ""
      local_trigger: trigger_1
```

Alternatively extend `controller_handle_event` in the controller file. It receives `source`, `event`, `item` and `reason`. Keep handlers short and execute the existing local routine/button so its startup guard and cooldown apply. The numbered receiver configurations demonstrate delayed starts based on `sequence.started`; they intentionally ignore raw sensor events.

For custom sequences, call `controller_broadcast_event` at accepted start, cooldown start and normal completion. Use the source-local sequence number consistently. Extend `controller_stop_sequences` with synchronous `script.stop` actions for the routine and its cooldown; the shared Stop All then cancels relay OFF timers, switches outputs OFF, and announces stopped active sequences. Never add delays to that cancellation hook. Sequence settings may be changed in the UI; keep explanatory UI descriptions in sync with your mappings.
