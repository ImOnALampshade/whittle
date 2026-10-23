# Contributing to Whittle

Thanks for helping. Whittle is small and opinionated, so a short issue describing the
problem or idea before a large change saves everyone time.

## Before you start

- Read [README.md](README.md) (Development and Tests) and
  [docs/architecture.md](docs/architecture.md), the blueprint the code follows. The sidebar's
  spec is [docs/ui.md](docs/ui.md); agent-facing text (the system prompt, the skills, tool
  descriptions) follows [docs/prompting.md](docs/prompting.md).
- You need Blender 5.2 and the development venv described in the README. Whittle is
  developed on Linux x64; the scripts (`run_tests.sh`, `build.sh`, `screens.sh`) are POSIX
  shell, and `screens.sh` needs Linux with KDE's `kwin_wayland`. Windows and Apple silicon
  Macs are supported but untested: a report of what works there is a welcome
  contribution.
  You do not need an API key: the offline suite and the screenshots use a scripted fake
  agent.

## Making a change

- Keep to the style around you: plain functions, few comments that say why, the stdlib
  only outside `whittle/addon/` (bpy) and `whittle/agent/runner.py` (the SDK).
- Add or update tests with the change, and run the whole suite: `./run_tests.sh`. For a
  sidebar change, run `./screens.sh` for the affected scenarios and look at the images.
- Keep `README.md` and `docs/` in step with what you change (`docs/progress.md` lists
  what exists and the known gaps).
- New source files start with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Commit messages: an imperative subject line, then a short body saying why.

## Dependencies

Dependency changes get extra scrutiny (see Supply-chain notes in the README). Do not add
packages, bump versions or change `agent_env/requirements.lock` in a change about
something else; propose them on their own, with exact versions and hashes from PyPI
wheels only, and keep `whittle/requirements.lock` byte-identical to it.

## Anthropic's terms

Whittle authenticates with the user's own Anthropic API key only. Changes must not add a
Claude.ai login, use subscription plan credentials, collect or store Claude.ai tokens,
modify the bundled CLI, or name or style Whittle as Claude Code or an Anthropic product
(architecture §2, Authentication; decisions, Distribution).

## License

By contributing you agree that your contribution is licensed under the
GPL-3.0-or-later, the project's license ([LICENSE](LICENSE)).
