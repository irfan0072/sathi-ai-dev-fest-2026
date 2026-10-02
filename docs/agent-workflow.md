# Implementer workflow

Status: CLI found as `agy`; non-interactive read-only execution probe passed. Human authorized startup and project work on 2 October 2026.

## Verified `agy` interface (2 October 2026)

- Executable: `/Users/apple/.local/bin/agy`.
- `agy --help` and `agy help` succeed. `agy help agent` and `agy help models` describe listing commands; there is no separate task subcommand in top-level help.
- `--print` / `-p` accepts one non-interactive prompt and prints the response; `--prompt` is an alias.
- `--input-format` supports text or stream-json; `--output-format` supports text, json or stream-json. Text is the default.
- `--mode` supports `accept-edits` and `plan`; `--sandbox` enables terminal restrictions. Do not use the permission-bypass option.
- No working-directory flag is documented. Launch the process with the project as its working directory. `--add-dir` adds workspace directories; it is not a cwd substitute.
- No task-file flag is documented. Supply a prompt directing the agent to read the brief at `tasks/T###.md`, then its explicitly listed references.
- Task invocation: `agy --mode accept-edits --print 'Read tasks/T002.md and implement only that task. Report changed files and checks run. Do not commit or push.'`
- Initial sandboxed `agy` failed creating its own logs/crash files and binding a local port. An approved execution outside the sandbox started the interactive CLI.
- Interactive startup reports not signed in and signing in; a workspace trust prompt appeared. A read-only `--print` probe is in progress. Successful help alone does not establish task execution.

Earlier observations below refer to the unavailable `antigravity` command name, not the now-discovered `agy` alias.

## Verified environment

- Host OS: macOS (`uname -s` returned `Darwin`).
- Shell: zsh.
- Working directory: `/Applications/XAMPP/xamppfiles/htdocs/aidevfesthackathon`.
- `command -v antigravity`: no executable found on PATH.
- `antigravity --help`: exit 127, `zsh:1: command not found: antigravity`.
- `git status --short` and `git remote -v`: exit 128; this directory is not a Git repository.

## Missing capability

An installed Antigravity command-line executable accessible to this shell is required. Task input, working-directory selection, file context, non-interactive execution, output capture, and subcommands remain unverified. No flags or invocation syntax are assumed. Subcommand help cannot be inspected until the executable is available.

Once the human supplies its executable path or installs the CLI, run its top-level help, then the documented task subcommand help. Record the supported invocation here before delegation. Do not install dependencies without recording them in dependency files.

## Closest workable alternatives (require human choice)

1. If only the Antigravity desktop application is available, the human can submit each `tasks/T###.md` brief there and return the changes for Codex review and testing.
2. The human can authorize Codex to implement the same scoped briefs directly, retaining the board, diff review, tests, small commits, and development log.

## Required operating loop once unblocked

1. Confirm the task is permitted by the T+0 gate and the human's delegation go-ahead.
2. Create a brief with goal, files, source references, constraints, acceptance criteria, and exact test command.
3. Use only the CLI invocation verified from help; give it the minimal relevant context.
4. Review the full diff against the source documents. Return specific feedback for deviations.
5. Run task checks, the full suite, and linters. Never mark implementation done on unrun checks.
6. Commit one task at a time once Git is initialized. Ask before touching the public remote.
7. Log timestamp, task ID, tool, actual brief/prompt, and outcome in `docs/ai-dev-log.md`.
8. Stop for human input after two failures following feedback or for design conflicts.

No task execution method is approved or verified yet.

## Successful execution probe

`agy --print` reported the exact project cwd and successfully read `tasks/BOARD.md`; exit 0. Workspace trust was accepted for the authorized project. T002 was then delegated using the task invocation above. No model or effort override was supplied.

## T002 command-permission blocker

The headless T002 run returned: `a tool required the command permission that headless mode cannot prompt for, so it was auto-denied`. No T002 files were created. Read-only success does not prove command/edit execution. Switched to the documented `--prompt-interactive` mode for specific permission prompts; no permission bypass is used.

Host tool checks: Python 3.13.2, Node v20.20.2, npm 10.8.2, Docker Compose v5.3.1. Docker engine is unavailable at the configured socket.
