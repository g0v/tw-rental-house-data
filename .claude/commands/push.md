Push the current branch to origin and create a GitLab Merge Request using `glab`.

Steps:

1. Run `git branch --show-current` to get the current branch name.
   - If the branch is `main`, STOP and warn: "Cannot push main directly. Switch to a feature branch first." Do NOT proceed.

2. Run `git status` to confirm there are no uncommitted changes. If there are, warn the user and stop — they should commit first.

3. Push to origin:
   ```
   git push -u origin <branch>
   ```

4. Determine the merge request content from the branch's commit log:
   - Run `git log main..<branch> --oneline` to list all commits on this branch.
   - Run `git log main..<branch> --format="%s%n%b"` to get subjects and bodies.
   - Derive an MR **title**: a concise one-line summary (≤72 chars) of what the branch delivers as a whole.
   - Derive an MR **description** in this format:
     ```
     ## Summary
     - <bullet per logical change, distilled from commit log>

     ## Commits
     - <each commit oneline>
     ```

5. Create the MR with `glab`:
   ```
   glab mr create \
     --title "<mr title>" \
     --description "<mr description>" \
     --target-branch main \
     --remove-source-branch \
     --yes
   ```
   Use a heredoc or `$'...'` quoting to safely pass multi-line description.

6. Print the MR URL returned by `glab`.

Do NOT merge the MR. Do NOT force-push.
