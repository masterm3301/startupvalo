# Agent Teams — Master Reference Guide

Source: https://code.claude.com/docs/en/agent-teams
Requires: Claude Code v2.1.32+, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`

---

## What Agent Teams Are

A team consists of:
- **Team lead** — the main Claude Code session that creates the team, spawns teammates, and coordinates work
- **Teammates** — separate, fully independent Claude Code instances, each with its own context window
- **Shared task list** — work items that teammates claim and complete; supports dependencies and file-locking to prevent race conditions
- **Mailbox** — messaging system for direct agent-to-agent communication

Unlike subagents (which only report back to the caller), teammates can message each other directly and self-coordinate through the shared task list.

---

## Enable Agent Teams

Set in `.claude/settings.local.json` (project-local, gitignored):

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

---

## Subagents vs. Agent Teams — When to Use Which

| | Subagents | Agent Teams |
|---|---|---|
| **Context** | Own context; results return to caller | Own context; fully independent |
| **Communication** | Report results back to main agent only | Teammates message each other directly |
| **Coordination** | Main agent manages all work | Shared task list with self-coordination |
| **Best for** | Focused tasks where only the result matters | Complex work requiring discussion and collaboration |
| **Token cost** | Lower — results summarized back | Higher — each teammate is a separate Claude instance |

**Use subagents** when you need quick, focused workers that report back.  
**Use agent teams** when teammates need to share findings, challenge each other, and coordinate on their own.

---

## Best Use Cases

- **Research and review** — multiple teammates investigate different aspects simultaneously, then share and challenge findings
- **New modules or features** — teammates each own a separate piece without file conflicts
- **Debugging with competing hypotheses** — teammates test different theories in parallel and converge faster
- **Cross-layer coordination** — changes spanning frontend, backend, and tests, each owned by a different teammate

**Avoid agent teams for**: sequential tasks, same-file edits, or work with many interdependencies. Use a single session or subagents instead.

---

## Starting a Team

Tell Claude what you want in natural language. Claude creates the team, spawns teammates, and coordinates work:

```
I'm designing a CLI tool that helps developers track TODO comments across
their codebase. Create an agent team to explore this from different angles: one
teammate on UX, one on technical architecture, one playing devil's advocate.
```

Claude may also *propose* a team if it determines parallel work would help. You must confirm before it proceeds.

---

## Controlling the Team

### Display Modes

| Mode | How it works | Requirement |
|---|---|---|
| `in-process` (default) | All teammates run inside your main terminal. Shift+Down cycles through them. | Any terminal |
| `tmux` / split panes | Each teammate gets its own pane, all visible at once | tmux or iTerm2 + `it2` CLI |

Default is `"auto"` — uses split panes if already inside a tmux session, in-process otherwise.

Override in `~/.claude/settings.json`:
```json
{ "teammateMode": "in-process" }
```

Or per-session:
```bash
claude --teammate-mode in-process
```

**Keyboard shortcuts (in-process mode):**
- `Shift+Down` — cycle through teammates (wraps back to lead after the last one)
- `Enter` — view a teammate's session
- `Escape` — interrupt their current turn
- `Ctrl+T` — toggle the task list

### Specifying Teammates and Models

```
Create a team with 4 teammates to refactor these modules in parallel.
Use Sonnet for each teammate.
```

### Requiring Plan Approval Before Implementation

```
Spawn an architect teammate to refactor the authentication module.
Require plan approval before they make any changes.
```

The teammate works read-only until the lead approves. If rejected, the teammate revises and resubmits. The lead approves autonomously — shape its judgment in the prompt: `"only approve plans that include test coverage"`.

### Assigning and Claiming Tasks

- **Lead assigns**: tell the lead which task to give which teammate
- **Self-claim**: after finishing a task, a teammate picks up the next unassigned, unblocked task automatically
- Dependencies are resolved automatically — blocked tasks unblock when their dependencies complete
- File locking prevents race conditions when multiple teammates try to claim the same task

### Messaging Teammates Directly

Every teammate is a full Claude Code session. Message any teammate directly:

- **In-process**: Shift+Down to cycle, then type
- **Split-pane**: click into the pane

The lead gets idle notifications automatically when a teammate finishes.

### Shutting Down Teammates

```
Ask the researcher teammate to shut down
```

The lead sends a shutdown request. The teammate can approve (exit gracefully) or reject with an explanation.

### Cleaning Up the Team

Always use the **lead** to clean up — never a teammate:

```
Clean up the team
```

This removes shared team resources. Fails if any teammates are still running — shut them down first.

---

## Using Subagent Definitions for Teammates

Define a role once (e.g., `security-reviewer`, `test-runner`) and reuse it as both a subagent and a teammate:

```
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

- The teammate honors the definition's `tools` allowlist and `model`
- The definition body is **appended** to the teammate's system prompt (not replacing it)
- Team coordination tools (`SendMessage`, task tools) are always available regardless of `tools` restrictions
- `skills` and `mcpServers` frontmatter fields are **not** applied when running as a teammate — those load from project/user settings instead

---

## Enforcing Quality with Hooks

| Hook | When it fires | How to use |
|---|---|---|
| `TeammateIdle` | When a teammate is about to go idle | Exit code 2 to send feedback and keep them working |
| `TaskCreated` | When a task is being created | Exit code 2 to block creation and send feedback |
| `TaskCompleted` | When a task is being marked complete | Exit code 2 to block completion and send feedback |

---

## Architecture Details

### File Storage

| Resource | Path |
|---|---|
| Team config | `~/.claude/teams/{team-name}/config.json` |
| Task list | `~/.claude/tasks/{team-name}/` |

**Do not edit `config.json` by hand** — it holds runtime state (session IDs, tmux pane IDs) and is overwritten on every state update. There is no project-level equivalent; `.claude/teams/teams.json` in your project directory is treated as an ordinary file.

### Context Each Teammate Receives

On spawn, a teammate gets:
- Project context: `CLAUDE.md`, MCP servers, skills
- The spawn prompt from the lead
- **Not** the lead's conversation history

Teammates message each other by name. The lead assigns names at spawn time — specify them in your prompt for predictable references later.

### Permissions

- Teammates start with the lead's permission settings
- If lead uses `--dangerously-skip-permissions`, all teammates do too
- You can change individual teammate modes **after** spawning, but not at spawn time

---

## Best Practices

### Give Teammates Enough Context at Spawn Time

```
Spawn a security reviewer teammate with the prompt: "Review the authentication module
at src/auth/ for security vulnerabilities. Focus on token handling, session
management, and input validation. The app uses JWT tokens stored in httpOnly
cookies. Report any issues with severity ratings."
```

Teammates don't inherit the lead's conversation history — put everything task-specific in the spawn prompt.

### Team Size

- **Start with 3–5 teammates** for most workflows
- **5–6 tasks per teammate** keeps everyone productive without excessive context switching
- Token costs scale linearly — each teammate is a separate Claude instance
- Coordination overhead increases with team size
- Three focused teammates often outperform five scattered ones

### Task Sizing

| Size | Problem |
|---|---|
| Too small | Coordination overhead exceeds the benefit |
| Too large | Teammates work too long without check-ins; wasted effort risk |
| Just right | Self-contained unit with a clear deliverable (a function, a test file, a review) |

The lead breaks work into tasks automatically. If it isn't creating enough tasks: `"Split the work into smaller pieces."` If it starts implementing itself instead of waiting: `"Wait for your teammates to complete their tasks before proceeding."`

### Avoid File Conflicts

Two teammates editing the same file leads to overwrites. Structure work so each teammate owns a different set of files.

### Monitor and Steer

Check in on teammates' progress, redirect approaches that aren't working, synthesize findings as they come in. Don't let a team run unattended too long.

### Start With Research and Review

If new to agent teams, begin with tasks that have clear boundaries and don't require writing code: reviewing a PR, researching a library, investigating a bug.

---

## Proven Prompt Patterns

### Parallel Code Review with Specialized Roles

```
Create an agent team to review PR #142. Spawn three reviewers:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```

### Competing Hypotheses for Debugging

```
Users report the app exits after one message instead of staying connected.
Spawn 5 agent teammates to investigate different hypotheses. Have them talk to
each other to try to disprove each other's theories, like a scientific
debate. Update the findings doc with whatever consensus emerges.
```

The debate structure prevents anchoring: the theory that survives adversarial scrutiny is much more likely to be the actual root cause.

### Multi-Angle Exploration

```
I'm designing [thing]. Create an agent team to explore this from different angles:
one teammate on UX, one on technical architecture, one playing devil's advocate.
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Teammates not appearing (in-process) | Press Shift+Down — they may already be running |
| Teammates not appearing (split panes) | Run `which tmux`; install if missing |
| Too many permission prompts | Pre-approve common operations in permission settings before spawning |
| Teammate stops on error | Give direct instructions via Shift+Down, or spawn a replacement |
| Lead shuts down before work is done | Tell it to keep going or wait for teammates |
| Orphaned tmux session | `tmux ls` then `tmux kill-session -t <session-name>` |
| Task appears stuck | Check if work is actually done; update status manually or tell lead to nudge teammate |

---

## Known Limitations (Experimental)

- **No session resumption for in-process teammates** — `/resume` and `/rewind` don't restore them; spawn new ones after resuming
- **Task status can lag** — teammates sometimes fail to mark tasks complete, blocking dependents; fix manually or have lead nudge the teammate
- **Slow shutdown** — teammates finish current request/tool call before exiting
- **One team per session** — clean up before starting a new one
- **No nested teams** — teammates cannot spawn their own teams; only the lead can
- **Lead is fixed** — can't promote a teammate to lead or transfer leadership
- **Split panes unsupported in**: VS Code integrated terminal, Windows Terminal, Ghostty

---

## CLAUDE.md Works Normally

Teammates read `CLAUDE.md` from their working directory. Use this to provide project-specific guidance to all teammates automatically — no extra spawn-prompt setup needed.
