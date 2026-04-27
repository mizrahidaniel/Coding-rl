from __future__ import annotations

import random


# Each family has multiple realistic-user-style phrasings. The seed picks one,
# making prompts vary across tasks while remaining decontaminated (no reference
# to the underlying mutation).
_USER_PROMPTS = {
    "bug_injection": [
        "The {target} calculation seems off for edge cases. Can you fix it without changing the public API?",
        "Hey - {target} is returning weird values for a few inputs. Could you take a look?",
        "I'm getting wrong numbers from {target} on some test data. Mind investigating?",
        "Something's not right with {target}. Boundary indexes look broken. Please patch it.",
    ],
    "config_bug": [
        "Something is broken with {target} configuration handling. Please make it work again.",
        "We just shipped a release and {target} config option no longer takes effect. Help?",
        "{target} stopped picking up the config we pass in. Was that intentional?",
        "Reports say {target} doesn't read its config correctly. Can you investigate?",
    ],
    "feature_addition": [
        "Can you add an option to {target} so we can filter results? Keep old usage working.",
        "Could you extend {target} with the new flag we discussed? Backwards compatibility matters.",
        "Please add the optional behavior for {target}. Existing callers must keep working.",
        "We need a small enhancement on {target}. Add the optional argument and keep defaults intact.",
    ],
}


def generate_prompts(
    repo_id: str,
    family: str,
    target: str,
    seed: int = 0,
) -> tuple[str, str, str]:
    rng = random.Random(seed)
    user_template = rng.choice(_USER_PROMPTS.get(family, _USER_PROMPTS["bug_injection"]))
    user = user_template.format(target=target)

    if family == "bug_injection":
        formal = f"Fix boundary bug in {target} for repo {repo_id} without API changes."
        hidden = "Edge cases including empty input and interior indexes must match (len-1)*p/100."
    elif family == "config_bug":
        formal = f"Repair config/API key behavior in {target} for repo {repo_id}."
        hidden = "Backward-compatible config keys and defaults should still behave correctly."
    else:
        formal = f"Add small feature to {target} in repo {repo_id} while preserving backward compatibility."
        hidden = "New option should work while old calls remain valid."
    return formal, user, hidden
