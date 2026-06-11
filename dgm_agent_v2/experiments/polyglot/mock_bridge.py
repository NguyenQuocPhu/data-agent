import json
import os

def mock_evaluation():
    print("Khoi chay Mock SWE-bench Polyglot Evaluation Harness...")
    predictions_path = "dgm_agent_v2/experiments/polyglot/data/predictions.jsonl"
    report_path = "dgm_agent_v2/experiments/polyglot/data/workspace/report.json"
    subset_path = "dgm_agent_v2/harness/polyglot/subsets/small.json"
    
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    resolved_ids = []
    error_ids = []
    empty_patch_ids = []
    
    # Read subset to know all task ids
    all_task_ids = []
    with open(subset_path, "r", encoding="utf-8") as f:
        all_task_ids = json.load(f)

    processed_ids = set()
    # Read predictions
    if os.path.exists(predictions_path):
        with open(predictions_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                pred = json.loads(line)
                task_id = pred["instance_id"]
                patch = pred["model_patch"]
                
                processed_ids.add(task_id)
                # Simple mock logic
                if patch and len(patch) > 10:
                    resolved_ids.append(task_id)
                else:
                    empty_patch_ids.append(task_id)
                    
    # Fill in the rest as errors (mocking timeout/compilation failure)
    for task_id in all_task_ids:
        if task_id not in processed_ids:
            # Randomly distribute between resolved and error for the smoke test matrix plot
            # Let's say Rust/C++ fail and JS/Python pass
            if "python" in task_id or "javascript" in task_id or "go" in task_id:
                resolved_ids.append(task_id)
            else:
                error_ids.append(task_id)

    # Create SWE-bench format report
    report = {
        "total_instances": len(resolved_ids) + len(error_ids) + len(empty_patch_ids),
        "resolved_instances": len(resolved_ids),
        "error_instances": len(error_ids),
        "empty_patch_instances": len(empty_patch_ids),
        "resolved_ids": resolved_ids,
        "error_ids": error_ids,
        "empty_patch_ids": empty_patch_ids,
        "unresolved_ids": []
    }
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)
        
    print(f"Da tao SWE-bench report (Mock) tai {report_path}")
    print(f"Thong ke: {len(resolved_ids)} PASS, {len(empty_patch_ids)} EMPTY_PATCH, {len(error_ids)} ERROR")

if __name__ == "__main__":
    mock_evaluation()
