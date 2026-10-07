# Security and publishing

Do not post suspected credentials in public issues. Use [GitHub private vulnerability reporting](https://github.com/gysahlgreene/SlopForge/security/advisories/new) if available, or contact the repository owner privately. Rotate exposed credentials before relying on file removal.

## Before committing

- Keep credentials in local environment/configuration, never workflow graphs or example files.
- Do not commit `.env`, private keys, model weights, full generated projects, or unsanitized logs.
- Replace private service URLs with placeholders and personal filesystem paths with project-relative paths.
- Preserve public model revisions, SHA-256 hashes, license notices, and validation measurements; these are provenance, not credentials.
- Scan both the working tree and Git history. Ignoring a file does not remove earlier commits.

With [Gitleaks](https://github.com/gitleaks/gitleaks) installed:

```sh
gitleaks git --redact --log-opts=--all
gitleaks dir --redact .
```

The repository config extends the default rules and narrowly excludes labeled model-integrity hashes. GitHub secret scanning and push protection are enabled. No scanner can prove that a repository has never contained sensitive information.

## October 2026 audit

The audit checked tracked files, all then-reachable Git text blobs, a Gitleaks scan of all refs, remote URL configuration, and GitHub's open secret alerts. No credentials were confirmed. Private ComfyUI addresses and personal paths were found in benchmark documentation and embedded PNG metadata and redacted from the active tree. PNG pixels were preserved; original/published hashes are recorded in `docs/media/publication-sanitization.json`. They remain visible in earlier commits and one older issue comment: ordinary cleanup does not rewrite history or revoke downloaded copies. The comment is [issue #5’s historical verification note](https://github.com/gysahlgreene/SlopForge/issues/5#issuecomment-5978193984); it exposes a private service address, not a credential.

Binary payloads, unreachable objects, external service storage, and external clones were not comprehensively inspected. Future generated artifacts need their own review before publication.
