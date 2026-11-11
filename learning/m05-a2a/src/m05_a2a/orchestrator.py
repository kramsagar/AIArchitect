"""The M4 graph, unchanged, but every specialist is a remote A2A agent. Only the human approval gate and the
checkpointer stay in the orchestrator: the caller owns the workflow state, agents own their skills."""

from __future__ import annotations

from m04_crew.crew import Crew
from m04_crew.graph import build_graph

from .client import A2AClient


class RemoteCrew:
    """Duck-types `m04_crew.Crew`: same node names, but each node is one A2A SendMessage."""

    approval = Crew.approval  # stays local: a human decides, not a remote agent
    after_triage = staticmethod(Crew.after_triage)
    after_approval = staticmethod(Crew.after_approval)
    after_verify = staticmethod(Crew.after_verify)

    def __init__(self, client: A2AClient) -> None:
        self.client = client

    def _remote(self, skill: str):
        def node(state, config=None):
            thread = (config or {}).get("configurable", {}).get("thread_id", "")
            return self.client.call(skill, dict(state), thread_id=thread)

        node.__name__ = skill
        return node

    def __getattr__(self, skill: str):
        if skill.startswith("_"):
            raise AttributeError(skill)
        return self._remote(skill)


def build_remote_graph(client: A2AClient, checkpointer=None):
    return build_graph(RemoteCrew(client), checkpointer=checkpointer)
