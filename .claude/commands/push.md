Push the current branch to origin and create a GitHub Pull Request using `gh`.

Steps:

1. Run `git branch --show-current` to get the current branch name.
   - If the branch is `master`, STOP and warn: "Cannot push master directly. Switch to a feature branch first." Do NOT proceed.

2. Run `git status` to confirm there are no uncommitted changes. If there are, warn the user and stop — they should commit first.

3. Push to origin:
   ```
   git push -u origin <branch>
   ```

4. Determine the pull request content from the branch's commit log:
   - Run `git log master..<branch> --oneline` to list all commits on this branch.
   - Run `git log master..<branch> --format="%s%n%b"` to get subjects and bodies.
   - Derive a PR **title**: a concise one-line summary (≤72 chars) of what the branch delivers as a whole.
   - Derive a PR **description** in this format:
     ```
     ## Summary
     - <bullet per logical change, distilled from commit log>

     ## Commits
     - <each commit oneline>
     ```

5. Create the PR with `gh`:
   ```
   gh pr create \
     --title "<pr title>" \
     --body "$(cat <<'EOF'
   <pr description>
   EOF
   )" \
     --base master
   ```

6. Print the PR URL returned by `gh`.

Do NOT merge the PR. Do NOT force-push.
