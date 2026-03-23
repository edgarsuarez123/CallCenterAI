# Project Skills Manifest

This project uses Claude project-local skills under `.claude/skills/`.

## Installed Skill Packages

- `api-design-reviewer` - API design and contract quality checks.
- `database-schema-designer` - schema design and migration planning.
- `env-secrets-manager` - environment variable and secret handling.
- `senior-frontend` - React/Next.js/TypeScript frontend guidance.
- `playwright-pro` - Playwright testing toolkit and templates.
- `create-skill` - local skill-authoring helper package.
- `skill-creator` - official Anthropic skill creator package.

## Playwright-Pro Subskills

- `playwright-pro/skills/browserstack`
- `playwright-pro/skills/coverage`
- `playwright-pro/skills/fix`
- `playwright-pro/skills/generate`
- `playwright-pro/skills/init`
- `playwright-pro/skills/migrate`
- `playwright-pro/skills/report`
- `playwright-pro/skills/review`
- `playwright-pro/skills/testrail`

## Notes

- Claude Code discovers these as project skills from `.claude/skills/<skill-name>/SKILL.md`.
- Keep each skill in its own directory with a `SKILL.md` at the skill root.
- `skill-creator` is also mirrored in the project root at `skill-creator/` for direct access.
