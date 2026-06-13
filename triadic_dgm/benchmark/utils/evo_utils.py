"""
Evolution utility functions.
Ported from dgm_agent (V1) utils/evo_utils.py
Import paths updated to triadic_dgm.benchmark.
"""
import json
import os

from triadic_dgm.benchmark.utils.common_utils import load_json_file, read_file


def load_dgm_metadata(dgm_metadata_path, last_only=False):
    """Load all archives from given metadata file (JSONL format)."""
    if not os.path.exists(dgm_metadata_path):
        raise FileNotFoundError(f"Metadata file not found at {dgm_metadata_path}")
    # Read all JSON entries from the metadata file
    content = read_file(dgm_metadata_path)
    json_entries = content.split('\n{')
    # Parse all JSON entries
    dgm_metadata = []
    for json_entry in json_entries:
        # Add back the { if it was removed by split
        if not json_entry.startswith('{'):
            json_entry = '{' + json_entry
        metadata = json.loads(json_entry)
        dgm_metadata.append(metadata)

    if last_only:
        return dgm_metadata[-1]
    return dgm_metadata


def get_model_patch_paths(root_dir, dgm_dir, parent_commit):
    """Walk backwards through parent commits to collect all patch files in order."""
    prev_commit = parent_commit
    patch_files = []
    while prev_commit != 'initial':
        parent_dir = os.path.join(root_dir, dgm_dir, prev_commit)
        parent_patch_file = os.path.join(parent_dir, "model_patch.diff")
        if os.path.exists(parent_patch_file):
            patch_files.append(parent_patch_file)
        else:
            print(f"Parent patch file not found: {parent_patch_file}")
        # find next parent commit in the metadata
        parent_metadata = load_json_file(os.path.join(parent_dir, "metadata.json"))
        prev_commit = parent_metadata.get('parent_commit', 'initial')
    return patch_files[::-1]  # reverse the list to get the correct order


def get_all_performance(run_keyword, results_dir='./swe_bench'):
    """
    Retrieve performance results for all runs based on the provided keyword.

    Args:
        run_keyword (str): A keyword used to identify the target runs' evaluation results.
        results_dir (str): Directory containing evaluation result JSON files.

    Returns:
        tuple: (performance_results_list, overall_performance_dict) or (None, None).
    """
    # Find all JSON files in results_dir matching the keyword
    matching_files = [
        f for f in os.listdir(results_dir)
        if f.endswith('.json') and run_keyword in f
    ]

    if not matching_files:
        print(f"No evaluation files found matching the keyword '{run_keyword}'.")
        return None, None

    performance_results = []
    total_resolved_instances = 0
    total_submitted_instances = 0
    total_unresolved_ids = []
    total_resolved_ids = []
    total_emptypatch_ids = []
    for file_name in matching_files:
        eval_agent_path = os.path.join(results_dir, file_name)
        eval_results = load_json_file(eval_agent_path)
        resolved_instances = eval_results.get('resolved_instances', 0)
        submitted_instances = eval_results.get('submitted_instances', 0)
        total_resolved_instances += resolved_instances
        total_submitted_instances += submitted_instances
        accuracy_score = resolved_instances / submitted_instances if submitted_instances > 0 else 0
        performance_results.append({'file': file_name, 'accuracy_score': accuracy_score, **eval_results})
        total_unresolved_ids.extend(eval_results.get('unresolved_ids', []))
        total_emptypatch_ids.extend(eval_results.get('empty_patch_ids', []))
        total_resolved_ids.extend(eval_results.get('resolved_ids', []))

    overall_performance = {
        'accuracy_score': total_resolved_instances / total_submitted_instances if total_submitted_instances > 0 else 0,
        'total_resolved_instances': total_resolved_instances,
        'total_submitted_instances': total_submitted_instances,
        'files': matching_files,
        'total_unresolved_ids': total_unresolved_ids,
        'total_emptypatch_ids': total_emptypatch_ids,
        'total_resolved_ids': total_resolved_ids,
    }

    return performance_results, overall_performance


def is_compiled_self_improve(metadata, num_swe_issues=None, logger=None):
    """
    Checks if the run was properly compiled and 'self-improved' by verifying:
      1. The 'overall_performance' dict has the required keys.
      2. There is at least one non-empty patch (resolved + unresolved > 0).
      3. If num_swe_issues is provided, the total evaluated matches.

    Returns True if all conditions are met, else False.
    """
    if num_swe_issues is None:
        num_swe_issues = []

    def _log(msg):
        if logger:
            logger.info(msg)

    overall_perf = metadata.get('overall_performance', {})
    required_keys = ['accuracy_score', 'total_unresolved_ids', 'total_resolved_ids', 'total_emptypatch_ids']

    # 1. Must have the required keys
    if not overall_perf or not all(k in overall_perf for k in required_keys):
        _log("no required keys")
        return False

    # 2. Must have at least one non-empty patch
    num_resolved = len(overall_perf['total_resolved_ids'])
    num_unresolved = len(overall_perf['total_unresolved_ids'])
    if (num_resolved + num_unresolved) == 0:
        _log("no non-empty patch")
        return False

    # 3. If specified, total evaluated must match num_swe_issues
    if num_swe_issues:
        total_evaluated = overall_perf.get('total_submitted_instances', 0)
        if total_evaluated < num_swe_issues[0]:
            _log("not match num_issues")
            return False

    return True
