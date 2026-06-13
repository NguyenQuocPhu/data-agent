import os
import time
import json
from typing import Optional

from blade_bench.data.dataset import DatasetInfo
from blade_bench.llms.llm import LLMBase
from blade_bench.nb import SimpleCodeExecutor

from triadic_dgm.benchmark.DGM_orchestrator import TriadicDGMOrchestrator
from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient
from triadic_dgm.benchmark.interfaces.sandbox import ISandbox


class BladeLLMAdapter(ILLMClient):
    """Adapts BLADE's LLMBase to DGM V2's ILLMClient interface."""
    def __init__(self, blade_llm: LLMBase):
        self.blade_llm = blade_llm

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.7) -> str:
        # We append the system prompt to the user prompt since BLADE's LLMBase 
        # might just expect a single string or list of dicts.
        # But wait, LLMBase in BLADE has a generate() method.
        # Let's pass the combined prompt.
        combined_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        # BLADE llm.generate typically takes prompt string and returns string
        # Assuming typical signature: generate(prompt: str, prompt_vars: dict, ...) -> str
        response = self.blade_llm.generate(combined_prompt, {})
        return response


class BladeSandboxAdapter(ISandbox):
    """Adapts BLADE's SimpleCodeExecutor to DGM V2's ISandbox interface."""
    def __init__(self, data_path: str):
        self.data_path = data_path
        self.executor = SimpleCodeExecutor(data_path=data_path, run_init_once=True)

    def execute(self, code: str, task_id: str, timeout: int = 60) -> tuple[bool, str]:
        import asyncio
        start_time = time.time()
        result = asyncio.run(self.executor.run_code(code))
        
        # Determine if execution was successful and get output
        if result.value is not None:
            output = str(result.value)
        else:
            output = str(result.output)
            
        success = True
        if "Traceback" in output or "Error" in output:
            success = False
            
        return success, output


class TriadicDGMAgent:
    """
    Adapter that acts as a BLADE Agent (like ReActAgent) 
    but internally runs the Triadic DGM Orchestrator V2.
    """
    def __init__(
        self,
        llm: LLMBase,
        dinfo: DatasetInfo,
        data_path: str,
        use_data_desc: bool = True,
        use_code_cache: bool = True,
    ):
        self.llm = llm
        self.dinfo = dinfo
        self.data_path = data_path
        self.use_data_desc = use_data_desc
        
        # Adapters
        self.dgm_llm = BladeLLMAdapter(self.llm)
        self.dgm_sandbox = BladeSandboxAdapter(self.data_path)
        
        # Orchestrator
        self.orchestrator = TriadicDGMOrchestrator(
            llm_client=self.dgm_llm,
            sandbox=self.dgm_sandbox,
            max_debug_rounds=3
        )

    def run(self, query: Optional[str] = "", max_turns: int = 10):
        """
        Executes the DGM pipeline to solve the data science task.
        """
        # Construct task question and data lake dir
        task_id = self.dinfo.dataset_name
        data_lake_dir = os.path.dirname(self.data_path)
        
        # Inject Dataset Schema info into the query if allowed
        if self.use_data_desc:
            schema_info = json.dumps(self.dinfo.data_desc, indent=2)
            full_question = f"Dataset Schema:\n{schema_info}\n\nTask: {self.dinfo.research_question}"
        else:
            schema_info = json.dumps(self.dinfo.data_desc_no_desc_no_semantic_type, indent=2)
            full_question = f"Dataset Schema:\n{schema_info}\n\nTask: {self.dinfo.research_question}"

        # Run the DGM Inner Loop
        result = self.orchestrator.run_task(
            task_id=task_id,
            question=full_question,
            data_lake_dir=data_lake_dir
        )
        
        # Return the final JSON representation of the analysis
        final_code = result.get("code", "")
        # The BLADE framework expects a JSON string matching the EntireAnalysis schema
        entire_analysis = {
            "transform_code": final_code,
            "m_code": ""
        }
        return json.dumps(entire_analysis, indent=2)
