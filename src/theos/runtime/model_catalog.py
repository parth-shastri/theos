"""Model aliases and generation capabilities verified against the provider catalog."""

from pydantic import BaseModel, ConfigDict, Field

# OpenRouter model IDs and parameter support, checked on 2026-10-06.
# Keep display names separate from wire IDs so saved model choices stay readable.
MODEL_CATALOG = {
    "gpt-6-luna": ("openai/gpt-6-luna", ("seed",), 128000),
    "gpt-5.6-luna": ("openai/gpt-5.6-luna", ("seed",), 128000),
    "glm-5.3": ("z-ai/glm-5.3", ("temperature", "top_p"), 128000),
    "sonnet-5.5": ("anthropic/claude-sonnet-5.5", ("temperature",), 128000),
    "deepseek-flash-v4.1": (
        "deepseek/deepseek-v4.1-flash",
        ("temperature", "top_p", "top_k", "seed", "frequency_penalty", "presence_penalty"),
        943718,
    ),
    "gemini-3.8-flash": ("google/gemini-3.8-flash", ("temperature", "top_p", "seed"), 65536),
    "glm-5.3-flash": (
        "z-ai/glm-5.3-flash",
        ("temperature", "top_p", "top_k", "seed", "frequency_penalty", "presence_penalty"),
        943717,
    ),
    "qwen-3.8-27b": (
        "qwen/qwen3.8-27b",
        ("temperature", "top_p", "top_k", "seed", "frequency_penalty", "presence_penalty"),
        235929,
    ),
}
MODEL_CHOICES = tuple(name for name in MODEL_CATALOG if name != "gpt-6-luna")
REASONING_EFFORTS = {
    "gpt-6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
    "gpt-5.6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
    "glm-5.3": ["low", "high", "max"],
    "sonnet-5.5": ["low", "medium", "high", "xhigh", "max"],
    "deepseek-flash-v4.1": ["low", "high", "max"],
    "gemini-3.8-flash": ["low", "medium", "high"],
    "glm-5.3-flash": ["low", "high", "max"],
    "qwen-3.8-27b": ["low", "medium", "xhigh"],
}


def reasoning_choices(provider, model):
    name = next((name for name, entry in MODEL_CATALOG.items() if model in {name, entry[0]}), None)
    if name and provider in {"openrouter", "openai", "fake"}:
        return ["default", *REASONING_EFFORTS[name]]
    return ["default", "none", "low", "medium", "high"]


def fallback_reasoning(provider, model, requested):
    """Map the primary effort to an effort that the fallback model supports."""
    if provider != "openrouter":
        return requested
    supported = set(reasoning_choices(provider, model)[1:])
    if requested in supported:
        return requested
    if requested in {"default", "none", "medium"}:
        if "low" in supported:
            return "low"
        if "high" in supported:
            return "high"
    if requested in {"xhigh", "max"}:
        if "max" in supported:
            return "max"
        if "high" in supported:
            return "high"
    return requested


class GenerationConfig(BaseModel):
    """Unset fields use provider defaults. Reject unknown or invalid controls."""

    model_config = ConfigDict(extra="forbid")
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=1, le=1000, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)


def model_choices(settings):
    """Respect operator allowlists and expose the shared catalog on OpenRouter."""
    if settings.allowed_models:
        return settings.allowed_models
    choices = [settings.model]
    if settings.provider in {"openrouter", "fake"}:
        choices += MODEL_CHOICES
    elif settings.provider == "openai":
        choices += ["gpt-5.6-luna"]
    return list(dict.fromkeys(choices))


def catalog_entry(model):
    return MODEL_CATALOG.get(model) or next(
        (
            entry
            for entry in MODEL_CATALOG.values()
            if model in {entry[0], entry[0].split("/", 1)[1]}
        ),
        None,
    )


def wire_model(provider, model):
    entry = catalog_entry(model)
    return entry[0] if provider == "openrouter" and entry else model


def generation_capabilities(provider, model):
    entry = catalog_entry(model)
    fields, limit = (), 128000
    if entry and provider in {"openrouter", "fake"}:
        _, fields, limit = entry
    elif provider == "gemini":
        fields = ("temperature", "top_p", "top_k", "seed")
        limit = 65536
    # Direct OpenAI reasoning models omit sampling controls. Unknown models expose
    # only the common output limit rather than guessing their sampling contract.
    return {
        "parameters": ["max_output_tokens", *fields],
        "max_output_tokens": limit,
        "reasoning": reasoning_choices(provider, model),
    }


def validate_generation(provider, model, config):
    values = GenerationConfig.model_validate(config).model_dump(exclude_none=True)
    capabilities = generation_capabilities(provider, model)
    unsupported = values.keys() - set(capabilities["parameters"])
    if unsupported:
        raise ValueError("This model does not support: " + ", ".join(sorted(unsupported)))
    if values.get("max_output_tokens", 0) > capabilities["max_output_tokens"]:
        raise ValueError(
            f"The output token limit is {capabilities['max_output_tokens']} for this model."
        )
    return values


def generation_options(provider, model, config):
    """Map the saved UI names to each existing adapter's request fields."""
    values = validate_generation(provider, model, config)
    if provider in {"openrouter", "anthropic", "llama"}:
        if "max_output_tokens" in values:
            values["max_tokens"] = values.pop("max_output_tokens")
    if provider == "openrouter" and "top_k" in values:
        values["extra_body"] = {"top_k": values.pop("top_k")}
    return values
