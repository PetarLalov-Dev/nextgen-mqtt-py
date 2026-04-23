#!/usr/bin/env python3
"""Subscribe to a device via WebSocket and print messages.

Usage:
    python examples/basic_subscribe.py 2529015
    python examples/basic_subscribe.py 2529015 --payload 0801e2400408011001
    python examples/basic_subscribe.py 2529015 --interactive
    python examples/basic_subscribe.py 2529015 --clear-retained
    python examples/basic_subscribe.py 2529015 --clear-retained --max-num 32
    python examples/basic_subscribe.py 2529015 --filter r,s

Interactive mode requires prompt_toolkit (included in dev extras).
"""

import argparse
import asyncio
import html
import logging
import time
from pathlib import Path

import websockets.exceptions
from google.protobuf.json_format import MessageToDict
from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import has_completions
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout

from nextgen_mqtt import NextGenMQTTClient
from nextgen_mqtt.colors import BOLD, GRAY, RST, WHITE, topic_color
from nextgen_mqtt.generated.main_pb2 import Helix

logger = logging.getLogger(__name__)

HISTORY_FILE = Path.home() / ".cache" / "nextgen_mqtt_interactive_history"

# Retained topic aliases from main.proto @mqtt.unsolicited.alias annotations
# where @mqtt.unsolicited.retained: True
RETAINED_TOPIC_TEMPLATES = [
    # status topics (s/)
    "s/sy", "s/p/{num}", "s/z/{num}", "s/io/{num}", "s/pr/{num}",
    "s/ha/{num}", "s/hu/{num}", "s/if", "s/up",
    # info topics (i/)
    "i/sy", "i/p/{num}", "i/z/{num}", "i/io/{num}", "i/pr/{num}",
    "i/ha/{num}", "i/if",
    # config topics (cf/)
    "cf/sy", "cf/p/{num}", "cf/z/{num}", "cf/io/{num}", "cf/pr/{num}",
    "cf/ha/{num}", "cf/u/{num}", "cf/in/{num}", "cf/if", "cf/m", "cf/to", "cf/cp",
]

ARM_LEVELS = {
    "disarm": 2, "off": 2,
    "stay": 3,
    "night": 4,
    "away": 5,
    "level6": 6, "l6": 6,
    "level7": 7, "l7": 7,
    "level8": 8, "l8": 8,
}

PGM_STATES = {"on": 1, "off": 0, "toggle": 2}

# Domain tree: top-level domain → set of valid actions (empty = leaf, no action).
# 'panel' is an alias of 'system'.
DOMAINS: dict[str, set[str]] = {
    "partition": {"status", "arm", "disarm"},
    "zone":      {"status", "config", "bypass", "unbypass"},
    "ha":        {"status", "on", "off", "toggle", "level", "lock", "unlock"},
    "system":    {"status"},
    "panel":     {"status"},  # alias of system
    "alarm":     {"panic", "fire", "medical"},
    "pgm":       set(),       # leaf: pgm <num> <on|off|toggle>
}

# Signatures keyed by (domain, action) or (domain,) for leaf domains.
SIGNATURES: dict[tuple[str, ...], str] = {
    ("partition", "status"):  "partition status [num] | partition status <start> <end>",
    ("partition", "arm"):     "partition arm <num> or {n n} <level> [pin] [user]   level=away|stay|night|disarm",
    ("partition", "disarm"):  "partition disarm <num> or {n n} [pin] [user]",
    ("zone",      "status"):  "zone status [num] | zone status <start> <end>",
    ("zone",      "config"):  "zone config [num] | zone config <start> <end>",
    ("zone",      "bypass"):  "zone bypass <num> or {n n ...} [pin] [user] [part_auth=N]",
    ("zone",      "unbypass"):"zone unbypass <num> or {n n ...} [pin] [user] [part_auth=N]",
    ("ha",        "status"):  "ha status [num] | ha status <start> <end>",
    ("ha",        "on"):      "ha on <num> [part_auth=N]",
    ("ha",        "off"):     "ha off <num> [part_auth=N]",
    ("ha",        "toggle"):  "ha toggle <num> [part_auth=N]",
    ("ha",        "level"):   "ha level <num> <0-100|on|off> [part_auth=N]",
    ("ha",        "lock"):    "ha lock <num> [part_auth=N]",
    ("ha",        "unlock"):  "ha unlock <num> [part_auth=N]",
    ("system",    "status"):  "system status",
    ("panel",     "status"):  "panel status  (alias of system status)",
    ("alarm",     "panic"):   "alarm panic [notify_cs=y|n]",
    ("alarm",     "fire"):    "alarm fire",
    ("alarm",     "medical"): "alarm medical [notify_cs=y|n]",
    ("pgm",):                 "pgm <num> <on|off|toggle> [pin]",
}

# Mini-signature hint when only a domain has been typed (no action yet).
_DOMAIN_HINT: dict[str, str] = {
    d: f"{d} <{' | '.join(sorted(actions))}>" if actions else SIGNATURES[(d,)]
    for d, actions in DOMAINS.items()
}

HELP_TEXT = """Interactive commands (optional leading /):

  <hex>                             send raw hex (spaces OK, e.g. '08 01 82 28')

  partition
      status [num] | <start> <end>  query one, range, or all partitions
      arm <num> or {n n} <level> [pin] [user]   level=away|stay|night|disarm
      disarm <num> or {n n} [pin] [user]

  zone
      status [num] | <start> <end>  query one, range, or all zones
      config [num] | <start> <end>  query zone configuration
      bypass <num> or {n n ...} [pin] [user] [part_auth=N]
      unbypass <num> or {n n ...} [pin] [user] [part_auth=N]

  ha
      status [num] | <start> <end>  query HA device status
      on <num>                      turn on
      off <num>                     turn off
      toggle <num>                  toggle on/off
      level <num> <0-100|on|off>    set dimmer level
      lock <num>                    lock
      unlock <num>                  unlock

  system                            (alias: panel)
      status

  alarm
      panic [notify_cs=y|n]          trigger panic alarm (notify_cs defaults to y)
      fire                           trigger fire alarm
      medical [notify_cs=y|n]        trigger medical alarm (notify_cs defaults to y)

  pgm <num> <on|off|toggle> [pin]

  clear                             clear all retained topics via API
  clear <suffix> [suffix ...]       clear specific topic(s) via MQTT (e.g. clear s/p/1)

  <> = required  [] = optional  {} = array
  /help /quit q Ctrl-D"""

_ARM_LEVEL_NAMES = sorted(ARM_LEVELS.keys())
_PGM_STATE_NAMES = sorted(PGM_STATES.keys())
_META_COMMANDS = ["/clear", "/help", "/quit"]


def expand_retained_topics(max_num: int) -> list[str]:
    """Expand topic templates into suffixes (without serial prefix)."""
    topics = []
    for template in RETAINED_TOPIC_TEMPLATES:
        if "{num}" in template:
            for n in range(1, max_num + 1):
                topics.append(template.format(num=n))
        else:
            topics.append(template)
    return topics


async def clear_retained(client: NextGenMQTTClient, serial: str, password: str, use_secondary: bool, max_num: int):
    """Clear retained MQTT messages via direct MQTT connection."""
    suffixes = expand_retained_topics(max_num)
    print(f"Clearing {len(suffixes)} retained topics via direct MQTT...")

    try:
        async with client.connect_mqtt(serial, password, use_secondary=use_secondary) as conn:
            cleared = 0
            for suffix in suffixes:
                await conn.publish(suffix, b"", qos=1, retain=True)
                cleared += 1
                if cleared % 20 == 0:
                    print(f"  Cleared {cleared}/{len(suffixes)}...")
            print(f"Done. Cleared {cleared} retained topics.\n")
    except Exception as e:
        print(f"Failed to clear retained topics: {e}")
        print("Note: Direct MQTT (port 8883) may not be accessible from your network.")
        print("The MQTT broker may reject credentials from external networks.\n")


def _parse_kv_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split tokens into (positional, {key: value})."""
    positional: list[str] = []
    kwargs: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            kwargs[k] = v
        else:
            positional.append(tok)
    return positional, kwargs


def _range_from_positional(positional: list[str]) -> tuple[int, int]:
    """Parse: no args = all (1,0); one = that one (N,N); two = range."""
    if len(positional) >= 2:
        return int(positional[0]), int(positional[1])
    if len(positional) == 1:
        n = int(positional[0])
        return n, n
    return 1, 0


def _extract_group(tokens: list[str]) -> tuple[list[int], list[str]]:
    """Parse ``{1 2 3}`` or a single number from the front of *tokens*.

    Returns (numbers, remaining_tokens).  Supports:
      - ``{1 2 3}`` → [1, 2, 3]
      - ``{1`` ``2`` ``3}`` → [1, 2, 3]  (braces split across tokens)
      - ``5`` → [5]  (single number, no braces)
    """
    if not tokens:
        return [], tokens
    if not tokens[0].startswith("{"):
        return [int(tokens[0])], tokens[1:]

    nums: list[int] = []
    rest: list[str] = []
    inside = True
    for i, tok in enumerate(tokens):
        if inside:
            cleaned = tok.strip("{}")
            if cleaned:
                nums.append(int(cleaned))
            if "}" in tok:
                rest = tokens[i + 1 :]
                inside = False
        else:
            rest.append(tok)
    if inside:
        raise ValueError("unclosed '{' — expected '}'")
    return nums, rest


def _extract_str_group(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Like _extract_group but returns raw strings instead of ints."""
    if not tokens:
        return [], tokens
    if not tokens[0].startswith("{"):
        return [tokens[0]], tokens[1:]

    items: list[str] = []
    rest: list[str] = []
    inside = True
    for i, tok in enumerate(tokens):
        if inside:
            cleaned = tok.strip("{}")
            if cleaned:
                items.append(cleaned)
            if "}" in tok:
                rest = tokens[i + 1 :]
                inside = False
        else:
            rest.append(tok)
    if inside:
        raise ValueError("unclosed '{' — expected '}'")
    return items, rest


def build_command_payload(domain: str, action: str | None, args: list[str], msg_id: int) -> tuple[bytes, str]:
    """Build a Helix payload from a <domain> <action> command. Returns (bytes, description)."""
    h = Helix()
    h.msg_id = msg_id
    positional, kwargs = _parse_kv_args(args)

    if "pin" in kwargs:
        h.pin = kwargs["pin"]
    if "user" in kwargs:
        h.user_number = int(kwargs["user"])

    # --- partition ---
    if domain == "partition":
        if action == "status":
            start, end = _range_from_positional(positional)
            h.partition_status_get.num_start = start
            h.partition_status_get.num_end = end
            return h.SerializeToString(), f"partition_status_get {start}-{end or 'all'}"
        if action in ("arm", "disarm"):
            partitions, rest = _extract_group(positional)
            if not partitions:
                partitions = [1]
            if action == "disarm":
                levels = ["disarm"] * len(partitions)
            else:
                level_names, rest = _extract_str_group(rest) if rest else (["away"], rest)
                if len(level_names) == 1:
                    levels = [level_names[0].lower()] * len(partitions)
                elif len(level_names) == len(partitions):
                    levels = [ln.lower() for ln in level_names]
                else:
                    raise ValueError(f"partition arm: {len(partitions)} partitions but {len(level_names)} levels")
            if "pin" not in kwargs and rest:
                h.pin = rest[0]
                rest = rest[1:]
            if "user" not in kwargs and rest:
                h.user_number = int(rest[0])
            level_vals = [ARM_LEVELS.get(lv) or int(lv) for lv in levels]
            if len(partitions) == 1:
                h.arm.partition_num = partitions[0]
                h.arm.level = level_vals[0]
                desc = f"{action} p={partitions[0]} level={levels[0]}"
            else:
                for p, lv in zip(partitions, level_vals):
                    entry = h.arm_many.partition_num_list.add()
                    entry.partition_num = p
                    entry.level = lv
                level_desc = levels[0] if len(set(levels)) == 1 else ",".join(levels)
                desc = f"{action} p={','.join(str(p) for p in partitions)} level={level_desc}"
            return h.SerializeToString(), desc

    # --- zone ---
    if domain == "zone":
        if action == "status":
            start, end = _range_from_positional(positional)
            h.zone_status_get.num_start = start
            h.zone_status_get.num_end = end
            return h.SerializeToString(), f"zone_status_get {start}-{end or 'all'}"
        if action == "config":
            start, end = _range_from_positional(positional)
            h.zone_config_get.num_start = start
            h.zone_config_get.num_end = end
            return h.SerializeToString(), f"zone_config_get {start}-{end or 'all'}"
        if action in ("bypass", "unbypass"):
            if not positional:
                raise ValueError(f"zone {action}: zone number(s) required")
            zones, rest = _extract_group(positional)
            if not zones:
                raise ValueError(f"zone {action}: zone number(s) required")
            if rest and rest[0].lower() in ("y", "n"):
                rest = rest[1:]
            if "pin" not in kwargs and rest:
                h.pin = rest[0]
                rest = rest[1:]
            if "user" not in kwargs and rest:
                h.user_number = int(rest[0])
            is_bypass = action == "bypass"
            part_auth = int(kwargs["part_auth"]) if "part_auth" in kwargs else None
            if len(zones) == 1:
                h.zone_bypass.num = zones[0]
                h.zone_bypass.bypass = is_bypass
                if part_auth is not None:
                    h.zone_bypass.partition_auth = part_auth
                desc = f"zone {action} num={zones[0]}"
            else:
                for z in zones:
                    entry = h.zone_bypass_many.bypass_list.add()
                    entry.num = z
                    entry.bypass = is_bypass
                    if part_auth is not None:
                        entry.partition_auth = part_auth
                desc = f"zone {action} num={','.join(str(z) for z in zones)}"
            return h.SerializeToString(), desc

    # --- ha (home automation) ---
    if domain == "ha":
        part_auth = int(kwargs["part_auth"]) if "part_auth" in kwargs else None
        if action == "status":
            start, end = _range_from_positional(positional)
            h.ha_device_status_get.num_start = start
            h.ha_device_status_get.num_end = end
            return h.SerializeToString(), f"ha_device_status_get {start}-{end or 'all'}"
        if action in ("on", "off"):
            if not positional:
                raise ValueError(f"ha {action}: device number required")
            num = int(positional[0])
            h.ha_on_off_set.num = num
            h.ha_on_off_set.on_off = action == "on"
            if part_auth is not None:
                h.ha_on_off_set.partition_auth = part_auth
            return h.SerializeToString(), f"ha {action} num={num}"
        if action == "toggle":
            if not positional:
                raise ValueError("ha toggle: device number required")
            num = int(positional[0])
            h.ha_toggle_set.num = num
            if part_auth is not None:
                h.ha_toggle_set.partition_auth = part_auth
            return h.SerializeToString(), f"ha toggle num={num}"
        if action == "level":
            if len(positional) < 2:
                raise ValueError("ha level: expected <num> <0-100|on|off>")
            num = int(positional[0])
            h.ha_level_set.num = num
            level_arg = positional[1].lower()
            if level_arg == "on":
                h.ha_level_set.on_off = True
            elif level_arg == "off":
                h.ha_level_set.on_off = False
            else:
                h.ha_level_set.level = int(level_arg)
            if part_auth is not None:
                h.ha_level_set.partition_auth = part_auth
            return h.SerializeToString(), f"ha level num={num} {level_arg}"
        if action in ("lock", "unlock"):
            if not positional:
                raise ValueError(f"ha {action}: device number required")
            num = int(positional[0])
            h.ha_lock_set.num = num
            h.ha_lock_set.lock_unlock = action == "lock"
            if part_auth is not None:
                h.ha_lock_set.partition_auth = part_auth
            return h.SerializeToString(), f"ha {action} num={num}"

    # --- system / panel (alias) ---
    if domain in ("system", "panel"):
        if action == "status":
            h.system_status_get.SetInParent()
            return h.SerializeToString(), f"{domain}_status_get"

    # --- alarm ---
    if domain == "alarm":
        notify_cs = kwargs.get("notify_cs", "y").lower() in ("y", "yes", "true", "1")
        if action == "panic":
            h.send_panic_alarm.notify_cs = notify_cs
            return h.SerializeToString(), f"send_panic_alarm notify_cs={notify_cs}"
        if action == "fire":
            h.send_fire_alarm.SetInParent()
            return h.SerializeToString(), "send_fire_alarm"
        if action == "medical":
            h.send_medical_alarm.notify_cs = notify_cs
            return h.SerializeToString(), f"send_medical_alarm notify_cs={notify_cs}"

    # --- pgm (leaf — no action word, direct args) ---
    if domain == "pgm":
        if len(positional) < 2:
            raise ValueError("pgm: expected <num> <on|off|toggle>")
        num = int(positional[0])
        state_name = positional[1].lower()
        io_set_val = PGM_STATES.get(state_name)
        if io_set_val is None:
            raise ValueError(f"pgm: unknown state '{state_name}' (on/off/toggle)")
        if "pin" not in kwargs and len(positional) > 2:
            h.pin = positional[2]
        h.io_output_set.num = num
        h.io_output_set.io_set = io_set_val
        return h.SerializeToString(), f"pgm num={num} {state_name}"

    raise ValueError(f"unknown command: {domain} {action or ''}".rstrip())


class ReplCompleter(Completer):
    """Context-sensitive completer: domain → action → sub-args."""

    def get_completions(self, document, complete_event):  # noqa: ARG002
        before = document.text_before_cursor

        # idx 0 — first word completion matches raw text so `/h` can hit `/help`.
        if " " not in before:
            for c in sorted(DOMAINS) + _META_COMMANDS:
                if c.startswith(before):
                    yield Completion(c, start_position=-len(before))
            return

        tokens = before.lstrip("/").split()
        if before.endswith(" "):
            tokens.append("")
        idx = len(tokens) - 1
        domain = tokens[0].lower()
        current = tokens[idx]

        action = tokens[1].lower() if len(tokens) > 1 else ""
        candidates: list[str] = []
        if domain == "clear" and idx >= 1:
            candidates = sorted(set(RETAINED_TOPIC_TEMPLATES))
        elif idx == 1:
            # action for the given domain
            candidates = sorted(DOMAINS.get(domain, set()))
        elif domain == "pgm" and idx == 2:
            # pgm <num> <state>
            candidates = _PGM_STATE_NAMES
        elif domain == "partition" and action == "arm" and idx == 3:
            # partition arm <num> <level>
            candidates = _ARM_LEVEL_NAMES

        for c in candidates:
            if c.startswith(current):
                yield Completion(c, start_position=-len(current))


def _bottom_toolbar():
    """Shows the signature of the command currently being typed."""
    try:
        buf = get_app().current_buffer.document.text_before_cursor
    except Exception:
        return ""
    tokens = buf.lstrip("/").split()
    domain = tokens[0].lower() if tokens else ""
    action = tokens[1].lower() if len(tokens) > 1 else None
    sig = (
        SIGNATURES.get((domain, action))
        or SIGNATURES.get((domain,))
        or _DOMAIN_HINT.get(domain)
        or "tab=complete  hjkl/arrows=menu-nav  ctrl-r=search  ctrl-c/ctrl-d=exit"
    )
    return HTML(f"<ansigray>{html.escape(sig)}</ansigray>")


def _build_menu_keybindings() -> KeyBindings:
    """hjkl and arrow keys for navigating the completion menu, active only while it's open."""
    kb = KeyBindings()

    @kb.add("j", filter=has_completions)
    @kb.add("down", filter=has_completions)
    def _(event):
        event.current_buffer.complete_next()

    @kb.add("k", filter=has_completions)
    @kb.add("up", filter=has_completions)
    def _(event):
        event.current_buffer.complete_previous()

    @kb.add("h", filter=has_completions)
    @kb.add("left", filter=has_completions)
    def _(event):
        event.current_buffer.complete_previous()

    @kb.add("l", filter=has_completions)
    @kb.add("right", filter=has_completions)
    def _(event):
        event.current_buffer.complete_next()

    return kb


async def _clear_retained_topics(client, serial: str, password: str, suffixes: list[str]):
    """Clear specific retained topics via a temporary MQTT connection."""
    try:
        async with client.connect_mqtt(serial, password) as mqtt_conn:
            for suffix in suffixes:
                await mqtt_conn.publish(suffix, b"", qos=1, retain=True)
                print(f"  {GRAY}cleared:{RST} {serial}/{suffix}")
            print(f"  {GRAY}done:{RST} cleared {len(suffixes)} topic(s)")
    except Exception as e:
        print(f"  {topic_color('e')}error:{RST} {e}")
        print(f"  {GRAY}(direct MQTT may not be accessible from your network){RST}")


async def interactive_sender(conn, pending: dict[int, tuple[float, str]], client=None, password: str = "123123"):
    """REPL: hex payloads or commands. Assigns msg_ids and registers them for response matching."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=ReplCompleter(),
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        key_bindings=_build_menu_keybindings(),
    )
    next_msg_id = 1000

    print("Interactive mode: type hex or /help. Ctrl-D to quit.")
    while True:
        try:
            line = await session.prompt_async("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in ("q", "quit", "/quit", "/q"):
            break
        if text in ("/help", "/?", "?", "help"):
            print(HELP_TEXT)
            continue
        if text.lower().startswith("clear") or text.lower().startswith("/clear"):
            if client is None:
                print(f"  {topic_color('e')}error:{RST} client not available")
                continue
            clear_args = text.lstrip("/").split()[1:]
            serial = conn.device_serial
            try:
                if not clear_args:
                    print(f"  Clearing all retained topics for {serial} via API...")
                    result = await client.cleanup_device(serial)
                    print(f"  {GRAY}done:{RST} {result}")
                else:
                    await _clear_retained_topics(client, serial, password, clear_args)
            except Exception as e:
                print(f"  {topic_color('e')}error:{RST} {e}")
            continue

        parts = text.lstrip("/").split()
        domain = parts[0].lower() if parts else ""
        try:
            if domain in DOMAINS:
                msg_id = next_msg_id
                next_msg_id += 1
                if DOMAINS[domain]:
                    # domain with actions (partition, zone, system, panel)
                    if len(parts) < 2:
                        raise ValueError(f"{domain}: action required (try tab)")
                    action = parts[1].lower()
                    if action not in DOMAINS[domain]:
                        raise ValueError(f"{domain} {action}: unknown action")
                    payload, desc = build_command_payload(domain, action, parts[2:], msg_id)
                else:
                    # leaf domain (pgm) — args follow directly
                    payload, desc = build_command_payload(domain, None, parts[1:], msg_id)
            elif text.startswith("/"):
                raise ValueError(f"unknown command: /{domain} (try /help)")
            else:
                payload = bytes.fromhex(text)
                try:
                    parsed = Helix()
                    parsed.ParseFromString(payload)
                    msg_id = parsed.msg_id or None
                except Exception:
                    msg_id = None
                desc = f"raw {len(payload)}b"
        except Exception as e:
            print(f"  {topic_color('e')}error:{RST} {e}")
            continue

        try:
            await conn.send(payload)
        except websockets.exceptions.ConnectionClosed as e:
            print(f"  {topic_color('e')}connection closed:{RST} {e}")
            break
        if msg_id is not None:
            pending[msg_id] = (time.monotonic(), desc)
        hex_preview = payload[:50].hex() + ("..." if len(payload) > 50 else "")
        print(f"  {GRAY}→{RST} sent msg_id={msg_id} ({desc}) {GRAY}{len(payload)}b{RST}")
        print(f"    {GRAY}hex:{RST}     {GRAY}{hex_preview}{RST}")


async def _listener(conn, pending, topic_filter):
    """Print incoming messages; match against pending msg_ids for latency tracking."""
    try:
        async for message in conn.messages():
            _print_message(message, pending, topic_filter)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"{topic_color('e')}connection closed:{RST} {e}")


def _print_message(message, pending, topic_filter):
    code = message.topic_type.value
    if topic_filter and code not in topic_filter:
        return
    cc = topic_color(code)
    ts = message.received_at.strftime("%H:%M:%S.%f")[:-3]
    print(f"{GRAY}{ts}{RST} {cc}{BOLD}{message.topic}{RST} {GRAY}{len(message.payload)}b{RST}")
    print(f"  {GRAY}hex:{RST}     {GRAY}{message.payload[:50].hex()}{'...' if len(message.payload) > 50 else ''}{RST}")
    if message.helix:
        h = message.helix
        print(f"  {GRAY}message:{RST} {cc}{BOLD}{h.message_name}{RST} {GRAY}msg_id={h.msg_id} field={h.msg_field}{RST}")
        match = pending.pop(h.msg_id, None)
        if match:
            elapsed_ms = (time.monotonic() - match[0]) * 1000
            print(f"  {GRAY}↳ match:{RST} {WHITE}{match[1]}{RST} {GRAY}in {elapsed_ms:.0f}ms{RST}")
        try:
            payload_dict = MessageToDict(h.payload, preserving_proto_field_name=True)
            if payload_dict:
                print(f"  {GRAY}payload:{RST} {WHITE}{BOLD}{payload_dict}{RST}")
            if h.topic_code in ("r", "cdr"):
                err = payload_dict.get("error")
                if err:
                    print(f"  {topic_color('e')}{BOLD}✗ {err}{RST}")
                else:
                    print(f"  {topic_color('r')}{BOLD}✓ OK{RST}")
        except Exception as e:
            print(f"  {GRAY}error:{RST}   {topic_color('e')}{e}{RST}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="Subscribe to a device via WebSocket")
    parser.add_argument("serial", help="Device serial number")
    parser.add_argument("--payload", help="Hex payload to send on connect")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode: send hex payloads from stdin")
    parser.add_argument("--secondary", "-s", action="store_true", help="Use secondary shard (1-B)")
    parser.add_argument("--clear-retained", action="store_true", help="Clear all retained MQTT messages before subscribing")
    parser.add_argument("--password", "-p", default="123123", help="Device password for --clear-retained (default: 123123)")
    parser.add_argument("--max-num", type=int, default=16, help="Max number for numbered retained topics (default: 16)")
    parser.add_argument("--filter", "-f", help="Comma-separated topic codes to show (e.g. r,s,i,cf,cd,e,c)")
    parser.add_argument("--verbose", "-v", action="count", default=0, help="Increase log verbosity (-v=INFO, -vv=DEBUG)")
    args = parser.parse_args()
    topic_filter = set(args.filter.split(",")) if args.filter else None

    log_level = logging.WARNING
    if args.verbose >= 2:
        log_level = logging.DEBUG
    elif args.verbose >= 1:
        log_level = logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print(f"Subscribing to device {args.serial} via WebSocket...")

    pending: dict[int, tuple[float, str]] = {}

    async with NextGenMQTTClient.staging() as client:
        if args.clear_retained:
            await clear_retained(client, args.serial, args.password, args.secondary, args.max_num)

        async with client.connect_websocket(args.serial, use_secondary=args.secondary) as conn:
            print(f"Connected! Device: {conn.device_serial}")

            if args.payload:
                payload = bytes.fromhex(args.payload)
                print(f"Sending payload: {args.payload} ({len(payload)} bytes)")
                await conn.send(payload)

            print("Waiting for messages (Ctrl+C to exit)...\n")

            if args.interactive:
                # patch_stdout keeps the prompt line stable while messages scroll above it.
                with patch_stdout(raw=True):
                    listener_task = asyncio.create_task(_listener(conn, pending, topic_filter))
                    try:
                        await interactive_sender(conn, pending, client=client, password=args.password)
                    finally:
                        listener_task.cancel()
            else:
                await _listener(conn, pending, topic_filter)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
