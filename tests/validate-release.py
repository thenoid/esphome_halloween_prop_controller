"""Run existing regression checks in an isolated copy with disposable secrets.

No real secrets are read or changed. --generate also generates firmware C++.
--compile additionally builds all three controllers (requires toolchain downloads).
Temporary credentials and generated firmware are deleted on exit.
"""
import argparse
import base64
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="prop-controller-validation-") as temp:
        stage = Path(temp)
        for folder in ("packages", "tests"):
            shutil.copytree(root / folder, stage / folder,
                            ignore=shutil.ignore_patterns("__pycache__"))
        configs = [f"halloween-controller-{i}.yaml" for i in (1, 2, 3)]
        extras = ["halloween-controller.yaml", "controller.example.yaml"]
        for name in configs + extras:
            shutil.copyfile(root / name, stage / name)
        key = base64.b64encode(secrets.token_bytes(32)).decode()
        (stage / "secrets.yaml").write_text(
            "wifi_ssid: validation-only\n"
            "wifi_password: validation-only-password\n"
            f"halloween_api_encryption_key: {key}\n"
            "halloween_ap_password: validation-only-hotspot\n"
            "ha_ip: 192.0.2.1\nha_api_port: 6054\n"
        )
        def run(command):
            subprocess.run(command, cwd=stage, check=True)
        run([sys.executable, "tests/validate-contact-config.py", *configs, *extras])
        run([sys.executable, "tests/validate-fog-choreography.py", *configs])
        if args.generate or args.compile:
            for config in configs + extras:
                run([sys.executable, "-m", "esphome", "compile", config, "--only-generate"])
        if args.compile:
            for config in configs:
                run([sys.executable, "-m", "esphome", "compile", config])
    print("Release validation passed; temporary credentials and builds removed.")


if __name__ == "__main__":
    main()
