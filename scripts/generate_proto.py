#!/usr/bin/env python3
"""Generate Python protobuf files from helix-protobuf definitions.

Compiles .proto files from lib/helix-protobuf/protos/ into
src/nextgen_mqtt/generated/*_pb2.py using grpc_tools.protoc.

Usage:
    uv run python scripts/generate_proto.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "lib" / "helix-protobuf" / "protos"
OUTPUT_DIR = ROOT / "src" / "nextgen_mqtt" / "generated"


def main() -> None:
    if not PROTO_DIR.exists():
        print(f"Error: proto directory not found at {PROTO_DIR}")
        print("Run: git submodule update --init --recursive")
        sys.exit(1)

    validate_proto = PROTO_DIR / "buf" / "validate" / "validate.proto"
    if not validate_proto.exists():
        print(f"Error: {validate_proto} not found.")
        print("Run 'buf dep update && buf export' inside lib/helix-protobuf/,")
        print("or ensure the submodule is fully initialized.")
        sys.exit(1)

    # Clean and recreate output directory
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all proto files: top-level + buf/validate/validate.proto
    proto_files = sorted(PROTO_DIR.glob("*.proto"))
    proto_files.append(validate_proto)

    if not proto_files:
        print(f"Error: no .proto files found in {PROTO_DIR}")
        sys.exit(1)

    print(f"Compiling {len(proto_files)} proto files...")
    for pf in proto_files:
        print(f"  {pf.relative_to(PROTO_DIR)}")

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={PROTO_DIR}",
        f"--python_out={OUTPUT_DIR}",
        *[str(pf) for pf in proto_files],
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"protoc failed:\n{result.stderr}")
        sys.exit(1)

    # Create __init__.py for all generated packages
    _write_init(OUTPUT_DIR)
    buf_dir = OUTPUT_DIR / "buf"
    if buf_dir.exists():
        _write_init(buf_dir)
        validate_dir = buf_dir / "validate"
        if validate_dir.exists():
            _write_init(validate_dir)

    # Fix relative imports in top-level generated files
    for gf in sorted(OUTPUT_DIR.glob("*_pb2.py")):
        content = gf.read_text()
        fixed = _fix_imports(content)
        if fixed != content:
            gf.write_text(fixed)

    # Extract @mqtt.range.* annotations from main.proto and write topic_ranges.py
    _generate_topic_ranges(PROTO_DIR / "main.proto", OUTPUT_DIR / "topic_ranges.py")

    total = len(list(OUTPUT_DIR.rglob("*_pb2.py")))
    print(f"\nGenerated {total} pb2 files + topic_ranges.py in {OUTPUT_DIR}")


def _write_init(directory: Path) -> None:
    (directory / "__init__.py").write_text('"""Generated protobuf modules. Do not edit manually."""\n')


def _fix_imports(content: str) -> str:
    """Rewrite imports to be relative within the generated package."""
    lines = content.split("\n")
    result = []
    for line in lines:
        # `import foo_pb2 as bar` -> `from . import foo_pb2 as bar`
        if (
            line.startswith("import ")
            and "_pb2" in line
            and "google.protobuf" not in line
        ):
            result.append(f"from . {line}")
        # `from buf.validate import validate_pb2 as ...` -> `from .buf.validate import ...`
        elif line.startswith("from buf.") and "import" in line:
            result.append(f"from .{line[5:]}")
        else:
            result.append(line)
    return "\n".join(result)


RANGE_PATTERN = re.compile(r"@mqtt\.range\.(\w+):\s*(\d+)-(\d+)")

# Map annotation names to topic codes
RANGE_NAME_TO_CODE = {
    "event": "e",
    "status_info": "s/i",
    "config": "cf",
    "config_desired": "cd",
    "cmd_resp": "r",
    "cmd": "c",
}


def _generate_topic_ranges(main_proto: Path, output_path: Path) -> None:
    """Parse @mqtt.range.* annotations from main.proto and write topic_ranges.py."""
    content = main_proto.read_text()
    ranges = []
    for match in RANGE_PATTERN.finditer(content):
        name, low, high = match.group(1), int(match.group(2)), int(match.group(3))
        code = RANGE_NAME_TO_CODE.get(name)
        if code is None:
            print(f"  Warning: unknown range name '{name}', skipping")
            continue
        ranges.append((low, high, code))

    if not ranges:
        print("  Warning: no @mqtt.range annotations found in main.proto")
        return

    lines = [
        '"""Topic field-number ranges extracted from main.proto. Do not edit manually."""',
        "",
        "TOPIC_RANGES: list[tuple[int, int, str]] = [",
    ]
    for low, high, code in ranges:
        lines.append(f'    ({low}, {high}, "{code}"),')
    lines.append("]")
    lines.append("")

    output_path.write_text("\n".join(lines))
    print(f"  Wrote topic_ranges.py with {len(ranges)} ranges")


if __name__ == "__main__":
    main()
