from __future__ import annotations


def generate_prompts(repo_id: str, family: str, target: str) -> tuple[str, str, str]:
    if family == "bug_injection":
        formal = f"Fix boundary bug in {target} for repo {repo_id} without API changes."
        user = f"The {target} calculation seems off for edge cases. Can you fix it without changing the public API?"
        hidden = "Edge cases including empty/singleton and boundary indexes must be correct."
    elif family == "config_bug":
        formal = f"Repair config/API key behavior in {target} for repo {repo_id}."
        user = f"Something is broken with {target} configuration handling. Please make it work again."
        hidden = "Backward-compatible aliases and defaults should still behave correctly."
    else:
        formal = f"Add small feature to {target} in repo {repo_id} while preserving backward compatibility."
        user = "Can you add the requested optional behavior? Keep old usage working."
        hidden = "New option should work while old calls remain valid."
    return formal, user, hidden
