{% include "capabilities/skill_policy.md" %}
<installed_skill_catalog>
{{ catalog | join('\n') }}
</installed_skill_catalog>{% for skill in selected_skills %}{% if skill.content is none %}
Required skill unavailable: {{ skill.name }}. Report this limitation accurately.{% else %}
<operator_skill name='{{ skill.name }}'>
{{ skill.content }}
</operator_skill>{% endif %}{% endfor %}
