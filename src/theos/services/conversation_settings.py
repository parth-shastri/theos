"""Validate conversation settings consistently for every transport."""

import json

from theos.runtime.model_catalog import (
    generation_capabilities,
    model_choices,
    reasoning_choices,
    validate_generation,
)


def save(runtime, owner, session_id, *, model=None, reasoning=None, generation=None):
    session = runtime.db.session(owner, session_id)
    settings = runtime.settings
    if session_id in runtime.active or runtime.pending(owner, session_id):
        raise ValueError(
            "Finish this turn and its approvals before changing conversation settings."
        )
    model = model or session["model"]
    if model not in model_choices(settings):
        raise ValueError("Choose one of the available models.")
    choices = reasoning_choices(settings.provider, model)
    if reasoning is None:
        reasoning = session["reasoning"] if session["reasoning"] in choices else "default"
    if reasoning not in choices:
        raise ValueError("Choose a supported reasoning effort: " + ", ".join(choices))
    capabilities = generation_capabilities(settings.provider, model)
    if generation is None:
        generation = {
            key: value
            for key, value in json.loads(session["generation"]).items()
            if key in capabilities["parameters"]
        }
        if generation.get("max_output_tokens", 0) > capabilities["max_output_tokens"]:
            generation["max_output_tokens"] = capabilities["max_output_tokens"]
    generation = validate_generation(settings.provider, model, generation)
    runtime.db.execute(
        "UPDATE sessions SET model=?,reasoning=?,generation=? WHERE id=? AND owner=?",
        (model, reasoning, json.dumps(generation), session_id, owner),
    )
    return {"saved": True, "generation": generation}
