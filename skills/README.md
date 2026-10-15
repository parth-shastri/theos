# Shared skills and report style

The Pi stores shared skills in `/home/neuron/.agents/skills`.
Theos reads the same directory through a read-only bind mount at `/skills`.
New installations and updates appear without copying files or restarting Theos.
Set these variables in the Pi deployment environment:

```env
AGENT_SKILLS_DIR=/skills
THEOS_SHARED_SKILLS_DIR=/home/neuron/.agents/skills
```

Copy the repository's `compose.skills.yaml` into `/home/neuron/theos-deploy`.
The deployment script adds that file to release, readiness, and rollback commands.
For manual Compose commands, include it with `-f` after the release Compose file.
Host skills are available to Codex and linked into the existing Claude Code skill directory.

The installed upstream skills are:

| Skill | Source |
| --- | --- |
| `code-review-excellence` | `wshobson/agents` |
| `arxiv-search` | `langchain-ai/deepagents`, `libs/code/examples/skills/arxiv-search` |
| `pwc-cli` | `huggingface/pwc-cli`, `standalone_cli` |
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
The read-only mount exposes the result directly to Theos.
Back up the shared host directory separately from the application data volume.
Refresh the installation manifest after updates.

The arXiv CLI entrypoint needs a local correction to print its returned result.
The Pi installation records that correction and preserves upstream licenses.
The upstream installation lock and `.theos-install.json` record sources and file hashes.

Prefer `pwc-cli` for paper discovery, reading, related work, and benchmarks.
Use arXiv and Hugging Face skills for supplemental evidence.
Apply the paper policy after upstream updates:

```sh
python3 scripts/apply_paper_skill_policy.py --skills-dir /home/neuron/.agents/skills
```

The official [Papers with Code CLI](https://github.com/huggingface/pwc-cli) provides the companion command.
The Pi uses version `0.4.3` in an isolated Python environment.
Its source revision is `dba15a776f9773282fa590f42d7496f2833b5959`.
Live paper search and metadata retrieval passed from the Pi host.
The shared sandbox runtime image installs this pinned CLI in its Python environment.

Skill instructions do not grant execution permissions.
The ARM64 shared sandbox image installs the declared Python packages and command-line tools for all eight skills.
It contains the report scripts, style assets, examples, and references at `/opt/theos/report-style`.
Other skill scripts and text resources are loaded from the host and copied when the task needs them.
Build and activate the image by following [sandbox deployment](../docs/sandbox.md#shared-skill-runtime-image).
