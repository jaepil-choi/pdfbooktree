# pdfbooktree 릴리스 / Release

이 문서는 저장소 설정과 사람이 승인해야 하는 운영 절차를 함께 기록한다. workflow
파일만 추가해도 Trusted Publishing은 활성화되지 않는다. GitHub와 PyPI 양쪽의
보호 설정을 별도로 완료해야 한다.

This document covers both repository configuration and the human approvals
required for release. Adding workflow files alone does not enable Trusted
Publishing; GitHub and PyPI must be configured separately.

## 한국어

### 1. 최초 1회 설정

PyPI와 TestPyPI에서 project가 아직 없을 때는 각각 **pending publisher**를 만든다.

| 항목 | TestPyPI | PyPI |
| --- | --- | --- |
| project | `pdfbooktree` | `pdfbooktree` |
| owner | `jaepil-choi` | `jaepil-choi` |
| repository | `pdfbooktree` | `pdfbooktree` |
| workflow | `publish-testpypi.yml` | `publish-pypi.yml` |
| environment | `testpypi` | `pypi` |

GitHub에는 같은 이름의 environment 두 개를 만든다.

- `testpypi`: RC 게시 권한이 있는 reviewer를 1명 이상 지정하고 self-review
  허용 여부를 조직 정책에 맞게 정한다.
- `pypi`: production publisher reviewer를 지정한다. 승인자는 해당 RC run의 설치
  검증 성공과 최종 `master` CI를 확인해야 한다.
- deployment branch/tag rule은 각 workflow의 release tag만 허용한다.
- environment secret이나 장기 PyPI token은 만들지 않는다. workflow는 GitHub OIDC
  `id-token: write`와 Trusted Publishing을 사용한다.

`develop`과 `master` branch protection에는 `ci-green`을 required status check로
지정하고, 최신 branch가 아니면 merge하지 못하게 설정한다. master 직접 push,
force push와 branch 삭제는 금지한다. GitHub 설정 변경은 저장소 파일 변경과
별도의 승인 작업이다.

`develop`은 실험, showcase와 내부 설계 이력을 포함하는 전체 개발 브랜치다.
`master`는 설치 사용자에게 필요한 공개 release tree만 보존한다. release commit을
만들 때 다음 내부 경로는 `develop`에 유지하되 `master` tree에서는 제외한다.

- `experiments/`, `showcase/`, `references/`
- `docs/vibe/`, `docs/thoughts/`, `docs/handoff/`, `docs/references/`
- `docs/review/to-do-before-release.md`
- `.claude/`, `AGENTS.md`, `CLAUDE.md`
- 실험·구현 노트 전용 script

루트 README, LICENSE, CHANGELOG, CONTRIBUTING, SECURITY, RELEASING 문서와
`docs/reference.md`, 공개 평가 근거, package skill reference는 공개 계약이므로
유지한다. tag는 이 선별 작업과 CI가 끝난 `master` HEAD에만 만든다.

### 2. Release candidate

1. `develop`에서 version을 `0.1.0rc1`로 바꾸고 `uv lock`을 갱신한다.
2. `uv run pytest -q`, Ruff lint/format, build, `twine check`, wheel smoke를
   통과시킨다.
3. 검증된 commit을 `master`에 반영하고 양쪽 `ci-green`을 확인한다.
4. 해당 master HEAD에 `v0.1.0rc1` tag를 만든다.
5. `Publish to TestPyPI` workflow는 tag/version/wheel metadata가 일치하고 tag
   commit이 현재 `origin/master` HEAD인지 확인한 뒤 sdist/wheel을 한 번 build한다.
6. build provenance attestation과 `SHA256SUMS` 생성 후 `testpypi` environment
   reviewer가 승인한다.
7. 게시 뒤 별도 runner가 TestPyPI에서 정확한 RC version을 설치하고 `--version`,
   root help와 inspect help를 실행한다.

문제가 있으면 source version과 tag를 `rc2`, `rc3`처럼 올린다. 이미 게시된 tag나
artifact를 삭제·교체·재업로드하지 않는다.

### 3. Production

1. 성공한 RC 이후 `develop`에서 version을 `0.1.0`으로 바꾸고 CHANGELOG 날짜와
   내용을 최종 확인한다.
2. 다시 `develop → master`를 진행하고 양쪽 `ci-green`을 확인한다.
3. master HEAD에 `v0.1.0` tag를 만든다.
4. `pypi` environment 승인자는 성공한 RC 게시·설치 run, 최종 master CI,
   tag/version과 release notes를 확인한 뒤 승인한다.
5. workflow는 OIDC로 PyPI에 게시하고 새 runner에서 core와 `[ocr]` 설치,
   `--version`, CLI help와 OCR dependency import를 확인한다.
6. 검증 성공 뒤 GitHub Release에 wheel, sdist, `SHA256SUMS`와
   `CHANGELOG.en.md`에서 추출한 release notes를 첨부한다.

### 4. 실패 대응

- `ci-green`이 실패하면 master 반영과 tag 생성을 중단한다.
- tag validation이 실패하면 tag를 이동시키지 않는다. 잘못된 tag를 게시 전에
  삭제하고 올바른 master HEAD에서 새 번호를 사용한다.
- TestPyPI/PyPI가 이미 artifact를 받았다면 같은 version을 다시 올리지 않는다.
- 게시가 실패했지만 project에 artifact가 없다면 원인을 고친 뒤 같은 immutable
  tag에서 workflow 재실행을 검토한다. source가 바뀌면 반드시 새 version/tag다.
- provenance나 checksum 생성이 실패하면 게시를 승인하지 않는다.
- PyPI 게시 후 설치 검증이 실패하면 GitHub Release를 만들지 않고 원인을
  CHANGELOG와 issue에 기록한다. PyPI artifact는 교체할 수 없으므로 후속 patch
  release로 수정한다.
- environment reviewer, branch protection, pending publisher는 repository 밖의
  상태다. release 전에 실제 설정을 화면/API에서 다시 확인한다.

## English

### 1. One-time setup

Create a **pending publisher** on both TestPyPI and PyPI when the project does
not exist yet. Use project `pdfbooktree`, owner `jaepil-choi`, repository
`pdfbooktree`, workflow `publish-testpypi.yml` with environment `testpypi`, and
workflow `publish-pypi.yml` with environment `pypi`.

Create protected GitHub environments with the same names:

- `testpypi` requires at least one authorized RC reviewer.
- `pypi` requires a production reviewer who checks the successful RC install
  run and final `master` CI before approval.
- Deployment rules allow only the matching release tags.
- Do not create a long-lived API token or environment secret. The workflows use
  GitHub OIDC with `id-token: write`.

Require the stable `ci-green` status check on both `develop` and `master`, require
branches to be current before merge, and block direct/force pushes and branch
deletion on `master`. These external GitHub settings require separate explicit
authorization.

`develop` is the complete development branch and retains experiments, showcases,
and internal design history. `master` is a curated public release tree. Keep the
following paths on `develop` but remove them from the `master` tree when creating
a release commit:

- `experiments/`, `showcase/`, and `references/`
- `docs/vibe/`, `docs/thoughts/`, `docs/handoff/`, and `docs/references/`
- `docs/review/to-do-before-release.md`
- `.claude/`, `AGENTS.md`, and `CLAUDE.md`
- scripts used only for experiments or implementation notes

Retain the root README, LICENSE, CHANGELOG, CONTRIBUTING, SECURITY, and RELEASING
documents, `docs/reference.md`, public evaluation evidence, and package skill
references. Create a release tag only from the curated, CI-green `master` HEAD.

### 2. Release candidates

Set the source version to `0.1.0rc1`, update `uv.lock`, complete local validation,
merge the verified commit through `develop` and `master`, and confirm
`ci-green` on both. Tag the exact master HEAD as `v0.1.0rc1`.

The TestPyPI workflow checks tag/source/wheel versions and requires the tag
commit to equal the current `origin/master` HEAD. It builds one wheel and sdist,
runs `twine check`, writes SHA-256 checksums, creates a provenance attestation,
waits for protected-environment approval, publishes through OIDC, and verifies a
fresh installation from TestPyPI.

If a defect is found, increment to `rc2`, `rc3`, and so on. Never replace or
re-upload an existing RC artifact.

### 3. Production

After a successful RC, set the version to `0.1.0`, finalize the changelog, repeat
the `develop → master` and CI gates, and tag the exact master HEAD as `v0.1.0`.
The `pypi` reviewer verifies the successful RC run before approval. The workflow
publishes through OIDC, verifies fresh core and `[ocr]` installations, then
creates a GitHub Release with the wheel, sdist, `SHA256SUMS`, and extracted
release notes.

### 4. Failure handling

- Never merge to master or create a tag while `ci-green` is failing.
- Do not move a published tag. If no publication occurred, delete an incorrect
  tag and create the correct new tag from master.
- Never re-upload an existing version. Any source change requires a new RC or
  patch version.
- Do not approve publication when checksum or provenance generation fails.
- If post-publication installation fails, do not create the GitHub Release.
  Record the problem and fix it in a subsequent version because PyPI artifacts
  are immutable.
- Recheck environment reviewers, branch protection, and pending publishers
  immediately before release; they are external state not enforced by files in
  this repository.
