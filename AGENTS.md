# Agent entry point

For requests to set up, run, or troubleshoot a user's scientific project with
Clusterlink, read [.agents/skills/clusterlink-project/SKILL.md](.agents/skills/clusterlink-project/SKILL.md).
It covers what to ask, project-local setup, bounded remote verification, and
workflow handoff. It applies to project onboarding/operation, not unrelated work.

For implementation work, consult README.md for the supported interface and
STATUS.md for evidence and limitations. Preserve the single project-bound SIF
model and no-remote-admin requirement. Leave scheduling and retries with
HTCondor/Pegasus. Do not treat recorded test hosts, paths, or budgets as permission
to reuse them in a different user's project.
