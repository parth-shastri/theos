"""Render versioned package prompts without storing request data in shared state.

    packaged .md + plain context -> cached template -> request text

Only trusted package files are template sources. Inserted text is rendered once.
"""

from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined
from jinja2 import meta as template_meta


@cache
def _environment(package: str) -> Environment:
    # Production files change with releases. Cache templates, never rendered user data.
    return Environment(
        loader=PackageLoader(package, "prompts"),
        undefined=StrictUndefined,
        autoescape=False,
        auto_reload=False,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=False,
    )


@cache
def prompt_names(package: str) -> frozenset[str]:
    return frozenset(_environment(package).list_templates(extensions=("md",)))


def render_prompt(package: str, name: str, **context) -> str:
    """Render a trusted Markdown template with request-local values."""
    return _environment(package).get_template(name).render(**context)


@cache
def validate_prompts(package: str) -> None:
    """Compile package templates and check static includes before serving turns."""
    environment = _environment(package)
    for name in prompt_names(package):
        source, _, _ = environment.loader.get_source(environment, name)
        parsed = environment.parse(source)
        for reference in template_meta.find_referenced_templates(parsed):
            if reference is not None:
                environment.get_template(reference)
        environment.get_template(name)
