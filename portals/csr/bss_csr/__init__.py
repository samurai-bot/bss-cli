"""bss-csr — CSR (customer service rep) console.

A small FastAPI + Jinja + HTMX portal on port 9002. Operators log in
(stub auth), search for a customer, open a 360 view, and ask the LLM
agent to investigate or act on the customer's behalf. Every write
goes through ``agent_bridge.ask_about_customer`` (which wraps
``bss_orchestrator.session.astream_once``) — route handlers never call
mutating bss-clients methods directly.

The agent log widget, SSE plumbing, base CSS, and vendored HTMX live
in ``bss_portal_ui`` (extracted in v0.5 so this portal and the
self-serve portal share the same UI primitives).
"""
