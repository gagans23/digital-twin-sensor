# GitLab Publishing Guide

The repository is ready for GitLab, including README, architecture diagrams, CI, license, contribution guide, API docs, deployment docs, and research notes.

## Create The GitLab Project

Create an empty GitLab project named:

```text
digital-twin-sensor-starter
```

Recommended visibility:

- private while validating privacy/security language
- public when you are ready for external download and use

Do not initialize the GitLab project with a README, license, or `.gitignore`; this repository already contains those files.

## Add The Remote

SSH:

```bash
git remote add origin git@gitlab.com:<namespace>/digital-twin-sensor-starter.git
```

HTTPS:

```bash
git remote add origin https://gitlab.com/<namespace>/digital-twin-sensor-starter.git
```

## Push

```bash
git push -u origin main
```

## Current Local State

Current branch:

```text
main
```

Current published-ready files include:

- `README.md`
- `LICENSE`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `.gitlab-ci.yml`
- `docs/ARCHITECTURE.md`
- `docs/GETTING_STARTED.md`
- `docs/API.md`
- `docs/DEPLOYMENT.md`
- `docs/RESEARCH_AND_EVALUATION.md`
- `docs/assets/architecture.svg`
- `docs/assets/pipeline.svg`

## GitLab Project Description

Use this short description:

```text
Local-first privacy-gated digital twin sensor for personal context engineering, working spheres, and agent-ready context packs.
```

Use these topics:

```text
digital-twin, context-engineering, agent-memory, privacy, macos, local-first, kiro, codex, gitlab, x-synth
```

## Release Notes For First Tag

```bash
git tag -a v0.1.0 -m "Digital Twin Sensor v0.1.0"
git push origin v0.1.0
```

Suggested release title:

```text
Digital Twin Sensor v0.1.0
```

Suggested release summary:

```text
Initial local-first prototype with macOS foreground attention collection, pre-storage redaction, Digital Twin Signature, living context graph, working spheres, context packs, Product Ops, watchdog, pause/resume, retention purge, and professional documentation.
```

## Access Setup If Push Fails

If SSH fails:

```bash
ssh -T git@gitlab.com
```

Add your public SSH key to:

```text
GitLab -> Preferences -> SSH Keys
```

If HTTPS fails, create a GitLab personal access token with repository write access and use it through your Git credential manager.
