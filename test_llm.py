from dgm_agent.llm import get_response_from_llm, create_client
client, model_name = create_client('hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8')
prompt='''Note: import json is required for output format.
You are an expert Data Scientist. Solve the following data science question using Python.

QUESTION:
Question: question7

INSTRUCTIONS:
- Use the exact file paths shown above to load the data.
- Use pandas, numpy, or other standard data science libraries.
- Handle missing values (NaN) appropriately.
- In your code, you must use the print() function to output the final answer in a valid JSON format like this: print(json.dumps({"main-task": final_answer})). Do not print DataFrame summaries or any other text.
- Return ONLY valid, executable Python code inside ```python ``` blocks.'''

resp, _ = get_response_from_llm(prompt, client, model_name, 'You are an expert data scientist. Generate clean, executable Python code.', 0.2)
print("RAW RESPONSE:")
print(repr(resp))
print("EXTRACTED:")
import re
def _extract_python_code(text: str) -> str:
    match = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()
print(repr(_extract_python_code(resp)))
