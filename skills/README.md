# Shared skills and report style

The Pi stores shared skills in `/home/neuron/.agents/skills`.
Theos loads a copy from `/data/skills` in its persistent data volume.
Set `AGENT_SKILLS_DIR=/data/skills` in the deployment environment.
Host skills are available to Codex and linked into the existing Claude Code skill directory.

The installed upstream skills are:

| Skill | Source |
| --- | --- |
| `code-review-excellence` | `wshobson/agents` |
| `arxiv-search` | `langchain-ai/deepagents`, `libs/code/examples/skills/arxiv-search` |
| `huggingface-papers` | `huggingface/skills` |
| `docx`, `xlsx`, `pdf` | `anthropics/skills` |

Use the [skills.sh CLI](https://skills.sh/docs) to install upstream skills.
The Pi's system Node 20 cannot run `skills@1.7.2`.
Use a temporary Node 22 runtime:

```sh
DISABLE_TELEMETRY=1 npx --yes --package=node@22 --package=skills@1.7.2 skills list --global
```

The `report-style` directory contains the operator's neutral PDF and DOCX style.
Apply it after installation or an upstream update:

```sh
python3 scripts/apply_skill_styles.py --skills-dir /home/neuron/.agents/skills
```

The script adds the shared style and updates the DOCX and PDF instructions.
It preserves upstream instructions and resources.
Copy the resulting directories into the active Theos data volume.
Use physical directories rather than symlinks inside `/data` because deployment backups reject symlinks.
Refresh the installation manifest after updates.

The arXiv CLI entrypoint needs a local correction to print its returned result.
The Pi installation records that correction and preserves upstream licenses.
The upstream installation lock and `.theos-install.json` record sources and file hashes.

Skill instructions do not install tools or grant execution permissions.
The report helpers require their declared Python packages and a separate browser installation.
DOCX rendering also requires LibreOffice and the selected fonts.
PDF page inspection requires Poppler or an equivalent renderer.
Copy report scripts and text assets into the remote sandbox before execution.
Host installation does not make these files available inside a remote sandbox.
