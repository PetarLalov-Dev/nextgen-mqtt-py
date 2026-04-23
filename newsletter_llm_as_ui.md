The human doesn't learn the interface. The interface understands the human.

"Arm the alarm panel." — Done? No. The panel fights back: ARM_ERR_NOT_READY. A faulted zone is blocking everything.
A traditional app stops here. Red banner. Error code. "Contact support." Good luck.
The LLM doesn't stop. It thinks. It scans all 8 zones, finds the one that's open, and comes back with: "Zone 4 is faulted. Want me to bypass it and arm anyway?"
One word: "Yes." Panel armed.

----

No buttons. No screens. No pre-built workflows. Just a conversation that solves problems.
This is the paradigm shift: from UIs that encode every possible action in advance, to a conversational interface that assembles the right action in the moment.

No "bypass and arm" button — no one pre-built that workflow. No troubleshooting wizard — that failure path wasn't in any UI spec. No error code lookup — the LLM already knew what to do.
The logic wasn't hardcoded. It emerged from the conversation.

Traditional UI builds for what you expect. LLM as UI handles what you don't.

----

I believe traditional UIs will stay. Dashboards, real-time monitoring, quick-glance status — you need a screen for that. I don't see that changing.
But do we still need to hardcode every action into a button? Every edge case into a workflow? Every error into a dialog with three pre-written options?
Or do we build the tools, expose the protocols, and let the LLM compose the right workflow in the moment — for every situation we never thought to design for?

The cost model flips: instead of building screens for every scenario before users need them, you build tools once and let the LLM compose them on demand. The changes happen during acting — not months before in a sprint planning meeting.

----

How it works under the hood.

This isn't a production app — it's a test console. Claude Code running in a terminal, talking to a real alarm panel over the network. No UI was built. No one designed screens or wired up buttons. An engineer types what they want to test, and the LLM executes it against the device.
The key enabler is MCP. The LLM connects to an MCP server — a tool that knows the entire security API. When I typed "do arm," the LLM picked the right message, set the fields (partition 1, level AWAY), serialized it, and sent it to the panel through a Python script.
When the panel refused, the LLM called the same MCP server again — this time to query zone statuses. Found Zone 4 open. Then called it a third time to bypass that zone. Then armed again. Three different API calls, composed and chained on the fly.

In a test environment, the UI investment is zero. You describe scenarios in plain language — the LLM handles the API, the serialization, the error handling. You dictate tests the way you'd explain them to a colleague.
And when this moves to production? The interface changes — maybe it's voice on a phone, maybe it's a chat widget — but the pattern stays the same. The user expresses intent. The LLM acts on it.

#LLM #MCP #IoT #UX #AI
