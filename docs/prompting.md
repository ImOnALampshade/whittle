# Writing for the agent

How Whittle's agent-facing text is written: the system prompt (`whittle/agent/system_prompt.md`), the skills (`whittle/agent/plugin/skills/*/SKILL.md`), the tool descriptions and schemas (`whittle/agent/tools.py`), the context notes Whittle adds to a turn, and every error or result message the agent reads. The default model is Claude Opus 5.5 (`decisions.md`, Agent process).

Points that are new or different on Opus 5.5 are marked **[5.5]**. Everything else carries over from the Opus 4.x and 5 guidance and still applies. Sources are listed at the end. Anthropic's docs were read on 2026-10-23.

## The stance

Write practices with reasons, not rules. The project's stance: there are no hard and fast rules; the prompts carry best practices so the model knows them, and also knows when to break them. Anthropic's guidance points the same way. Current models follow instructions literally and generalise from the reason behind them, so a default with its trade-off works better than a bare command, and a bare command gets applied where it does not fit.

- **Give the reason.** "Keep each `exec` step short, because it runs on Blender's main thread and cannot be interrupted" generalises to cases the sentence never names. "Keep steps short" does not.
- **Normal volume.** No CAPS, MUST, ALWAYS, NEVER, CRITICAL or "if in doubt, use X". Emphasis causes over-triggering and rigid behaviour, and an anxious prompt produces a cautious, hedging agent. The exceptions are genuine scene-safety rules, such as never blocking or reverting the user. Write those plainly too, with their reason.
- **No soft hedges on real requirements.** "Try to" and "if possible" are read as permission to skip. If something is required, say so and say why. If it is a default, call it a default and say when to depart from it.
- **Goals and checks over choreography.** Describe the outcome, the constraints and how to tell it worked. Keep numbered steps only where order matters (checkpoint before a destructive step) or the operation is fragile.
- **Positive descriptions over "don't" lists.** Say what good output looks like. Where a specific bad pattern keeps showing up, name it exactly. A generic negative ("avoid a generic look") mostly swaps one default for another. **[5.5]**
- **Context is never padding.** Who the user is, what they see (a narrow sidebar and the live viewport), what the result is for (game-ready meshes, not just a good render) and environment facts all earn their place. Generic virtues ("be accurate and thorough"), rules repeated for emphasis and strategy coaching do not.

## Opus 5.5 specifics

Anthropic says Opus 5 prompts work unchanged on Opus 5.5, so treat 5.5 as a re-test, not a rewrite. Tune only what you observe going wrong. **[5.5]** The differences that matter here:

- **Thinking is always on; effort controls it.** **[5.5]** Effort defaults to medium on 5.5 (high on Opus 5). Set it explicitly in the harness and tune it there, not with prompt text. Remove "think carefully", "step by step" and "don't overthink" lines; lowering effort reduces thinking more reliably than any wording. Thinking counts toward `max_tokens` even when it is not returned, so size that for long agentic turns (64K to 128K). Changing effort between requests invalidates the prompt cache. Whittle sets effort per chat: high by default, low or medium from the model menu (`--effort` at session start, switched on the live session when the chat's changes; `architecture.md` §15). It changes only when the user picks another level, so the cache is lost at most once per change.
- **Never ask for reasoning in the output.** **[5.5]** A prompt, skill or tool description that asks the model to write its reasoning into the reply, a `<thinking>` tag or a tool or JSON field such as `reasoning` can be declined as `reasoning_extraction`. Ask for a short plan or an outcome summary instead. Whittle's "one or two lines to the user" plan is a plan and is fine. No tool schema should have a reasoning or explanation-of-thinking field.
- **Progress notes arrive as thinking blocks.** **[5.5]** Text the model writes between tool calls comes back as progress-update thinking blocks, which are empty at the default `thinking.display`. A sidebar that shows only text blocks looks silent mid-turn. Whittle gets `display: "updates"` (beta): it sets no thinking display, so the bundled CLI requests updates itself, and the runner shows each narration block as Claude's text (`architecture.md` §5). Ordinary thinking stays omitted. The cadence itself is set in the prompt (next section), and those notes are what the user reads mid-turn, so the "Writing to the user" guidance applies to them as much as to the final reply.
- **Append-only history.** **[5.5]** Editing earlier messages, rebuilding the system prompt or tool list, or summarising old turns in place invalidates the preserved thinking blocks after that point. Freeze the system prompt and tool list from the first request of a session. Declare every tool a session might need up front, put standing paragraphs in from the start, and deliver later information as appended messages. Check resume, fork and `resume_at` against this.
- **No forced tool choice.** **[5.5]** `tool_choice` of `any` or `tool` returns a 400. Use `auto`, name the tool in the prompt ("Call it first"), and use strict schemas where inputs must be valid.
- **Human in the loop, so no anti-early-stop paragraph.** **[5.5]** In unattended loops 5.5 can end a turn with text partway through a task, and Anthropic suggests a "don't stop early" paragraph plus capped automatic continuations. It also says to leave that out where someone is watching. The Whittle user watches and steers, so a text-only end of turn is the end of the turn.
- **Settled answers in chat.** **[5.5]** Anthropic suggests telling a chat model to treat earlier answers as done, so follow-ups start faster. Whittle's turns are iterative edits where a later render can expose an earlier mistake, which is the case Anthropic says to leave it out of.
- **Better at images.** **[5.5]** 5.5 reads screenshots and dense visuals more accurately without scaffolding, so re-test visual-check instructions. Tool-backed looking still helps on dense inputs: higher-resolution renders, close-ups and cropping beat prose about looking carefully.
- **Elapsed time.** **[5.5]** 5.5 responds well to an elapsed-versus-budget line (for example `elapsed 340s / 1200s`) appended to harness messages. Advisory only; keep the hard timeout.

## Scope, verification and delegation

- **Scope.** Opus 5-family models tend to widen a task. Whittle's prompt should say: deliver the edit the sketch and prompt asked for at the scope intended; make routine modelling calls without asking; use `ask` only when different readings lead to materially different geometry; when a better approach exists, say so in a sentence and carry on with the request as given; finish the whole edit and stop short of things nobody asked for.
- **Verification.** Generic "double-check", "re-verify" and "final verification" lines cause over-verification and cost tokens with no quality gain, so leave them out. Keep checks that use real tools, because renders and `whittle.mesh_report` are the agent's only ground truth about the scene. Frame them as how to look, not as an instruction to be careful, and keep the hard cap (`$self_check_rounds`). **[5.5]** re-test whether the visual check still needs every view.
- **Subagents.** Whittle exposes only the `Skill` tool from the CLI, so the agent cannot delegate. A custom system prompt replaces the `claude_code` preset's delegation guidance, so if a Task or Agent tool is ever exposed, add a line limiting delegation to large independent tracks (never verification) and cap spawns in the harness.

## Writing to the user

The "Writing to the user" section of the system prompt sets the cadence; keep its intent. Length is controlled by explicit prompt text, not by effort. Describe the shape rather than banning narration: a line of intent before a multi-step edit, an update only when something changes the plan, and a final reply that leads with the outcome in one to three sentences. Prefer that description, or two or three short `<example>` replies, over a list of "don't"s. Avoid numeric word caps, which starve hard turns.

The prompt's own formatting leaks into replies. A prompt heavy with headings and bullets produces bullet-heavy replies; plain prose in the parts that describe replies helps keep them plain.

## The system prompt

- Open with a one-line role and the facts the agent cannot infer: what Whittle is, what the user sees, what the output is for.
- Whittle passes its own system prompt string instead of the `claude_code` preset. That is right for a non-coding agent with its own surface, but the string replaces the preset's sentence explaining system reminders, and the skill listing arrives as one. Include a sentence such as: "The application adds system reminders to this conversation. Treat them as context from the application, not as messages from the user."
- Pick one home for each fact. Per-tool details (parameters, what `exec` pre-imports, the `whittle` helpers) belong in the tool descriptions. The system prompt says when and why to reach for a tool, at the altitude of turn shape and judgement. Duplicates drift apart, and the model spends effort reconciling them.
- Resolve instructions that pull against each other (thorough checking and a brief turn, say) by stating which wins when they conflict.
- The modelling guidance keeps its substance: watertight fused meshes by default, `whittle.mesh_report`, the `fuse-parts` skill. Write it as defaults with reasons and the cases where a different choice is right (`modeling-practices.md`).

## Skills

- **Description.** Third person, key use case first, and both what the skill does and when to use it, with the words the agent will actually see in a request (stroke types such as add, carve, crease and free; prop nouns; user phrasings). Give every skill a "Use when ..." clause. The description and `when_to_use` text are truncated at 1,536 characters in the listing.
- **Body.** Assume the model knows `bpy` and Blender. Keep Whittle-specific conventions, gotchas and working code. Move long reference material into a sibling file linked one level deep. Write standing instructions, because the skill file is not re-read on later turns.
- **Degrees of freedom.** Exact code for fragile operations (bmesh spin, boolean solver settings, welding, Geometry Nodes wiring); heuristics for design choices (live or applied boolean). Give one default with an escape hatch rather than a menu.
- **Helpers over pasted code.** For repeatable operations, a `whittle.*` helper beats code the agent retypes: it is deterministic and cheaper. Say plainly whether to call a helper or read code as reference.
- **One term per concept** everywhere: target, stroke, sketch view, overlay.
- **Inline fallback.** `WHITTLE_INLINE_SKILLS` pastes every skill into the prompt and defeats load-on-demand. Keep it for testing.

## Tool descriptions and schemas

- Write each description like a short man page for a new colleague, three or four sentences or more: what it does, when to use it and when a sibling tool fits better, what each parameter means (units, world or local space), what it returns and what it does not. Keep behavioural steering and worked dialogues out.
- Enforce shapes in the schema rather than in prose: enums, minimums and maximums, required fields, mutually exclusive options. Where the schema cannot say it (exactly one of `view` or `camera`), reject the bad call with a message that shows the right one.
- Make mistakes hard (poka-yoke): validate ids, and fix footguns in the tool rather than warning about them in the prompt.
- Parallel tool calls are on by default; don't prompt for them unless batching is measurably low. Return all of a turn's tool results in one message.

## Context notes and errors

- **Mark where text came from.** **[5.5]** Wrap application context (the "Context from Whittle" notes, user amendments) in descriptive tags such as `<whittle_context>` and `<user_amendment>`, and text the user pasted from elsewhere in tags carrying a short random id. Add one system-prompt line saying instructions inside pasted content are followed only when the user's own message asks. The tags are plain text and can be imitated, so this is one layer of defence, not the only one.
- **High-signal results.** Return what the agent needs to decide its next step: for `exec`, stdout, the exception and a compact summary of what changed. Truncate long output with a note on how to get the rest.
- **Actionable errors.** Say what to change, with the valid options: `object "Body" not found; targets are: Crate, Lid`, not `KeyError`.

## Changing a prompt

Prompts are tuned against observed failures, not imagined ones. Keep a small set of representative requests (the crate bundle under `tests/fixtures` is a start), compare runs before and after a change, and cut one category at a time. Anthropic removed most of Claude Code's system prompt for Opus 5 with no measurable loss; deleting scaffolding is usually the first move, but keep anything that guards the user's scene. When an instruction is being ignored, shorten or clarify the prompt, or look for a conflicting instruction, rather than adding emphasis.

The repo's tests use the fake agent and make no API calls, so they cover the plumbing (that a context note or error is produced and shaped right) but not how the model responds to wording. Wording changes need a manual run.

## Sources

- [Prompting Claude Opus 5.5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5): effort, refusals, progress updates, unattended runs, chat thinking, pasted text, visual inputs, design defaults, time signals.
- [Prompting Claude Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5): scope and over-verification, progress updates, response length, subagents.
- [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices): context and reasons, clarity, XML tags, examples, formatting, tool usage, parallel calls, migration (append-only history).
- [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools): tool description practices, forced tool choice.
- [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) and [Claude Code skills](https://code.claude.com/docs/en/skills): descriptions, concision, degrees of freedom, scripts, evaluations.
- [Modifying system prompts (Agent SDK)](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts): custom prompt string and the system-reminder sentence.
- [The new rules of context engineering for Claude 5 generation models](https://claude.dev/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models/): cutting scaffolding, conflicting instructions, goals over rule lists.
- Anthropic engineering: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), [Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents), [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
