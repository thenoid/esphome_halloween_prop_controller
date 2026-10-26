"""Validate Halloween fog choreography in ESPHome's resolved configuration.

Run with test secrets beside configs; defaults to all three Halloween boards.
"""
import runpy
import sys
from pathlib import Path

common = runpy.run_path(str(Path(__file__).with_name("validate-contact-config.py")))
load, by_id, position, check_common = [common[name] for name in ("load", "by_id", "position", "check_common")]

def check_sequence(scripts, channel, relays, delayed_relay=None, start_delay_ms=0):
    sequence = scripts[f"sequence_{channel}"]
    assert sequence["mode"] == "single"
    branch = sequence["then"][0]["if"]
    assert str(branch["condition"]["not"]["script.is_running"]["id"]) == "startup_relay_check"
    assert "controller_broadcast_event" not in str(branch["else"])
    steps = branch["then"]
    events = [(i, s["script.execute"]) for i, s in enumerate(steps)
              if "script.execute" in s and str(s["script.execute"]["id"]) == "controller_broadcast_event"]
    assert [e["event"] for _, e in events] == ["sequence.started", "sequence.cooling_down", "sequence.ready"]
    assert all(int(e["item"]) == channel for _, e in events)
    assert events[-1][1]["reason"] == "cooldown_finished"
    started, cooling, ready = [i for i, _ in events]
    cooldown = f"sequence_{channel}_cooldown"
    for relay in relays:
        timer = f"relay_{relay}_sequence_timer"
        turn_on = position(steps, "switch.turn_on", f"relay_{relay}")
        start_timer = position(steps, "script.execute", timer)
        wait_timer = position(steps, "script.wait", timer)
        assert turn_on < start_timer < wait_timer < position(steps, "script.execute", cooldown)
        if relay == delayed_relay:
            delays = [(i, step["delay"]) for i, step in enumerate(steps) if "delay" in step]
            assert len(delays) == 1
            delay_index, delay = delays[0]
            assert delay.total_milliseconds == start_delay_ms
            assert started < delay_index < turn_on
        else:
            assert start_timer < started < wait_timer
    assert position(steps, "script.execute", cooldown) < cooling
    assert cooling < position(steps, "script.wait", cooldown) < ready
    # The routine must cancel its parent and cooldown before Stop All reaches
    # timer cancellation, output shutdown, and the stopped-event publication.
    cancel = scripts["controller_stop_sequences"]["then"]
    position(cancel, "script.stop", f"sequence_{channel}")
    position(cancel, "script.stop", cooldown)


def fog_timeline(scripts, fog_ms, cooldown_ms, start_delay_ms=0):
    """Project the actual resolved action graph onto independent timer clocks."""
    def target(value):
        return str(value["id"] if isinstance(value, dict) else value)

    parameters = {"fog_duration_ms": fog_ms, "start_delay_ms": start_delay_ms}
    now, finishes, trace = 0, {}, []
    for step in scripts["sequence_1"]["then"][0]["if"]["then"]:
        if "switch.turn_on" in step:
            trace.append((now, target(step["switch.turn_on"]), "on"))
        elif "delay" in step:
            assert str(step["delay"]).strip() == "return start_delay_ms;"
            now += start_delay_ms
        elif "script.wait" in step:
            now = max(now, finishes[target(step["script.wait"])])
        elif "script.execute" in step:
            action = step["script.execute"]
            name = target(action)
            if name == "controller_broadcast_event":
                trace.append((now, action["event"], action["reason"]))
            elif name == "sequence_1_cooldown":
                finishes[name] = now + cooldown_ms
            else:
                timer = scripts[name]["then"]
                # Read the timer's real OFF action; the delay must use the
                # duration snapshotted at the original sequence request.
                assert str(timer[0]["delay"]).strip() == "return duration_ms;"
                expression = str(action["duration_ms"]).strip()
                if expression == "return (int) (id(pulse_1_seconds).state * 1000.0f);":
                    duration = fog_ms
                else:
                    duration = next(value for key, value in parameters.items()
                                    if expression == f"return {key};")
                finishes[name] = now + duration
                trace.append((finishes[name], target(timer[1]["switch.turn_off"]), "off"))
        else:
            raise AssertionError(f"Unhandled sequence action: {step}")
    return trace, now


root = Path(__file__).resolve().parent.parent
paths = sys.argv[1:] or [root / f"halloween-controller-{board}.yaml" for board in (1, 2, 3)]
for path in paths:
    config = load(path)
    scripts, sensors, buttons = check_common(config)
    device = config["esphome"]["name"]
    if device == "prop-controller-1":
        check_sequence(scripts, 1, (3,))
        check_sequence(scripts, 2, (2,))
        steps = scripts["sequence_1"]["then"][0]["if"]["then"]
        assert "relay_4" not in str(steps) and not any("delay" in step for step in steps)
        assert set(scripts["sequence_1"]["parameters"]) == {"fog_duration_ms"}
        assert buttons["trigger_1"]["name"] == "Trigger Fog"
        assert buttons["trigger_2"]["name"] == "Trigger BIG Spider"
        assert by_id(config, "switch")["relay_4"]["name"] == "Relay 4 Manual"
        for channel in (1, 2):
            actions = sensors[f"contact_{channel}"]["on_press"][0]["then"]
            position(actions, "script.execute", f"sequence_{channel}")
            manual = buttons[f"trigger_{channel}"]["on_press"][0]["then"][0]["script.execute"]
            assert str(manual["id"]) == f"sequence_{channel}"
        delay_ms, relay = 0, "relay_3"
    else:
        source_item, delay_ms = {"prop-controller-2": (2, 3500), "prop-controller-3": (1, 15000)}[device]
        check_sequence(scripts, 1, (1,))
        rules = scripts["controller_handle_event"]["then"]
        assert len(rules) == 2
        rule = rules[-1]["if"]
        condition = str(rule["condition"]["lambda"])
        assert 'source == "prop-controller-1"' in condition
        assert f'event == "sequence.started" && item == {source_item}' in condition
        assert "reason.empty()" in condition
        route = rule["then"][0]["script.execute"]
        assert str(route["id"]) == "sequence_1" and route["start_delay_ms"] == delay_ms
        manual = buttons["trigger_1"]["on_press"][0]["then"][0]["script.execute"]
        assert str(manual["id"]) == "sequence_1" and manual["start_delay_ms"] == 0
        steps = scripts["sequence_1"]["then"][0]["if"]["then"]
        assert str(steps[0]["delay"]).strip() == "return start_delay_ms;"
        assert len([step for step in steps if "delay" in step]) == 1
        assert "id(sequence_1).is_running()" in str(sensors["sequence_1_busy"]["lambda"])
        for channel in (1, 2, 3, 4):
            assert len(sensors[f"contact_{channel}"]["on_press"][0]["then"]) == 1
        relay = "relay_1"
    for start_ms in sorted({0, delay_ms}):
        for fog_ms, cooldown_ms in ((100, 0), (2000, 10000), (10000, 10000), (600000, 600000)):
            trace, ready_ms = fog_timeline(scripts, fog_ms, cooldown_ms, start_ms)
            assert (start_ms, relay, "on") in trace
            assert (start_ms + fog_ms, relay, "off") in trace
            assert (start_ms, "sequence.started", "") in trace
            assert (start_ms + fog_ms, "sequence.cooling_down", "") in trace
            assert (start_ms + fog_ms + cooldown_ms, "sequence.ready", "cooldown_finished") in trace
            assert ready_ms == start_ms + fog_ms + cooldown_ms
    print(f"{Path(path).name}: fog choreography, timing, cooldown, and local Stop All passed.")
