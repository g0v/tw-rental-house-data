Create a git commit for all uncommitted changes using a semantic commit message.

Steps:
1. Run `git branch --show-current` to get the current branch name.
   - If the branch is `main`, STOP immediately and warn the user: "Cannot commit directly to main. Please switch to a feature branch first (e.g. git checkout -b feat/your-feature)." Do NOT proceed.
2. Run `git diff --cached` to check what has been staged.
   - If nothing is staged, STOP immediately and warn the user: "Nothing is staged. Please use `git add` to stage the changes you want to commit first." Do NOT proceed. Do NOT run `git add` yourself.
3. Run `git diff` to also understand unstaged changes for context (but do NOT stage them).
4. Run `git log --oneline -5` to understand the recent commit style of this repo
5. Analyze staged changes and determine the appropriate semantic commit type:
   - `feat`: new feature
   - `fix`: bug fix
   - `docs`: documentation only
   - `chore`: build, config, tooling, dependencies
   - `refactor`: code restructuring without behavior change
   - `style`: formatting, whitespace
   - `test`: adding or updating tests
6. Write a concise semantic commit message in the format: `type(optional-scope): short description`
   - Keep the subject line under 72 characters
   - Focus on "why", not just "what"
8. Commit using a heredoc to preserve formatting
9. Show the resulting commit with `git log --oneline -1`

Do NOT push. Do NOT amend existing commits.
