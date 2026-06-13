"""
Git utility functions.
Ported from dgm_agent (V1) utils/git_utils.py
"""
import os
import subprocess

try:
    import git
except ImportError:
    git = None


def get_git_commit_hash(repo_path='.'):
    """Get the current git commit hash for the repo at repo_path."""
    if git is None:
        return None
    try:
        repo = git.Repo(repo_path)
        commit_hash = repo.head.commit.hexsha
        return commit_hash
    except Exception as e:
        print("Error while getting git commit hash:", e)
        return None


def apply_patch(git_dname, patch_str):
    """Apply a patch string to the repository at `git_dname`."""
    cmd = ["git", "-C", git_dname, "apply", "--reject", "-"]
    result = subprocess.run(
        cmd,
        input=patch_str,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False
    )
    if result.returncode != 0:
        print(f"apply_patch error: Patch did not fully apply. Return code: {result.returncode}, "
              f"stdout: {result.stdout}, stderr: {result.stderr}")
    else:
        print("apply_patch successful")


def diff_versus_commit(git_dname, commit):
    """
    Take a diff of `git_dname` current contents versus the `commit`,
    including untracked files, without modifying the repository state.
    """
    # Get diff of tracked files
    diff_cmd = ["git", "-C", git_dname, "diff", commit]
    result = subprocess.run(diff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    diff_output = result.stdout.decode()

    # Get list of untracked files
    untracked_files_cmd = ["git", "-C", git_dname, "ls-files", "--others", "--exclude-standard"]
    result = subprocess.run(untracked_files_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    untracked_files = result.stdout.decode().splitlines()

    # Generate diffs for untracked files
    for file in untracked_files:
        devnull = 'NUL' if os.name == 'nt' else '/dev/null'
        diff_file_cmd = ["git", "-C", git_dname, "diff", "--no-index", devnull, file]
        result = subprocess.run(
            diff_file_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=git_dname,
            check=False
        )
        diff_file_output = result.stdout.decode('utf-8', errors='replace')
        diff_output += diff_file_output

    return diff_output


def reset_to_commit(git_dname, commit):
    """Reset the repository at `git_dname` to the given `commit`."""
    # Step 1: Hard-reset tracked files
    reset_cmd = ["git", "-C", git_dname, "reset", "--hard", commit]
    result_reset = subprocess.run(
        reset_cmd, capture_output=True, text=True, check=False
    )
    if result_reset.returncode != 0:
        print(f"reset_to_commit error: Failed to reset {git_dname} to commit '{commit}'. "
              f"STDOUT: {result_reset.stdout} STDERR: {result_reset.stderr}")
    else:
        print(f"reset_to_commit successful: {commit}")

    # Step 2: Clean untracked files and directories
    clean_cmd = ["git", "-C", git_dname, "clean", "-fd"]
    result_clean = subprocess.run(
        clean_cmd, capture_output=True, text=True, check=False
    )
    if result_clean.returncode != 0:
        print(f"reset_to_commit clean error: Failed to clean {git_dname}. "
              f"STDOUT: {result_clean.stdout} STDERR: {result_clean.stderr}")
    else:
        print(f"reset_to_commit clean successful: {commit}")


def filter_patch_by_files(patch_str, target_files):
    """
    Filters out the diff blocks related to any of the target_files in a patch string.

    Args:
        patch_str (str): The complete patch text.
        target_files (list[str]): A list of filenames for which to extract changes.

    Returns:
        str: A string containing only the diff blocks for the specified target files.
    """
    lines = patch_str.splitlines()
    filtered_lines = []
    include_block = False

    for line in lines:
        if line.startswith("diff --git"):
            include_block = any(f"a/{target}" in line and f"b/{target}" in line for target in target_files)
        if include_block:
            filtered_lines.append(line)
    return "\n".join(filtered_lines)


def remove_patch_by_files(patch_str, keyword='polyglot'):
    """
    Removes diff blocks related to files containing the keyword from a patch string.

    Args:
        patch_str (str): The complete patch text.
        keyword (str): Keyword to match in filenames for removal (default: 'polyglot').

    Returns:
        str: A string containing the patch with diff blocks for matching files removed.
    """
    lines = patch_str.splitlines()
    filtered_lines = []
    include_block = True

    for line in lines:
        if line.startswith("diff --git"):
            include_block = keyword.lower() not in line.lower()
        if include_block:
            filtered_lines.append(line)

    return "\n".join(filtered_lines)
