{% include "chat/base.md" %}{% if recovery_review %}
{% include "recovery/remote_review.md" %}{% endif %}{% if sandbox_enabled %}
{% include "capabilities/sandbox.md" %}{% endif %}
{{ skill_instructions }}
{% if research_enabled %}{% include "capabilities/research.md" %}{% else %}{% include "chat/normal_turn.md" %}{% endif %}{% if retrieved_memory %}
{{ retrieved_memory }}{% endif %}
{% include "shared/personality.md" %}
{% include "shared/writing.md" %}{% if telegram %}
{% include "channels/telegram.md" %}{% endif %}
