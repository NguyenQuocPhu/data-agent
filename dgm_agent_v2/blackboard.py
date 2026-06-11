import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dgm_agent_v2.implementations.file_readers import FileReaderFactory, FileContext


@dataclass
class BlackboardRequest:
    """Request posted to the Blackboard."""
    query: str = ""
    publisher: str = ""
    task_id: str = ""
    question: str = ""
    data_lake_dir: str = ""


@dataclass
class BlackboardResponse:
    """Response from a FileAgent."""
    agent_id: str
    cluster_name: str
    file_contexts: List[FileContext] = field(default_factory=list)
    relevance_score: float = 0.0


class Blackboard:
    """
    Central Hub where requests and responses are posted via Pub/Sub.
    Does NOT execute logic, only aggregates contexts.
    """
    def __init__(self):
        self.request: Optional[BlackboardRequest] = None
        self.responses: List[BlackboardResponse] = []
        self.agents: List['FileAgent'] = []

    def register_agent(self, agent: 'FileAgent'):
        """Registers a FileAgent to the Blackboard."""
        self.agents.append(agent)

    def post_request(self, request: BlackboardRequest):
        self.request = request
        self.responses = []
        q = request.query if request.query else request.question
        print(f"\n📋 [Blackboard] Request posted: '{q[:80]}...'")
        
        # Notify all registered agents
        for agent in self.agents:
            response = agent.handle_request(request)
            self.post_response(response)

    def post_response(self, response: BlackboardResponse):
        self.responses.append(response)

    def get_aggregated_context(self) -> str:
        return self.get_context_summary()

    def get_context_summary(self) -> str:
        """Aggregates context from all relevant FileAgents."""
        if not self.responses:
            return "No relevant data files found."

        sorted_responses = sorted(self.responses, key=lambda r: r.relevance_score, reverse=True)
        lines = ["=== DATA LAKE CONTEXT ==="]
        
        for resp in sorted_responses:
            lines.append(f"[Cluster: {resp.cluster_name}]")
            for fc in resp.file_contexts:
                if fc.error:
                    lines.append(f"  File: {fc.file_path}  → ⚠️ Error: {fc.error}")
                    continue
                lines.append(f"  File: {fc.file_path} (type={fc.file_type})")
                if fc.columns:
                    lines.append(f"    Columns: {fc.columns}")
                if fc.dtypes:
                    dtype_str = ", ".join(f"{k}: {v}" for k, v in list(fc.dtypes.items())[:10])
                    lines.append(f"    Dtypes: {dtype_str}")
                if fc.preview:
                    lines.append(f"    Preview:\n{fc.preview}")
            lines.append("")
            
        context = "\n".join(lines)
        if len(context) > 60000:
            context = context[:60000] + "\n...[TRUNCATED]..."
        return context


class FileAgent:
    """
    Agent responsible for reading a cluster of files and responding to requests.
    """
    def __init__(self, agent_id: str, cluster_name: str, file_paths: List[str]):
        self.agent_id = agent_id
        self.cluster_name = cluster_name
        self.file_paths = file_paths

    def _compute_relevance(self, question: str, file_contexts: List[FileContext]) -> float:
        q = question if question else ""
        question_lower = q.lower()
        keywords = set(re.findall(r"\b\w{3,}\b", question_lower))
        stop_words = {"the", "and", "for", "with", "what", "find", "data", "calculate", "using"}
        keywords -= stop_words

        if not keywords:
            return 0.1

        match_count = sum(
            len(set(re.findall(r"\b\w{3,}\b", col.lower())) & keywords)
            for fc in file_contexts if not fc.error
            for col in fc.columns
        )
        return min(1.0, match_count / max(len(keywords), 1))

    def handle_request(self, request: BlackboardRequest) -> BlackboardResponse:
        print(f"  🤖 FileAgent [{self.agent_id}] scanning cluster '{self.cluster_name}'...")
        contexts = []
        q = request.query if request.query else request.question
        for fp in self.file_paths:
            reader = FileReaderFactory.get_reader(fp)
            contexts.append(reader.read(fp, q))
            
        relevance = self._compute_relevance(q, contexts)
        return BlackboardResponse(self.agent_id, self.cluster_name, contexts, relevance)


def build_file_agents(data_lake_dir: str, max_files_per_cluster: int = 5) -> List[FileAgent]:
    """Helper to partition the datalake into FileAgents."""
    data_root = Path(data_lake_dir)
    if not data_root.exists():
        return []

    DATA_EXTS = {".csv", ".xlsx", ".json", ".txt"}
    all_files = [str(f) for f in data_root.rglob("*") if f.is_file() and f.suffix.lower() in DATA_EXTS]

    clusters: Dict[str, List[str]] = defaultdict(list)
    for fpath in all_files:
        rel = Path(fpath).relative_to(data_root)
        cluster_key = str(rel.parent)
        clusters[cluster_key].append(fpath)

    agents = []
    for idx, (c_name, files) in enumerate(clusters.items()):
        # Simple clustering for demonstration
        agent = FileAgent(f"file_agent_{idx:02d}", c_name, files[:max_files_per_cluster])
        agents.append(agent)
    return agents
