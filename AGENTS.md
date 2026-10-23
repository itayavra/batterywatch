# Agent notes

## Git

- Never run `git add`, `git reset`, `git restore --staged`, `git stash`, `git commit`, or any
  other command that stages, unstages, or commits changes unless the user explicitly asks.
- The user may intentionally keep changes staged as a manual backup. Do not "clean up" the
  index. Leave the staging area exactly as you found it.
- When the user asks for code changes, only modify working-tree files. Report status with
  `git status` / `git diff` (read-only) if useful, but do not alter the index.
