Publish scrapy-tw-rental-house to PyPI and update downstream dependencies.

Steps:

1. Read current version from `scrapy-tw-rental-house/pyproject.toml`.
2. Suggest the next version using semver:
   - patch bump (e.g. 2.1.8 → 2.1.9) for bug fixes
   - minor bump (e.g. 2.1.8 → 2.2.0) for new features
   - major bump (e.g. 2.1.8 → 3.0.0) for breaking changes
3. Ask the user to confirm the new version number and release notes / changelog summary.

4. Bump the version in `scrapy-tw-rental-house/pyproject.toml`.

3. Build and publish:
   ```bash
   cd scrapy-tw-rental-house
   poetry build
   poetry publish
   ```

4. Update the `scrapy-tw-rental-house` dependency version in `twrh-dataset/pyproject.toml`.

5. Re-install in twrh-dataset:
   ```bash
   cd twrh-dataset
   poetry update scrapy-tw-rental-house
   ```

6. Inform the user of the completed publish and downstream update.

Do NOT commit or push automatically. Let the user decide when to stage and commit.
