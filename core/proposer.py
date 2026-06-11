try:
    import openai
except ImportError:
    # Stub OpenAI client for environments without the library
    class DummyMessage:
        def __init__(self, content="{}"):
            self.content = content

    class DummyChoice:
        def __init__(self):
            self.message = DummyMessage()

    class DummyCompletions:
        @staticmethod
        def create(**kwargs):
            return type('Response', (), {'choices': [DummyChoice()]})

    class DummyOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = type('Chat', (), {'completions': DummyCompletions})

    openai = DummyOpenAI
import json
import os
import yaml


# System prompt for the Proposer Agent
PROPOSER_SYSTEM_PROMPT = """You are a Proposer Agent in a Darwin Gödel Machine (DGM) system.
Your role is to generate data analysis tasks/problems that are:
1. Grounded in real architectural context (from a knowledge graph node)
2. Appropriately challenging (controlled by a capacity budget)
3. Solvable with Python code in a Jupyter notebook

You must output ONLY a JSON object with these fields:
{
    "task_description": "A clear, specific data analysis task",
    "expected_skills": ["list", "of", "required", "skills"],
    "difficulty_level": "easy|medium|hard",
    "context_source": "the knowledge graph node that inspired this task"
}
"""


class Proposer:
    """
    Proposer Agent (part of the Triadic Roles: Proposer → Solver → Verifier).
    
    Generates data analysis tasks using:
    - Knowledge graph context from Understand-Anything (.understand-anything/knowledge-graph.json)
    - A capacity budget that controls task difficulty
    - Groq API (same key as Programmer/Inspector from config.yaml)
    
    This implements the "Proactive Information Seeking" concept from the Q1 paper:
    instead of random task generation, the Proposer mines the knowledge graph
    for real architectural context to ground its task proposals.
    """

    def __init__(self, budget: int = 100, config_path: str = None, kg_path: str = None):
        """
        Initialize Proposer with a capacity budget, LLM configuration, and Knowledge Graph path.
        
        Args:
            budget: Controls task difficulty (higher = harder tasks).
                    Range guidance: 50-100 = easy, 100-200 = medium, 200+ = hard
            config_path: Path to config.yaml. If None, auto-detect from repo root.
            kg_path: Path to knowledge-graph.json. If None, auto-detect from repo root.
        """
        self.budget = budget
        
        # Load config (same pattern as programmer.py and conversation.py)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if config_path is None:
            config_path = os.path.join(repo_root, "config.yaml")
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        api_key_env_var = config.get("api_key_env_var", "")
        if api_key_env_var and api_key_env_var in os.environ:
            api_key = os.environ[api_key_env_var]
        else:
            api_key = os.environ.get("GROQ_API_KEY", config.get("api_key", "dummy_key"))
            
        base_url = config.get("base_url_conv_model", "https://api.groq.com/openai/v1")
        model = config.get("conv_model", "llama-3.1-8b-instant")
        
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

        # Set up Knowledge Graph path
        if kg_path is None:
            self.kg_path = os.path.join(repo_root, ".understand-anything", "knowledge-graph.json")
        else:
            self.kg_path = kg_path
            
        self.knowledge_graph_nodes = self._load_knowledge_graph()

    def _load_knowledge_graph(self) -> list:
        """Đọc Đồ thị tri thức (Knowledge Graph) do Antigravity sinh ra."""
        if os.path.exists(self.kg_path):
            try:
                with open(self.kg_path, "r", encoding="utf-8") as f:
                    kg = json.load(f)
                return kg.get("nodes", [])
            except Exception:
                pass
        return []

    def proactively_seek_information(self) -> dict:
        """
        Cơ chế Chủ động Tìm kiếm Thông tin (Proactive Information Seeking).
        Trích xuất các hàm/file từ Đồ thị tri thức để làm bối cảnh nâng cấp.
        """
        import random
        if not self.knowledge_graph_nodes:
            # Fallback node if graph is empty/missing
            return {
                "id": "LAMBDA.py",
                "name": "LAMBDA.py",
                "summary": "Core agent class that orchestrates the conversation, programmer, and inspector components",
                "tags": ["core"]
            }
        
        # Chọn ngẫu nhiên một node từ Đồ thị
        return random.choice(self.knowledge_graph_nodes)

    def _difficulty_from_budget(self) -> str:
        """Map budget to difficulty level string."""
        if self.budget <= 100:
            return "easy"
        elif self.budget <= 200:
            return "medium"
        else:
            return "hard"

    def generate_task(self, context_node: dict = None) -> str:
        """
        Generate a data analysis task grounded in a knowledge graph node.
        
        This is the core of "Proactive Information Seeking": instead of 
        generating tasks randomly, we mine the knowledge graph for real 
        architectural context to create meaningful, grounded problems.
        
        Args:
            context_node: A node dict from knowledge-graph.json. If None,
                          it will proactively seek a node using proactively_seek_information().
                          
        Returns:
            str: JSON string containing the task specification
        """
        if context_node is None:
            context_node = self.proactively_seek_information()
            
        difficulty = self._difficulty_from_budget()
        
        user_prompt = (
            f"Generate a {difficulty}-level data analysis task.\n\n"
            f"Context from the system architecture:\n"
            f"- Component: {context_node.get('name', 'unknown')}\n"
            f"- Summary: {context_node.get('summary', 'no summary')}\n"
            f"- Tags: {context_node.get('tags', [])}\n\n"
            f"Capacity Budget: {self.budget}\n\n"
            f"The task should be related to this component's domain and "
            f"solvable with Python in a Jupyter notebook. "
            f"Include realistic sample data generation in the task description."
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROPOSER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,  # Higher temperature for creative task generation
            )
            
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            # Validate JSON structure
            parsed = json.loads(raw)
            return json.dumps(parsed, indent=2)
            
        except json.JSONDecodeError:
            # LLM didn't return valid JSON — wrap the raw response
            print(f"[Proposer] Warning: LLM returned non-JSON, wrapping as task_description")
            fallback = {
                "task_description": raw if 'raw' in dir() else "Generate a basic data analysis task",
                "expected_skills": ["python", "pandas"],
                "difficulty_level": difficulty,
                "context_source": context_node.get("name", "unknown")
            }
            return json.dumps(fallback, indent=2)
            
        except Exception as e:
            print(f"[Proposer] API error: {e}")
            fallback = {
                "task_description": f"Analyze the {context_node.get('name', 'system')} component: "
                                    f"{context_node.get('summary', 'perform basic analysis')}",
                "expected_skills": ["python"],
                "difficulty_level": difficulty,
                "context_source": context_node.get("name", "unknown")
            }
            return json.dumps(fallback, indent=2)

    @staticmethod
    def load_knowledge_stream(repo_root: str) -> list:
        """
        Load knowledge graph nodes from .understand-anything/knowledge-graph.json.
        
        This provides the "information stream" for Proactive Information Seeking.
        
        Args:
            repo_root: Path to the repository root
            
        Returns:
            list: List of node dicts from the knowledge graph
        """
        kg_path = os.path.join(repo_root, '.understand-anything', 'knowledge-graph.json')
        if os.path.exists(kg_path):
            with open(kg_path, 'r', encoding='utf-8') as f:
                kg = json.load(f)
            return kg.get('nodes', [])
        else:
            print("[Proposer] Warning: knowledge-graph.json not found")
            return []
