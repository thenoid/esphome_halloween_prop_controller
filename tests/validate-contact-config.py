"""Validate contact simulation, per-sensor trip limits, and UDP event wiring.

Run with ESPHome 2026.10.0 and a secrets.yaml beside the controller configs.
Optional arguments select config paths; otherwise all three Halloween boards run.
"""
import sys
from pathlib import Path

from esphome.config import read_config
from esphome.core import CORE


def load(path):
    CORE.reset()
    CORE.config_path = Path(path).resolve()
    config = read_config({})
    assert config is not None, f"Invalid configuration: {path}"
    return config

def by_id(config, section):
    return {str(entry["id"]): entry for entry in config[section] if "id" in entry}

def position(actions, action, target):
    for index, step in enumerate(actions):
        if action not in step:
            continue
        value = step[action]
        if str(value.get("id") if isinstance(value, dict) else value) == target:
            return index
    raise AssertionError(f"Missing {action}: {target}")

def check_common(config):
    # Public configurations retain encrypted API/OTA but reject HTTP uploads.
    assert config["api"]["encryption"]["key"]
    assert config["web_server"]["ota"] is False
    # captive_portal auto-loads the HTTP recovery platform; ota:false gates
    # that handler to the active fallback portal rather than the normal UI.
    assert any(entry["platform"] == "esphome" and "encryption" in entry
               for entry in config["ota"])
    scripts = by_id(config, "script")
    sensors = by_id(config, "binary_sensor")
    buttons = by_id(config, "button")
    for channel in range(1, 5):
        contact = sensors[f"contact_{channel}"]
        raw = sensors[f"contact_{channel}_raw"]
        pulse_id = f"simulate_contact_{channel}_pulse"
        assert raw["internal"] and raw["platform"] == "gpio"
        assert raw["pin"]["number"] == (26, 27, 32, 33)[channel - 1]
        assert raw["pin"]["inverted"] and raw["pin"]["mode"]["pullup"]
        assert "on_press" not in raw and "on_release" not in raw
        assert contact["platform"] == "template"
        assert f"id(contact_{channel}_raw).has_state()" in str(contact["lambda"])
        assert f"id(contact_{channel}_raw).state || id({pulse_id}).is_running()" in str(contact["lambda"])
        assert contact["filters"][0]["delayed_on_off"].total_milliseconds == 50
        limiter = str(contact["filters"][1]["lambda"])
        assert "static controller_events::SensorTriggerLimiter limiter;" in limiter
        assert f"!x || !id(contact_{channel}).has_state() || limiter.accept(millis())" in limiter
        pulse = scripts[pulse_id]
        assert pulse["mode"] == "restart"
        assert [step["delay"].total_milliseconds for step in pulse["then"]] == [50, 100]
        simulate = buttons[f"simulate_contact_{channel}"]
        label = config["substitutions"][f"contact_{channel}_label"]
        assert simulate["name"] == f"Test Contact {channel} - {label}"
        assert str(simulate["on_press"][0]["then"][0]["script.execute"]["id"]) == pulse_id
        assert simulate["web_server"]["sorting_group_id"] == contact["web_server"]["sorting_group_id"]
        assert contact["web_server"]["sorting_weight"] < simulate["web_server"]["sorting_weight"] < channel + 1
        assert contact["trigger_on_initial_state"] is False
        for trigger, event in (("on_press", "sensor.triggered"), ("on_release", "sensor.released")):
            broadcast = contact[trigger][0]["then"][0]["script.execute"]
            assert str(broadcast["id"]) == "controller_broadcast_event"
            assert broadcast["event"] == event
            assert int(broadcast["item"]) == channel
    stop = buttons["stop_all"]["on_press"][0]["then"]
    cancel = position(stop, "script.execute", "controller_stop_sequences")
    report = position(stop, "script.execute", "controller_sequences_stopped")
    assert position(stop, "script.stop", "startup_relay_check") < cancel
    for channel in range(1, 5):
        assert position(stop, "script.stop", f"simulate_contact_{channel}_pulse") < cancel
        assert cancel < position(stop, "switch.turn_off", f"relay_{channel}") < report
        assert cancel < position(stop, "script.stop", f"relay_{channel}_sequence_timer") < report
    assert scripts["controller_stop_sequences"]["mode"] == "single"
    assert scripts["controller_handle_event"]["mode"] == "parallel"
    udp = config["udp"][0]
    assert udp["port"] == 18512
    assert [str(a) for a in udp["addresses"]] == ["255.255.255.255"]
    return scripts, sensors, buttons

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    configs = sys.argv[1:] or [root / f"halloween-controller-{board}.yaml" for board in (1, 2, 3)]
    for config_path in configs:
        check_common(load(config_path))
        print(f"{Path(config_path).name}: contact simulation, trip limits, broadcasts, and Stop All passed.")
