I just armed a security panel by typing "do arm" into Claude Code.

No SDK. No manual protobuf serialization. No hex payload debugging. Just a conversation.

Here's what actually happened — and why it's a perfect demo of what Model Context Protocol (MCP) unlocks.

---

The setup: Claude Code connected to an MCP server that understands 217 protobuf message types for our security protocol — and a Python script in the repo to send payloads to devices over WebSocket/MQTT.

I typed "do arm" and Claude built the protobuf message, serialized it, sent it to the device, and got back:

  ARM_ERR_NOT_READY

The panel refused to arm. Here's where it gets interesting.

Claude didn't just report the error. It reasoned about it:

  "The partition can't arm because a zone is faulted."

Then it proposed three options:
  1. Close the violated zone and retry
  2. Force arm despite the fault
  3. Bypass the faulted zone first

I picked force arm — the device still rejected it. Claude adapted. It queried all 8 zones through MCP and found the culprit:

  Zone 4: open_violated = true

It asked: "Want me to bypass zone 4 and retry?"

I said yes. Two messages later:

  ZoneBypass zone 4 → success
  Arm partition 1   → success

Panel armed. Problem solved.

---

What happened behind the scenes at each step:

- Claude queried the protobuf schema through MCP when field names didn't match (arming_type vs level, partition_number vs partition_num) — and self-corrected
- It interpreted domain-specific error codes and mapped them to real causes
- It proposed multiple resolution paths and let me choose
- It chained dependent operations — bypass first, then arm — with proper message correlation

The whole flow took under 30 seconds.

---

Without MCP, this is a 5-step manual process: look up schemas, serialize with a CLI tool, send via WebSocket client, deserialize the response, interpret error codes, repeat.

With MCP, I just said what I wanted. The AI handled the protocol, adapted to failures, and drove toward resolution.

This is what happens when you give AI the right tools — not just knowledge, but the ability to act, observe, and adapt in real time.

#MCP #AI #IoT #ClaudeCode #Protobuf #MQTT #SecuritySystems #DeveloperTools
