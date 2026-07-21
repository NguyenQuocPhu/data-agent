from triadic_dgm.services.convergence_runner import build_task_prompt
from triadic_dgm.agent.verifier import SemanticVerifier


def test_task_prompt_has_no_churn_word():
    assert "churn" not in build_task_prompt(["f1", "f2"]).lower()


def test_task_prompt_still_lists_features_in_order():
    p = build_task_prompt(["alpha", "beta"])
    assert "alpha, beta" in p


def test_task_prompt_still_recognised_as_business_task():
    # SemanticVerifier.__init__ only stores an openai client config (no network);
    # is_business_task is pure keyword matching.
    v = SemanticVerifier(api_key="test-key-unused")
    assert v.is_business_task(build_task_prompt(["f1"])) is True
