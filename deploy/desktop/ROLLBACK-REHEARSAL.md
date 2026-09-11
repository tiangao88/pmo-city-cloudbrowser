# Disposable desktop cold-restore rehearsal

Local test evidence, **not a production rollback procedure or release GO**.
No existing volume, account, credential, Coolify service or dev01 runtime is
used. The candidate remains credential-disabled.

## Tested sequence

`experiments/novnc/candidate_smoke.py` now performs this after A/B/A:

1. Stop the actual desktop subprocess and require a clean exit before copying.
2. Copy its temporary per-owner Chromium profile root into a new backup tree.
   Compare file size/SHA-256/mode, directory modes and symlink targets before
   and after copying. Links are copied without following them.
3. Simulate an unsuccessful upgrade by changing a synthetic version canary and
   adding a candidate-only marker in the original profile tree.
4. Restore into a **fresh directory**, never overlaying the modified tree.
   Verify the manifest, original canary, absence of the candidate-only marker,
   and preservation of the modified original and unchanged backup.
5. Restart with the restored profile root. Require Alice's persistent
   synthetic cookie, reject old viewer cookies/controller tickets, and sample
   the restored owner's WSS framebuffer.
6. Repeat process-crash and lease-recovery checks. Remove the disposable
   container and its temporary state on completion.

The helper refuses existing/nested destinations and unsupported filesystem
objects. Unit tests cover cold SQLite integrity/content, modes, non-followed
symlinks and detection of a corrupted copy. All writers must be stopped first;
this is not a general live-backup utility. Manifests stay in memory, not logs.

## Reproduce

Build the candidate as documented in `services/desktop/README.md`, then run
from the repository root:

```sh
docker run --rm --network none \
  --mount type=bind,source="$PWD/experiments/novnc",target=/fixture,readonly \
  --entrypoint python3 cloudbrowser-desktop:candidate-local \
  /fixture/candidate_smoke.py
.venv/bin/python -m pytest -q tests/installation/test_desktop_cold_restore.py
```

Only test code is mounted from the host, read-only. Profiles live in a new
temporary directory inside the disposable container. No ports are published;
HTTPS/WSS stays inside the fixture. Authentication and cookies are synthetic.

## Evidence — 2026-09-11

- Cold-copy tests: **4 passed** on the Mac.
- Full Linux Python 3.12 regression suite: **1,190 passed / 14 skipped**.
  Skips remain five Docker-CLI checks, three disabled form cases and six
  unavailable real-browser cases; the standalone smoke separately uses Chromium.
  Test image: `sha256:5807592eadda4643ef01ef1147bd3d6f2f1028ccf1ee56b3f43c73d105a96988`.
- Actual Chromium cold restore, cookie continuity, stale-authority denial,
  A/B/A, broker-job exclusion, Xvfb/Chromium/x11vnc crashes and lease recovery:
  **passed**. All four owner/restart framebuffer samples contained 870,708
  owner pixels and zero other-owner pixels.
- Desktop image:
  `sha256:c3ebb28a6a616667d1bbef8e7633004ece2eef5217a67f60a065a4fe3dc839de`.
  Runtime source did not change in this checkpoint.

## Remaining gates

- Resolve the incomplete M2 security review through its original approved
  workflow. A read-only check still showed `running` / discovery, with no
  completed report, for scan `f6547962-81de-4748-bede-39f6e240eb82`. This does
  not clear the previously recorded platform block. No scan was restarted,
  replaced or marked complete here.
- Review the actual M3 release candidate too: the M2 scan ends at `9c113587`
  and cannot approve later desktop/job-coordination changes.
- Freeze old/new image digests and qualify dependencies, attestations,
  Chromium isolation and intended-host configuration.
- Rehearse **old image → candidate → old image** using disposable copies of
  all service state, including router, supervisor and identity-link databases.
  This drill uses the same image and restores browser profiles only; it does
  not establish schema-downgrade or whole-stack rollback compatibility.
- Define stop/drain order and backup sets for every writer/volume. Custody,
  grants, keys, job locks, downloads and real identity state are outside this
  fixture. Do not restore active locks or revive viewer authority from backup.
  File comparison is not power-loss durability, encrypted-backup, retention
  or disaster-recovery qualification.
- Obtain deployment approval, then qualify real SSO/revocation and harmless
  human takeover. Vaultwarden onboarding remains a separate gate.

The existing generic Coolify copy helper overlays destination directories; it
was not used or changed here. Fresh-tree restore avoids retaining files added
by an unsuccessful upgrade, but needs a reviewed volume-switch plan.
