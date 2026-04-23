"""bss-self-serve — customer-facing signup portal (v0.4+).

A thin FastAPI + Jinja + HTMX skin over the LLM orchestrator. The
hero artifact is the Agent Activity side-panel — the portal's back
end sends every write through ``bss_orchestrator.session.astream_once``
and streams tool-call events into the browser via SSE so the viewer
watches the agent work as their signup completes.

See ``phases/V0_4_0.md`` for the full spec and ``DECISIONS.md`` 2026-04-24
for the "portal writes route through the LLM orchestrator" rationale.
"""
