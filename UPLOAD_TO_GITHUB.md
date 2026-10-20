# Upload Celluloid through the GitHub website

This archive contains the complete repository source: web app, LibreOffice
bridge, Linux/macOS/Windows setup launchers, docs, CI and Vercel configuration.
You do not need to install anything or build the app before uploading its source.

## Extract first

**GitHub does not unpack an uploaded ZIP into repository files.** Extract the
ZIP on your computer and open its `celluloid` folder. Upload the **contents** of
that folder, not the ZIP and not the enclosing `celluloid` folder.

On a Mac, press **Command + Shift + .** in Finder to show hidden files before
selecting the contents. Include `.github`, `.gitignore`, `.gitattributes`,
`.editorconfig` and `.prettierignore` along with the visible files/folders.
On Windows, use **Extract All** first; enable hidden items in File Explorer if
any dotfiles are hidden.

## Upload

1. Create a repository in your GitHub account with your chosen name/visibility,
   or open the root of the intended repository. For a new repository, this bundle
   already includes its README and license.
2. Choose **Add file → Upload files**. An empty repository may show an
   **uploading an existing file** link instead.
3. Drag all the extracted folder's contents onto the upload area. Wait for the
   upload list to finish. Do not include `node_modules`, `.git` or an old source
   ZIP; these are not in the supplied bundle.
4. Check that files such as `README.md`, `package.json`, `package-lock.json`,
   `vercel.json` and `setup_celluloid.py` appear directly at the repository root.
   They must not be nested under an extra `celluloid/` directory.
5. Check that the upload includes `.github/workflows/ci.yml` and the other
   dotfiles. If your browser omits a hidden path, add it using GitHub's
   **Add file → Create new file** with its exact path/content, or use the Git
   commands in [the release guide](docs/RELEASING.md).
6. Enter a commit message such as `Initial Celluloid release` and commit/propose
   the changes as GitHub offers for your chosen branch.

GitHub's [upload documentation](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
allows up to 100 files per upload and 25 MiB per file. This release fits both
limits. The package check verifies that the archive matches the source and
excludes credentials, hosting identity, local recordings and dependencies.

## Check and deploy

After committing, the repository root should resemble:

```text
.github/
backend/
dist/
docs/
native/
scripts/
tests/
README.md
UPLOAD_TO_GITHUB.md
LICENSE
package.json
package-lock.json
vercel.json
setup_celluloid.py
setup.sh
setup.cmd
...dotfiles and remaining project documents
```

Open the repository's **Actions** tab to see its checks.

To run locally, use `bash setup.sh` on Linux/macOS or `.\setup.cmd` on
Windows. Prerequisites and permissions are covered in [the setup guide](docs/SETUP.md).
