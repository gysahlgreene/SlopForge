# Working on SlopForge

## Objective

Build a repeatable pipeline for models, textures, materials, rigging, animation,
and engine delivery. A fresh session or developer must be able to reproduce
qualified results using the repository, without knowledge from an earlier chat.
One successful asset is evidence for that asset, not proof of pipeline reliability.

Before substantial work, read [Product contract](docs/PRODUCT_CONTRACT.md),
[Pipeline contract](docs/PIPELINE_CONTRACT.md),
[Quality contract](docs/QUALITY_CONTRACT.md), [Roadmap](ROADMAP.md), and
[Current state](CURRENT_STATE.md). Follow the product contract's document precedence;
expose and reconcile contradictions between peer contracts. AGENTS governs working
behavior, not independent product direction. User instructions take precedence.
Work on the milestone the owner chose; later work requires a dependency of its gate
or explicit user direction. Tests/validation check contracts; implementation must
satisfy them.

Before changing a generation or delivery stage, read its existing implementation
and relevant guidance in [the documentation index](docs/README.md). For generation
settings and environment requirements, consult [Quality tiers](docs/QUALITY-TIERS.md),
[ComfyUI](docs/COMFYUI.md), [Workflows](docs/WORKFLOWS.md), and
[Agent integration](docs/AGENT-INTEGRATION.md). Preserve the boundaries in
[Architecture](docs/ARCHITECTURE.md). Follow [Contributing](CONTRIBUTING.md) for
changes and public evidence.

## Picking up

1. Start at [issue #19](https://github.com/gysahlgreene/SlopForge/issues/19): each milestone's next step, the owner's open decisions, and the work ready to start. The owner chooses what comes next.
2. Read `private/README.md` in the main checkout (the first line of `git worktree list`) before live GPU runs, Unity work, or anything about a game project. It holds this machine's server, projects, characters, worktrees and past evidence. Git ignores it, so those details stay out of the repo, issues and pull requests.
3. Read [what's been explored](docs/EXPLORED.md) before trying an approach.
4. Run `git worktree list`. Carry on parked work in the worktree its issue names, and start anything else in a new worktree off `origin/main`. The main checkout and other worktrees can hold parked uncommitted work.

## Working with the owner

- **Git:** commit, push and open pull requests when the owner asks, or when an approved plan says to. Push to a branch, so `main` only changes through a merged pull request, and merge `main` into a branch to update it. Merges, branch deletions and removing a worktree happen on the owner's word. After each push, wait for the checks: GitHub's runner has no Blender or Unity, so a local pass can't catch everything.
- **GPU:** it's shared. Run jobs on it and leave the service, its nodes and weights, and its disk as they are unless the owner says otherwise.
- **Questions:** ask in plain words, with what each option costs. On a vague verdict ("rough", "off"), ask straight away what it's about, with options and a request for a screenshot, before building again.
- **Reviews:** send images and video into the chat with your tool's file sending, with exact questions, using real materials. Say what you measured and what you didn't. Let the owner call a result good.
- **Stuck:** after a few rounds with no change in the verdict, stop and offer to park it.
- **Quality:** fix the stage that caused a defect and regenerate from the brief. A generated asset stays as generated.
- **Models:** open models the owner may ship in a commercial game, on our own hardware or a service they may use, with no paid clips or 3D APIs. Read each licence at its source, including a tool's default model. Anything excluding the EU is out.
- **Public:** the repo holds what improves SlopForge. A game's characters, briefs and name stay out unless the owner says otherwise. Machine details stay in `private/`.

## Finishing a piece of work

Do these in order. It's done when a fresh session could carry on from #19 without this conversation.

1. **Verify:** run `make verify`, and say what it doesn't cover.
2. **Issue:** every piece of work has an issue, under an epic and a milestone. Create one if it doesn't. Comment what changed and the evidence. Close it only when its acceptance is met.
3. **Issue #19:** update it if a next step, an owner decision or the local-only list changed. Update the epic's status too.
4. **Status:** record verified evidence and visible gaps in `CURRENT_STATE.md`, and in its Summary if a status changed. Update `ROADMAP.md` if a milestone changed, and [the gallery](docs/SHOWCASE.md) if a result is worth showing.
5. **Explored:** add a row to [what's been explored](docs/EXPLORED.md) for each thing tried, including failures and the owner's words.
6. **Local:** record attempts in `private/<work>/LEDGER.md`, and new machine facts in `private/README.md`.
7. **Uncommitted work:** name its worktree and branch in its issue, and list it in #19.
8. **Your own memory:** save corrections and decisions there, if your tool has one. If every session needs a rule, add it to this file instead.
9. **Hand over:** repo changes only reach a fresh session once merged, so propose them in a pull request when the owner has asked for one. Otherwise, tell the owner they're waiting.

## Turn discoveries into durable fixes

When a pitfall, environment quirk, ordering requirement, fragile step, or failure
mode appears:

1. Preserve the failing inputs, seed, configuration, intermediate outputs, and
   relevant environment versions. Read existing notes and compare a qualified
   baseline before changing the approach.
2. Identify the root cause with a controlled reproduction. Change one relevant
   variable at a time; distinguish observations from hypotheses.
3. Fix the shared pipeline and every affected caller. Encode required knowledge
   in the appropriate scripts, configuration, validation, prompts, or tooling.
   Turn required manual repairs into supported pipeline steps.
4. Add a focused regression check and early validation where possible. Invalid
   prerequisites or outputs must stop with an actionable error before expensive
   downstream work or approval. Preserve failed candidates and provenance.
5. Update the relevant guide with the cause, remedy, prerequisites, and verified
   limits. Document any necessary step that cannot be automated. Keep private
   machine details and large diagnostic artifacts outside public Git.
6. Verify from the documented starting state through the affected downstream
   stages. Recheck the original failing case and fresh representative inputs.
   Record what passed and what remains unverified.

Repeated commands, similar retries without new evidence, recurring assumptions,
manual output repairs, or reliance on chat-only knowledge trigger a stop and
root-cause reassessment. Improve the repository before resuming production;
an unresolved diagnosis must leave a reproducible case and clear next check.

After two attempts without materially new evidence, stop implementation changes.
Record known facts, assumptions, what each attempt tested, and its results.
Identify the last correct and first incorrect artifacts, then instrument their
boundary. Each further attempt must eliminate a hypothesis or add evidence.

## Qualification

Keep structural validation, visual material review, deformation review, and
engine playback checks separate. Passing tests or reducing review pose ranges
does not qualify an asset's appearance or rig. Preserve review gates; publish
success evidence only for stages actually checked. State asset-specific results
and pipeline repeatability separately, with the tested conditions and limits.
Use Experimental, Provisional, and Qualified only with the scope and evidence
required by the quality contract. The three-brief/two-independent-run protocol is
provisional initial evidence; six runs do not automatically qualify a pipeline.
Unknown requirements and undefined thresholds prevent the affected readiness claim.

Run `make verify` before declaring implementation complete. Use `make verify-live`
for explicitly authorized inference checks; expose unavailable or skipped coverage.
Improve verification when it misses a discovered failure. For substantial
completion reports, state goal, root cause, changes, regression protection,
verification evidence, and remaining uncertainty. Preserve architectural boundaries
from the architecture guide and keep personal diagnostics outside public Git.

For provenance, lineage, stage reuse, resume, or invalidation changes, follow
[the SlopForge provenance skill](.agents/skills/slopforge-provenance/SKILL.md)
and run `make verify-provenance`.

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context; the glossary is `CONTEXT.md`. See `docs/agents/domain.md`.
