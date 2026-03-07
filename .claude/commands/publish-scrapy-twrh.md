Publish scrapy-tw-rental-house to PyPI and update downstream dependencies.

Steps:

1. Ask the user to confirm:
   - The new version number (show the current version from `scrapy-tw-rental-house/pyproject.toml`)
   - Release notes / changelog summary

2. Bump the version in `scrapy-tw-rental-house/pyproject.toml`.

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
