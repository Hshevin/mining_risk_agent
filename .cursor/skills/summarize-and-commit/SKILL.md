---
name: summarize-and-commit
description: Summarize repository changes and create a safe Git commit. Use when the user asks to summarize changes and commit, says "总结更改并提交", or wants the current work packaged into a commit.
disable-model-invocation: true
---

# Summarize And Commit

## Workflow

1. Inspect the repository state in parallel:
   - `git status --short`
   - `git diff --stat && git diff`
   - `git diff --cached --stat && git diff --cached`
   - `git log --oneline -5`
2. Review staged and unstaged changes before committing. Do not commit secrets, `.env`, credentials, runtime logs, local databases, caches, or generated build artifacts unless the user explicitly asks and the risk is acceptable.
3. Stage only relevant source, configuration, documentation, tests, lockfiles, and intentionally versioned model/data artifacts.
4. Summarize the changes in Chinese with the main user-facing and engineering impact.
5. Commit with a concise message that matches the repository style. Always pass the message through a heredoc:

```bash
git commit -m "$(cat <<'EOF'
<commit message>

EOF
)"
```

6. Run `git status --short` after the commit and report any remaining uncommitted files, especially files intentionally excluded for safety.

## Safety Checks

- Warn before committing `.env`, API keys, credential files, logs, local databases, or cache directories.
- Never use destructive Git commands unless the user explicitly requests them.
- If hooks fail because they modify files, inspect the result and create a new commit after fixing the issue.
