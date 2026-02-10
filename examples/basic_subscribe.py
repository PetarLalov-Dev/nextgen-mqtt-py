#!/usr/bin/env python3
"""Basic example: Subscribe to a device via WebSocket and print all messages.

This uses the WebSocket connection to device-shard-api, which is the
recommended method for external access. Messages are in protobuf format.
"""

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from nextgen_mqtt import NextGenMQTTClient

# Enable logging to see connection progress
logging.basicConfig(level=logging.INFO)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to a device via WebSocket and print all messages."
    )
    parser.add_argument(
        "device_serial",
        nargs="?",
        default="2530296",
        help="Device serial to subscribe to (default: 2530296).",
    )
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _proto_dir() -> Path:
    return _repo_root() / "helix-protobuf" / "protos"


def _proto_cache_dir() -> Path:
    return _repo_root() / ".cache" / "helix_protobuf_py"


def _buf_export_dir() -> Path:
    return _proto_cache_dir() / "buf_export"


def _latest_mtime(paths: list[Path]) -> float:
    return max(path.stat().st_mtime for path in paths)


def _ensure_buf_deps(proto_dir: Path) -> list[Path]:
    validate_proto = proto_dir / "buf" / "validate" / "validate.proto"
    if validate_proto.exists():
        return []

    if shutil.which("buf") is None:
        raise RuntimeError(
            "Missing buf/validate/validate.proto. Install buf or vendor protovalidate protos. "
            "See helix-protobuf/buf.yaml for the dependency."
        )

    export_dir = _buf_export_dir()
    exported_validate = export_dir / "buf" / "validate" / "validate.proto"
    if exported_validate.exists():
        return [export_dir]

    export_dir.mkdir(parents=True, exist_ok=True)
    repo_root = _repo_root() / "helix-protobuf"

    try:
        subprocess.run(
            ["buf", "export", "--output", str(export_dir)],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "buf export failed. Ensure buf is installed and the helix-protobuf module is valid."
        ) from exc

    return [export_dir]


def _compile_protos(proto_dir: Path, out_dir: Path) -> None:
    from grpc_tools import protoc
    from importlib.resources import files as resource_files

    proto_files = sorted(proto_dir.rglob("*.proto"), key=lambda p: (p.name != "main.proto", str(p)))
    if not proto_files:
        raise RuntimeError(f"No .proto files found under {proto_dir}")

    grpc_include = str(resource_files("grpc_tools") / "_proto")

    out_dir.mkdir(parents=True, exist_ok=True)
    extra_includes = _ensure_buf_deps(proto_dir)

    args = [
        "protoc",
        f"-I{proto_dir}",
        f"-I{grpc_include}",
        *[f"-I{path}" for path in extra_includes],
        f"--python_out={out_dir}",
        *[str(p) for p in proto_files],
    ]
    result = protoc.main(args)
    if result != 0:
        raise RuntimeError(f"protoc failed with exit code {result}")


@lru_cache(maxsize=1)
def _load_helix_message_class():
    proto_dir = _proto_dir()
    if not proto_dir.exists():
        raise RuntimeError(f"Proto directory not found: {proto_dir}")

    cache_dir = _proto_cache_dir()
    proto_files = list(proto_dir.rglob("*.proto"))
    if not proto_files:
        raise RuntimeError(f"No .proto files found under {proto_dir}")

    target = cache_dir / "main_pb2.py"
    if not target.exists() or target.stat().st_mtime < _latest_mtime(proto_files):
        _compile_protos(proto_dir, cache_dir)

    sys.path.insert(0, str(cache_dir))
    try:
        import importlib

        main_pb2 = importlib.import_module("main_pb2")
        return main_pb2.Helix
    finally:
        sys.path.pop(0)


def _format_decoded_message(decoded) -> str:
    from google.protobuf import json_format

    msg_name = decoded.WhichOneof("msg")
    meta = {}
    if decoded.msg_id:
        meta["msg_id"] = decoded.msg_id
    if decoded.user_number:
        meta["user_number"] = decoded.user_number
    if decoded.age:
        meta["age"] = decoded.age
    if decoded.error_code:
        meta["error_code"] = decoded.error_code

    payload = getattr(decoded, msg_name)
    payload_type = payload.DESCRIPTOR.full_name
    payload_type_display = payload_type.ljust(40)
    payload_dict = json_format.MessageToDict(payload, preserving_proto_field_name=True)
    payload_json = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True)
    meta_json = json.dumps(meta, separators=(",", ":"), sort_keys=True)
    return f"{payload_type_display}\t{payload_json}\r\n"


async def main(device_serial: str):

    print(f"Subscribing to device {device_serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            print(f"Connected! Connection type: {conn.connection.connection_type}")
            print(f"Device: {conn.device_serial}")
            # print("Waiting for messages (Ctrl+C to exit)...\n")

            print("Waiting for messages (Ctrl+C to exit)...\n")
            
            # Send protobuf message to the device
            hex_payload = '08c2021a083031303230333034ba400408011005'
            payload = bytes.fromhex(hex_payload)  # Convert hex string to bytes
            print(f"Sending message to device: {hex_payload}")
            await conn.send(payload)
            print(f"Message sent! ({len(payload)} bytes)\n")
            
            try:
                helix_cls = _load_helix_message_class()
            except Exception as exc:
                print(f"Failed to load protobuf schema: {exc}")
                print("Install dependencies with: pip install -e .")
                return

            async for message in conn.messages():
                print(
                    f"[{message.received_at.isoformat()}] Received {len(message.payload)} bytes \t {message.payload[:50].hex()}"
                )
                # Messages are in protobuf format - raw bytes
                try:
                    decoded = helix_cls()
                    decoded.ParseFromString(message.payload)
                    print(_format_decoded_message(decoded))
                except Exception as exc:
                    print(f"Failed to decode protobuf message: {exc}")
                


if __name__ == "__main__":
    try:
        args = parse_args()
        asyncio.run(main(args.device_serial))
    except KeyboardInterrupt:
        print("\nExiting...")
