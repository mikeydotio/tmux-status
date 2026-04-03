# AGENTS.md — Project Task Management

This project uses **storyhook** for task tracking. All agents must follow the workflow below.

## Workflow

1. **Start of session**: Load project context
   ```
   story load-context
   ```

2. **Pick next task**: Get the highest-priority ready story
   ```
   story next
   ```

3. **Work on the task**: Implement the changes for the assigned story

4. **Complete the task**: Mark the story as done
   ```
   story move <id> done
   ```

5. **End of session**: Generate a handoff summary
   ```
   story handoff --since 2h
   ```

## Quick Reference

| Action | Command |
|---|---|
| List open stories | `story list` |
| Show a story | `story show TS-<n>` |
| Create a story | `story new "<title>"` |
| Move to state | `story move TS-<n> <state>` |
| Add a comment | `story comment TS-<n> "comment text"` |
| Set priority | `story prioritize TS-<n> high` |
| Assign a story | `story assign TS-<n> <member>` |
| Add a label | `story label TS-<n> <label>` |
| Block a story | `story block TS-<n> "reason"` |
| Unblock a story | `story unblock TS-<n>` |
| Add relationship | `story relate TS-1 blocks TS-2` |
| Set multiple fields | `story set TS-<n> --priority high --state in-progress` |
| Search stories | `story search "<query>"` |
| Project summary | `story summary` |
| Context (for LLM) | `story load-context` |
| Phase progress | `story phase list` |
| Session handoff | `story handoff --since 2h` |

## Important

The `.storyhook/` directory is version-controlled project data. Do NOT add it to
`.gitignore`. It must be committed to git so that project state travels with the repository.

## MCP Server

This project uses the storyhook MCP server for native integration with AI tools.
To configure, run:
```
story mcp-config
```
