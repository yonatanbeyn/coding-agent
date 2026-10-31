"""Durable runtime: the same agents, skills and agent skills running on Temporal.

    workflow.py    AgentWorkflow — deterministic agent loop; sub-agents are child workflows
    activities.py  load_agent_setup, llm_complete, run_tool — all side effects
    worker.py      hosts the workflow + activities   (python main.py --worker)
    client.py      start / attach / approve           (python main.py --durable "...")
    types.py       payload dataclasses
"""
