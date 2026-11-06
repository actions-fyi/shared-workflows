# shared-workflows

The reusable workflows (`on: workflow_call`) of the actions-fyi organization. Other repositories call
them by full path and release tag:

```yaml
uses: actions-fyi/shared-workflows/.github/workflows/_actions-lock.yml@v1.0.0
```

The callers are:

- the org ruleset's entry points in [`actions-fyi/ruleset-workflows`](https://github.com/actions-fyi/ruleset-workflows), for pull requests and merge groups;
- the thin push callers that [`actions-fyi/.github`](https://github.com/actions-fyi/.github) distributes;
- this repository's own workflows, which call their siblings with `$/` (see below).

## Conventions

- **The `_` prefix marks a shared workflow.** It's only ever called with `workflow_call`, never
  started by an event or a ruleset. Files without the prefix are this repository's own callers and
  tests.
- Every workflow starts with `permissions: {}`. Each job declares only what it needs, with a
  `# reason` comment on each permission. Every job with steps runs `step-security/harden-runner`
  first.
- Header comments explain why a workflow is built the way it is.
- Actions are referenced by tag, e.g. `actions/checkout@v7.0.1`. `.github/workflows/actions.lock`,
  made by [`gh actions-lock`](https://gh.io/actions-lockfile), pins them to commits. Never edit it
  by hand: run `gh actions-lock` and commit the result.

### `$/` and full references

Inside this repository, workflows call their siblings with `$/`, the same-repository syntax of
workflow lockfiles, which takes no ref:

```yaml
uses: $/.github/workflows/_screen.yml
```

That covers shared workflows calling each other, e.g. `_actions-lock.yml` calling `_explain.yml`,
which calls `_screen.yml`, and this repository's own callers. GitHub's docs say `$/` resolves to the
repository of the file it appears in.

**Ruleset workflows must use full references.** In an org ruleset run, GitHub turns `$/` into `./`,
relative to the *target* repository, where the shared workflow doesn't exist. The run then fails
with:

```text
error parsing called workflow "required/<id>/.github/workflows/metadata.yml"
-> "./.github/workflows/_screen.yml": failed to fetch workflow: workflow was not found
```

That's why these workflows moved here from `actions-fyi/ruleset-workflows`. Callers in other
repositories use `actions-fyi/shared-workflows/.github/workflows/<file>@vX.Y.Z`.

> [!WARNING]
> **Unverified:** whether `$/` *inside* a shared workflow, e.g. `_actions-lock.yml` calling
> `$/.github/workflows/_explain.yml`, still resolves to this repository when a ruleset workflow
> calls it cross-repository. The first consumer run verifies it. If it fails the same way, the
> sibling calls must become full references with a tag, which a release can only point at an
> earlier release.

## Catalog

A calling job can't grant a called job more than it has itself. It must grant the union of what the
called jobs declare, or the call fails before anything runs. Grant permissions on the calling job,
not at the top of the caller.

### `_actions-lock.yml`: Check Actions Lockfile

Checks that `.github/workflows/actions.lock` matches the workflows and that every pin still verifies
upstream. Repositories without a lockfile aren't onboarded, and the check passes.

| Event | Behaviour |
| --- | --- |
| `pull_request` | Checks when the pull request changes a workflow or action file. When the check fails on a branch of the same repository, the fix job commits the regenerated lockfile, and Claude explains the findings in one comment. |
| `merge_group` | Checks the merged result when the group changes a workflow or action file. |
| `push` | Checks when the pushed commits (`before...after`) change a workflow or action file, and checks everything when the push creates the branch. |
| `schedule`, `workflow_dispatch` | Always checks, for upstream drift: moved tags and vanished pins show up without any file change. |

Outside pull requests, a failed check only fails the run: no fix, no comment. Reporting failures as
issues is planned with a rework of `_explain.yml`.

- **Permissions:** `contents: read`, `id-token: write`, `pull-requests: write`.
- **Secrets:** `CLAUDE_CODE_OAUTH_TOKEN` (required).
- **Inputs:** none.
- **Caller name:** the caller's workflow name is what a ruleset shows, and it names the fix commit's
  trailer (`Lockfile-Fixed-By: <name>`), so keep it `Check Actions Lockfile`.

```yaml
name: Check Actions Lockfile
on:
  pull_request:
  merge_group:
  push:
    branches: [main]
  schedule:
    - cron: "43 2 * * 3"
  workflow_dispatch:

permissions: {}

jobs:
  actions-lock:
    name: Actions Lockfile
    permissions:
      contents: read # Compare the changes, read the workflows, check out the pull request
      id-token: write # Exchange the fix job's OIDC token with Octo STS
      pull-requests: write # Create or update the explanation comment
    uses: actions-fyi/shared-workflows/.github/workflows/_actions-lock.yml@vX.Y.Z
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

### `_zizmor.yml`: Audit

Audits the workflows with [zizmor](https://docs.zizmor.sh/) (pedantic persona) and uploads the
results to code scanning. Runs on any event; use `pull_request`, `merge_group` and `push` to the
default branch.

- **Permissions:** `security-events: write`, `contents: read`, `actions: read`.
- **Secrets, inputs:** none.
- **Known caveat:** code scanning keys an analysis on the workflow path and the job, which come from
  the caller. If pull requests run through one caller (the ruleset's) and pushes through another
  (the one from `actions-fyi/.github`), pull requests can show "no analysis on the base branch".
  Where possible, use the same caller file name, `zizmor.yml`, and job id, `zizmor`.

```yaml
name: Audit
on:
  pull_request:
  merge_group:
  push:
    branches: [main]

permissions: {}

jobs:
  zizmor:
    name: zizmor
    permissions:
      security-events: write # Upload the SARIF results to code scanning
      contents: read # Check out the repository
      actions: read # Let upload-sarif read the workflow run
    uses: actions-fyi/shared-workflows/.github/workflows/_zizmor.yml@vX.Y.Z
```

### `_renovate.yml`: Validate

Validates the Renovate configs in strict mode, and checks that each one sets the schema and extends
the org preset `github>actions-fyi/.github`. On pull requests from a branch of the same repository,
it suggests the missing lines as a review suggestion or comment. Runs on any event; the suggestion
only on `pull_request`.

- **Permissions:** `contents: read`, `pull-requests: write`.
- **Secrets, inputs:** none.

```yaml
name: Validate
on:
  pull_request:
  merge_group:
  push:
    branches: [main]

permissions: {}

jobs:
  renovate:
    name: Renovate
    permissions:
      contents: read # Read the Renovate configs
      pull-requests: write # Review permission, and post the suggestions on pull requests
    uses: actions-fyi/shared-workflows/.github/workflows/_renovate.yml@vX.Y.Z
```

### `_explain.yml`: Explain Results

Called by other shared workflows, e.g. `_actions-lock.yml`, rather than by consumers directly.
Claude reads the results of a failed check, uploaded as an artifact earlier in the same run, and
returns a title and a body. On a pull request, it posts the body as one comment, found by a marker
and updated by later runs. The text passes `_screen.yml` before it is posted or returned.

- **Permissions:** `contents: read`, `pull-requests: write`.
- **Secrets:** `CLAUDE_CODE_OAUTH_TOKEN` (required).
- **Inputs:** `prompt`, `results`, `marker` (required); `model`, `allowed-bots`, `screen-context`.
- **Outputs:** `title`, `body`; only use them when the call succeeded.

```yaml
  comment:
    permissions:
      contents: read # Check out the pull request, so Claude can read it
      pull-requests: write # Create or update the explanation comment
    uses: actions-fyi/shared-workflows/.github/workflows/_explain.yml@vX.Y.Z
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    with:
      results: my-check-results
      marker: "<!-- my-check-explanation -->"
      prompt: The check failed; the results directory holds ...
```

### `_screen.yml`: Screen Text

Called before anything Claude wrote is posted or returned. Fails closed unless the text is judged
free of secrets: first a deterministic check for the Claude token in common encodings and the
shapes of common credentials, then Claude Haiku without tools. Never prints the text.

- **Permissions:** `contents: read`.
- **Secrets:** `CLAUDE_CODE_OAUTH_TOKEN` (required; also the token the check looks for).
- **Inputs:** `text`, `context` (required).

```yaml
  screen:
    permissions:
      contents: read # Check out the default branch, which claude-code-action needs on pull requests
    uses: actions-fyi/shared-workflows/.github/workflows/_screen.yml@vX.Y.Z
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    with:
      text: ${{ needs.write.outputs.text }}
      context: What the text is, and what may legitimately appear in it.
```

## This repository's own workflows

The org ruleset doesn't run here, so this repository calls its shared workflows itself, with `$/`,
on `pull_request`, `merge_group` and `push` to `main`:

| Caller | Calls | Extra triggers |
| --- | --- | --- |
| `actions-lock.yml` (Check Actions Lockfile) | `_actions-lock.yml` | weekly `schedule`, `workflow_dispatch` |
| `zizmor.yml` (Audit) | `_zizmor.yml` | |
| `renovate.yml` (Validate) | `_renovate.yml` | |
| `test.yml` (Test) | `_screen.yml`, `_explain.yml` | `workflow_dispatch`; no `push` |

`test.yml` tests the lower-level workflows:

- **Screen Check** runs the deterministic "Check for Secrets" step of `_screen.yml`, read from the
  workflow file, against [`tests/screen_check.py`](tests/screen_check.py): dummy tokens raw,
  reversed, split, in base64 and base64url at each byte offset, hex and URL-encoded; fake
  credentials; clean text. It asserts pass or fail per case, and that no output holds the text. The
  blocking cases are tested offline because a failed call of a reusable workflow fails the run.
- **Screen** calls `_screen.yml` with a harmless text, which must pass.
- **Explain** calls `_explain.yml` with a synthetic results artifact on pull requests from this
  repository, and checks that it returned a title and a body. It posts or updates one test comment
  per pull request, marked `<!-- shared-workflows-explain-test -->`.

The ruleset's other checks, actionlint, Claude Review and Check Metadata, aren't migrated here and
don't run on this repository.

Run the offline test locally with `python3 tests/screen_check.py`.

## Releases

Releases are **immutable** (the repository setting "Enable release immutability" must be on): once
published, a release's tag can't be moved or deleted, so a caller pinned to `@vX.Y.Z` always runs
the same code.

1. A workflow, or a maintainer, creates a **draft** release targeting an exact commit SHA on `main`,
   e.g. `gh release create vX.Y.Z --draft --target <sha> --generate-notes`. A draft creates no tag.
2. A person reviews the draft and publishes it. Publishing creates the tag at that commit.

So no workflow needs the right to create tags. Use semantic versions: a breaking change to inputs,
secrets, required permissions or behaviour is a new major version.

## Octo STS

The fix job of `_actions-lock.yml` commits with a short-lived token from
[Octo STS](https://github.com/octo-sts), granted by org-level trust policies in
`.github/chainguard/` of `actions-fyi/.github`. The token's `job_workflow_ref` names this file, not
the caller:

| Where | `job_workflow_ref` | Identity |
| --- | --- | --- |
| Consumers | `actions-fyi/shared-workflows/.github/workflows/_actions-lock.yml@refs/tags/vX.Y.Z` | `actions-lock` |
| This repository's pull requests | `actions-fyi/shared-workflows/.github/workflows/_actions-lock.yml@refs/pull/<n>/merge` | `actions-lock.shared` |

The policies must accept these refs **before** a consumer switches to the shared workflow, or the
fix job gets no token and only reports the failure.

A consumer that pins this repository by commit SHA instead of tag gets `@<sha>` as its
`job_workflow_ref`, which the tag policy doesn't accept. Reference releases by tag; the releases are
immutable.
