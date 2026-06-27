"""
LangGraph-based Data Agent
Phase 1: Wraps existing TriadicAgent stream_workflow into a LangGraph graph
"""
from .graph import build_graph, DataAgentGraph

__all__ = ["build_graph", "DataAgentGraph"]
