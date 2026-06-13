import argparse
import datetime
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import docker
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datasets import load_dataset

from prompts.testrepo_prompt import get_test_description
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.docker_build import build_env_images, build_container, cleanup_container

from swe_bench.utils import (
    copy_to_container,
    copy_from_container,
    log_container_output,
    remove_existing_container,
    safe_log,
    setup_logger,
)
from utils.common_utils import load_json_file

def process_entry(entry, out_dname, model_name_or_path, model_patch_paths):
    """
    Process a single dataset entry. This function encapsulates the main processing logic
    for each entry to make it suitable for parallel execution.
    """
    instance_id = entry['instance_id']
    problem_statement = entry['problem_statement']
    base_commit = entry['base_commit']
    chat_history_file = out_dname / (instance_id + ".md")
    out_fname = out_dname / (instance_id + ".json")
    eval_file = out_dname / f"{instance_id}_eval.sh"

    # Skip if output result already exists
    if out_fname.exists():
        print(f"Skipping existing entry {instance_id}")
        return {"success": True, "instance_id": instance_id}

    try:
        # Create and start the Docker container
        client = docker.from_env()
        run_id = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        # Set up thread-specific logger
        log_file = out_dname / f"{instance_id}_docker.log"
        logger = setup_logger(str(log_file))
        
        # Create console handler to stream to terminal
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        nocache = True
        test_spec = make_test_spec(entry, instance_image_tag="latest", env_image_tag="latest")
        # Remove any existing container with the same name
        container_name = test_spec.get_instance_container_name(run_id)
        remove_existing_container(client, container_name)
        # Now create and start the container
        container = build_container(test_spec, client, run_id, logger, nocache, force_rebuild=False)
        container.start()

        # Navigate to dgm_agent directory (parent of swe_bench/)
        dgm_agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.chdir(dgm_agent_dir)
        logger.info(f"Working directory set to: {dgm_agent_dir}")

        # Copy the necessary files and requirements to the container
        copy_to_container(container, 'coding_agent.py', '/dgm/coding_agent.py')
        copy_to_container(container, 'requirements.txt', '/dgm/requirements.txt')
        copy_to_container(container, 'pytest.ini', '/dgm/pytest.ini')
        copy_to_container(container, 'tools/', '/dgm/tools/')
        copy_to_container(container, 'utils/', '/dgm/utils/')
        copy_to_container(container, 'tests/', '/dgm/tests/')
        copy_to_container(container, 'prompts/', '/dgm/prompts/')
        copy_to_container(container, 'llm.py', '/dgm/llm.py')
        copy_to_container(container, 'llm_withtools.py', '/dgm/llm_withtools.py')
        chat_history_file_container = f'/dgm/{chat_history_file.name}'

        # Install issue requirements
        logger.info("Setting up environment")
        eval_script = test_spec.eval_script
        # Write with Unix LF line endings (binary mode) to avoid Windows CRLF breaking bash scripts in Linux container
        eval_file.write_bytes(eval_script.replace('\r\n', '\n').encode('utf-8'))
        copy_to_container(container, eval_file, '/eval.sh')
        # Make sure eval.sh is executable with Unix line endings inside container
        container.exec_run("sed -i 's/\r//' /eval.sh", workdir='/')
        exec_result = container.exec_run("/bin/bash /eval.sh", workdir='/')  # setup environment
        log_container_output(exec_result)
        exec_result = container.exec_run("rm /eval.sh", workdir='/')  # remove eval script
        log_container_output(exec_result)

        # Get test description
        test_description = get_test_description(eval_script=eval_script, swerepo=True)

        # Apply model patch
        if model_patch_paths:
            safe_log("Applying model patches")
            for model_patch_path in model_patch_paths:
                copy_to_container(container, model_patch_path, '/dgm/parent_patch.txt')
                exec_result = container.exec_run("/bin/sh -c 'patch -p1 < /dgm/parent_patch.txt'", workdir='/dgm')
                log_container_output(exec_result)
                exec_result = container.exec_run("rm /dgm/parent_patch.txt", workdir='/dgm')
                log_container_output(exec_result)

        # Install this repo requirements
        safe_log("Installing more requirements")
        exec_result = container.exec_run("python -m pip install -r /dgm/requirements.txt", workdir='/')
        log_container_output(exec_result)

        # Run the agent
        env_vars = {
            "ANTHROPIC_API_KEY": os.getenv('ANTHROPIC_API_KEY'),
            "AWS_REGION": os.getenv('AWS_REGION'),
            "AWS_REGION_NAME": os.getenv('AWS_REGION_NAME'),
            "AWS_ACCESS_KEY_ID": os.getenv('AWS_ACCESS_KEY_ID'),
            "AWS_SECRET_ACCESS_KEY": os.getenv('AWS_SECRET_ACCESS_KEY'),
            "OPENAI_API_KEY": os.getenv('OPENAI_API_KEY'),
            "GROQ_API_KEY": os.getenv('GROQ_API_KEY'),
        }
        safe_log("Running the agent")
        cmd = [
            "timeout", "3600",  # 1h timeout
            "python", "/dgm/coding_agent.py",
            "--problem_statement", problem_statement,
            "--git_dir", "/testbed/",
            "--chat_history_file", chat_history_file_container,
            "--base_commit", base_commit,
            "--outdir", "/dgm/",
            "--test_description", test_description,
            "--instance_id", instance_id,
            "--model", model_name_or_path,
        ]
        exec_result = container.exec_run(cmd, environment=env_vars, workdir='/')
        log_container_output(exec_result)

        # Copy output files back to host
        logger.info("Copying output files back to host")
        copy_from_container(container, chat_history_file_container, chat_history_file)
        # Additional chat history files
        exec_result = container.exec_run(f"find /dgm/ -name '{instance_id}_*.md'", workdir='/')
        chat_history_files_container = exec_result.output.decode().split()
        for chat_history_file_container in chat_history_files_container:
            chat_history_file = out_dname / Path(chat_history_file_container).name
            copy_from_container(container, chat_history_file_container, chat_history_file)

        # Get model_patch
        logger.info("Getting model_patch")
        exec_result = container.exec_run("cat /dgm/model_patch.diff")
        log_container_output(exec_result)
        model_patch = exec_result.output.decode()
        # Additional proposed model patches
        proposed_model_patches = []
        exec_result = container.exec_run("find /dgm/ -name 'model_patch_*.diff'", workdir='/')
        model_patch_files_container = exec_result.output.decode().split()
        for model_patch_file_container in model_patch_files_container:
            exec_result = container.exec_run(f"cat {model_patch_file_container}")
            log_container_output(exec_result)
            proposed_model_patch = exec_result.output.decode()
            proposed_model_patches.append(proposed_model_patch)

        # Write result to file
        result = {
            "instance_id": instance_id,
            "model_name_or_path": model_name_or_path,
            "model_patch": model_patch,
            'proposed_model_patches': proposed_model_patches,
        }
        out_fname.write_text(json.dumps(result, indent=4))

        return {"success": True, "instance_id": instance_id}

    except Exception as e:
        print(f"Error processing entry {instance_id}: {str(e)}")
        return {"success": False, "instance_id": instance_id, "error": str(e)}

    finally:
        # Clean up docker container
        try:
            cleanup_container(client, container, logger)
        except Exception as e:
            print(f"Error cleaning up Docker container for {instance_id}: {e}")

def harness(
        test_task_list=None,
        num_samples=-1,
        max_workers=4,
        model_name_or_path=None,
        model_patch_paths=None,
        num_evals=1,
        num_evals_parallel=1,
        pred_dname='./swe_bench/predictions',
    ):
    """
    Parallel processing harness using ThreadPoolExecutor.
    
    Args:
        test_task_list: List of task IDs to process (None for all)
        num_samples: Number of samples to process (-1 for all)
        max_workers: Maximum number of concurrent threads
        model_name_or_path: Model name or path
        model_patch_paths: Paths to the model patches for dgm
        num_evals: Repeated number of swe evaluations
    """
    # Load dataset
    dataset = load_dataset("princeton-nlp/SWE-bench_Verified")
    dataset = dataset['test']
    
    # Ensure that necessary directories exist
    if model_name_or_path is None:
        model_name_or_path = "hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8"
    pred_dname = Path(pred_dname).resolve()
    pred_dname.mkdir(parents=True, exist_ok=True)
    out_dnames = []
    
    # Prepare the dataset entries
    entries = list(dataset)
    if test_task_list:
        entries = [entry for entry in entries if entry['instance_id'] in test_task_list]
    if num_samples > 0:
        entries = entries[:num_samples]

    # Build the environment images
    client = docker.from_env()
    build_env_images(client, dataset=entries, force_rebuild=False, max_workers=max_workers, instance_image_tag="latest", env_image_tag="latest")
    
    # Define a function to handle a single evaluation for all specified issues
    def process_evaluation(eval_idx):
        model_name_or_path_inst = f"{model_name_or_path}_{eval_idx}"
        out_dname = pred_dname / model_name_or_path_inst
        out_dname.mkdir(parents=True, exist_ok=True)
        
        print(f"Starting evaluation {eval_idx} for model {model_name_or_path}")
        
        # Process entries in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_entry = {
                executor.submit(process_entry, entry, out_dname, model_name_or_path, model_patch_paths): entry
                for entry in entries
            }
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_entry):
                result = future.result()
                if result["success"]:
                    print(f"Successfully processed entry {result['instance_id']} for eval {eval_idx}")
                else:
                    print(f"Failed to process entry {result['instance_id']} for eval {eval_idx}: {result.get('error', 'Unknown error')}")
        return out_dname

    # Process all evaluations in parallel
    with ThreadPoolExecutor(max_workers=num_evals_parallel) as eval_executor:
        out_dnames = list(eval_executor.map(process_evaluation, range(num_evals)))

    print(f"All evaluations completed for model {model_name_or_path}")
    return out_dnames

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_samples", type=int, default=-1, help="Number of samples to process")
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of concurrent threads")
    parser.add_argument("--model_name_or_path", type=str, default=None, help="Model name or path")
    parser.add_argument("--model_patch_paths", type=str, default=None, help="Paths to the model patches")
    parser.add_argument("--num_evals", type=int, default=1, help="Repeated number of swe evaluations")
    parser.add_argument("--num_evals_parallel", type=int, default=1, help="Number of parallel repeated evaluations")
    parser.add_argument("--pred_dname", type=str, default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "predictions"), help="Output directory for predictions")
    parser.add_argument("--test_task_list", type=str, default=None, help="Subset of swe issues to process")
    args = parser.parse_args()
    
    # Load the test task list
    subsets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subsets")
    if args.test_task_list == 'small':
        test_task_list = load_json_file(os.path.join(subsets_dir, "small.json"))
    elif args.test_task_list == 'medium':
        test_task_list = load_json_file(os.path.join(subsets_dir, "medium.json"))
    elif args.test_task_list == 'nano':
        test_task_list = load_json_file(os.path.join(subsets_dir, "nano.json"))
    elif args.test_task_list == 'custom_100':
        test_task_list = load_json_file(os.path.join(subsets_dir, "custom_100.json"))
    else:
        # Default to None, means all of them
        test_task_list = None

    # Run the parallel harness
    out_dnames = harness(
        test_task_list=test_task_list,
        num_samples=args.num_samples,
        max_workers=args.max_workers,
        model_name_or_path=args.model_name_or_path,
        model_patch_paths=args.model_patch_paths,
        num_evals=args.num_evals,
        num_evals_parallel=args.num_evals_parallel,
        pred_dname=args.pred_dname,
    )

    # Generate evaluation report
    try:
        from swe_bench.report import make_report
        # Convert Path objects to relative string paths
        cwd = Path(os.getcwd())
        dnames_str = []
        for dname in out_dnames:
            dpath = Path(dname)
            if dpath.is_absolute():
                dnames_str.append(str(dpath.relative_to(cwd)))
            else:
                dnames_str.append(str(dname))
        
        print("Consolidating predictions and generating reports...")
        make_report(
            dnames=dnames_str,
            dataset_name="princeton-nlp/SWE-bench_Verified",
            output_dir=args.pred_dname,
        )
    except Exception as e:
        print(f"Error generating report: {e}")

if __name__ == "__main__":
    main()
