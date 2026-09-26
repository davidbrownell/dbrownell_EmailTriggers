---
type: Change
title: Renamed CLAUDE.md to AGENTS.md
description: Moved agent instructions from the Claude-specific CLAUDE.md to the vendor-neutral AGENTS.md and updated the Python development guidance to version 0.8.0.
tags:
  - config
  - agents
generated:
  by: claude-opus-5-5/prepare-pr
  at: 2026-09-26T18:10:22-04:00
status: stable
---

# Summary
- Replaced `CLAUDE.md` with `AGENTS.md`.
- Updated the embedded version marker from `0.6.0` to `python_development Version: 0.8.0`.
- Clarified "SOLID" as "SOLID design principles".
- Added a `General` section under Python Development requiring `python`-related tasks to run via `uv`.

# Rationale
`AGENTS.md` is a tool-agnostic convention recognized by multiple coding agents, so the instructions no longer depend on a single vendor's filename. The `uv` guidance ensures agents run Python tasks within the project's managed environment.
