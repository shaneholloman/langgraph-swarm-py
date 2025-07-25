import re
from dataclasses import is_dataclass
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.types import Command
from pydantic import BaseModel


def _get_field(obj: Any, key: str) -> Any:
    """Get a field from an object.

    This function retrieves a field from a dictionary, dataclass, or Pydantic model.

    Args:
        obj: The object from which to retrieve the field.
        key: The key or attribute name of the field to retrieve.

    Returns:
        The value of the specified field.

    """
    if isinstance(obj, dict):
        return obj[key]
    if is_dataclass(obj) or isinstance(obj, BaseModel):
        return getattr(obj, key)
    msg = f"Unsupported type for state: {type(obj)}"
    raise TypeError(msg)


WHITESPACE_RE = re.compile(r"\s+")
METADATA_KEY_HANDOFF_DESTINATION = "__handoff_destination"


def _normalize_agent_name(agent_name: str) -> str:
    """Normalize an agent name to be used inside the tool name."""
    return WHITESPACE_RE.sub("_", agent_name.strip()).lower()


def create_handoff_tool(
    *,
    agent_name: str,
    name: str | None = None,
    description: str | None = None,
) -> BaseTool:
    """Create a tool that can handoff control to the requested agent.

    Args:
        agent_name: The name of the agent to handoff control to, i.e.
            the name of the agent node in the multi-agent graph.
            Agent names should be simple, clear and unique, preferably in snake_case,
            although you are only limited to the names accepted by LangGraph
            nodes as well as the tool names accepted by LLM providers
            (the tool name will look like this: `transfer_to_<agent_name>`).
        name: Optional name of the tool to use for the handoff.
            If not provided, the tool name will be `transfer_to_<agent_name>`.
        description: Optional description for the handoff tool.
            If not provided, the tool description will be `Ask agent <agent_name> for help`.

    """
    if name is None:
        name = f"transfer_to_{_normalize_agent_name(agent_name)}"

    if description is None:
        description = f"Ask agent '{agent_name}' for help"

    @tool(name, description=description)
    def handoff_to_agent(
        # Annotation is typed as Any instead of StateLike. StateLike
        # trigger validation issues from Pydantic / langchain_core interaction.
        # https://github.com/langchain-ai/langchain/issues/32067
        state: Annotated[Any, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        tool_message = ToolMessage(
            content=f"Successfully transferred to {agent_name}",
            name=name,
            tool_call_id=tool_call_id,
        )
        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": [*_get_field(state, "messages"), tool_message],
                "active_agent": agent_name,
            },
        )

    handoff_to_agent.metadata = {METADATA_KEY_HANDOFF_DESTINATION: agent_name}
    return handoff_to_agent


def get_handoff_destinations(
    agent: CompiledStateGraph, tool_node_name: str = "tools"
) -> list[str]:
    """Get a list of destinations from agent's handoff tools."""
    nodes = agent.get_graph().nodes
    if tool_node_name not in nodes:
        return []

    tool_node = nodes[tool_node_name].data
    if not isinstance(tool_node, ToolNode):
        return []

    tools = tool_node.tools_by_name.values()
    return [
        tool.metadata[METADATA_KEY_HANDOFF_DESTINATION]
        for tool in tools
        if tool.metadata is not None
        and METADATA_KEY_HANDOFF_DESTINATION in tool.metadata
    ]
