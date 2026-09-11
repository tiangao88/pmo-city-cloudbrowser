# Mac development and Linux qualification

Workflow accepted by Tigo on 2026-09-11: edit on the Mac, qualify an exact
committed revision in a separate persistent Linux checkout on mother01.

M1 is implemented on `feat/m1-owner-continuity`. Its storage/grant compatibility
and operator recovery constraints are in [M1-MIGRATION.md](M1-MIGRATION.md).
Do not use either development checkout to migrate live profiles or grants.

## Workspace ownership

- The active Mac checkout is `pmo-city-cloudbrowser-dev` under the local PMO City
  project. It is a standalone clone with its own `.git` directory. The earlier
  `pmo-city-cloudbrowser` review worktree remains a preserved snapshot, not the
  active editing location; it depended on a temporary Git directory.
- The Linux test checkout is `/opt/data/cloudbrowser-codex/repository` in
  `hermes-agent-gf68z1riv5f082shjcusvosw`, Coolify project `pmo-city`, environment
  `development`, on mother01. `/opt/data` is a persistent Docker volume.
- The original Hermes workspace `/opt/data/pmo-city-cloudbrowser-work` remains
  owned by the previous agent. It is used only to reproduce the handoff baseline.
- The Linux test checkout has an independent `.git` and `.venv`, uses detached
  candidate commits, and disables origin pushes (`remote.origin.pushurl=DISABLED`).
  Develop and commit on the Mac; Linux is a qualification target.

This initial arrangement isolates working files and Python environments, not
processes or secrets: both checkouts share the Hermes container, its resource
limits and inherited environment. Tests must continue using their synthetic
fixtures and disposable profiles. A dedicated test container with an explicit
environment and no production secret mounts is the longer-term target before
untrusted changes or heavier concurrent testing. No live CloudBrowser container
is a development workspace.

## Access and test tools

Use the configured SSH alias, disabling its interactive tunnel forwarding for
automation (local ports may already be occupied):

```bash
ssh -o ClearAllForwardings=yes -o BatchMode=yes mother01 hostname
```

Execute Git/test commands as container user `hermes`, never by globally
disabling Git ownership checks. Python/uv and the qualification Chromium already
exist there. A copy of mother01's Docker Compose v5.5.0 executable is retained at
`/opt/data/cloudbrowser-codex/bin/docker-compose`. It is used only for local
manifest rendering by the tests; no Compose up/down command is needed.

The tool copy is outside the repository and is persistent across container
recreation. Recheck architecture/version if the development image changes.

## Transfer a candidate without publishing a branch

1. Finish and locally commit the candidate on a feature branch. Verify the
   working tree is clean and record its full SHA and the common baseline SHA.
2. Create a Git bundle containing only the baseline-to-candidate revision range
   in a newly allocated local temporary directory. `git bundle verify` must pass.
   Git bundles transport committed Git objects, not `.env`, `.venv`, profiles or
   untracked work. Review the commit contents before transport.
3. Allocate a unique `/tmp/cloudbrowser-transfer.XXXXXX` directory on mother01,
   transfer the bundle there, then copy it into `/opt/data/cloudbrowser-codex/`.
   Give the transferred bundle to container user `hermes` so it can be read.
4. Check the test checkout is clean and idle. Fetch the bundle's feature-branch
   ref and switch to the recorded SHA in detached mode. Never overwrite a dirty
   test checkout or update it while tests are running. Verify the resulting SHA.
5. Run `uv sync --dev` in the test checkout; it uses that checkout's `.venv`.
6. Run the gates below, retain their result/skip reasons and exact candidate SHA,
   and recheck that the candidate and original Hermes worktrees remain clean.

The initial transported candidate was `3eb071a8eb4a0914169e386b777ab99e2d2fdbc7`,
based on `430a06603e8dff9531cc14042a01e38fff2b8874`. Branch publication, merging,
image building and deployment are later actions with their own scope/evidence.

## Linux verification commands

```bash
ssh -o ClearAllForwardings=yes -o BatchMode=yes mother01 \
  'docker exec --user hermes -w /opt/data/cloudbrowser-codex/repository hermes-agent-gf68z1riv5f082shjcusvosw env PATH=/opt/data/cloudbrowser-codex/bin:/usr/local/bin:/usr/bin:/bin uv run make check'

ssh -o ClearAllForwardings=yes -o BatchMode=yes mother01 \
  'docker exec --user hermes -w /opt/data/cloudbrowser-codex/repository hermes-agent-gf68z1riv5f082shjcusvosw uv run make cloudfiles-boundary'

ssh -o ClearAllForwardings=yes -o BatchMode=yes mother01 \
  'docker exec --user hermes -w /opt/data/cloudbrowser-codex/repository hermes-agent-gf68z1riv5f082shjcusvosw uv run python -m compileall -q src tests'
```

Use the short documentation/contract selection for documentation-only follow-ups
once the full runtime baseline is established. Never turn missing test tools into
a silent qualification pass. Production form tests remain deliberately skipped
until the broker-only form capability is implemented and accepted.

## Evidence and release boundary

Record source SHA, test environment/tool versions, passed/failed/skipped gates,
and checks performed. The checked-in release manifest may retain older images;
compare deployed digests with the candidate, rather than assuming healthy
containers run the latest source. A full test pass is not the final broker review
or live application acceptance. See the [M0 environment evidence](evidence/2026-09-11-m0-environment.md)
and [roadmap](../specs/proposals/v0.2/ROADMAP.md).
