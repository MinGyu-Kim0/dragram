# 이슈 트래커: GitHub

이 저장소의 이슈와 명세는 GitHub 이슈로 관리한다. 모든 작업은 `gh` CLI로 한다.

## 규칙

- **이슈 만들기**: 제목·본문은 `.github/CONTRIBUTING.md`의 "이슈" 절을 따른다(한국어, 필수 내용은 `###` 제목). 본문을 파일로 저장해 `gh issue create --title "..." --body-file <파일>`로 넘긴다.
- **이슈 읽기**: `gh issue view <number> --json number,title,body,labels,comments`.
- **이슈 목록**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`에 `--label`, `--state` 필터를 알맞게 붙인다.
- **이슈를 상위 이슈의 하위 이슈로 만들기**: `gh issue create --parent <parent> ...`, 또는 만든 뒤 `gh issue edit <parent> --add-sub-issue <child>`(`gh` 2.94 이상). 이전 버전 `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>`(데이터베이스 id, 아래 **차단** 참고). 하위 이슈 기능이 없으면 하위 이슈 본문 맨 위에 `Part of #<parent>`를 적는다.
- **이슈에 댓글 달기**: `gh issue comment <number> --body "..."`
- **라벨 붙이기 / 떼기**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **닫기**: `gh issue close <number> --comment "..."`

저장소는 `git remote -v`로 알 수 있다. 클론 안에서 실행하면 `gh`가 알아서 찾는다.

## 트리아지 대상으로서의 PR

**PR을 요청 창구로 쓰는가: 아니오.** _(외부 PR을 기능 요청으로 다루는 저장소라면 `예`로 바꾼다. `/triage`가 이 값을 읽는다.)_

`예`로 바꾸면 PR도 이슈와 같은 라벨과 상태로 다루며, `gh pr` 명령을 쓴다.

- **PR 읽기**: `gh pr view <number> --comments`, diff는 `gh pr diff <number>`.
- **트리아지할 외부 PR 목록**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **댓글 / 라벨 / 닫기**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub는 이슈와 PR이 번호를 함께 쓰므로 `#42`만으로는 어느 쪽인지 모른다. `gh pr view 42`로 확인하고, 실패하면 `gh issue view 42`를 쓴다.

## 스킬이 "이슈 트래커에 올려라"라고 하면

GitHub 이슈를 만든다.

## 스킬이 "관련 티켓을 가져와라"라고 하면

위의 **이슈 읽기**대로 읽는다.

## Wayfinding 작업

`/wayfinder`가 쓴다. **지도(map)**는 이슈 하나이고, 그 **하위(child)** 이슈들이 티켓이다.

- **지도**: `wayfinder:map` 라벨이 붙은 이슈 하나. 본문에 Notes / Decisions-so-far / Fog를 둔다. `gh issue create --label wayfinder:map`.
- **하위 티켓**: 지도에 GitHub 하위 이슈로 연결한 이슈(**이슈를 상위 이슈의 하위 이슈로 만들기** 참고). 하위 이슈 기능이 없으면 지도 본문의 작업 목록에 추가하고, 하위 이슈 본문 맨 위에 `Part of #<map>`을 적는다. 라벨: `wayfinder:<type>`(`research`/`prototype`/`grilling`/`task`). 맡으면 작업하는 개발자에게 할당한다.
- **차단**: GitHub의 **기본 이슈 의존성(issue dependencies)** 기능으로 표시한다. 화면에도 보이는 정식 방법이다. 의존 관계는 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`로 추가한다. `<blocker-db-id>`는 차단하는 이슈의 숫자 **데이터베이스 id**다(`gh api repos/<owner>/<repo>/issues/<n> --jq .id`. `#번호`나 `node_id`가 아니다). GitHub는 `issue_dependencies_summary.blocked_by`에 열린 차단 이슈 수만 알려 주며, 이 값으로 지금 막혀 있는지 판단한다. 의존성 기능이 없으면 하위 이슈 본문 맨 위에 `Blocked by: #<n>, #<n>`을 적는다. 차단 이슈가 모두 닫히면 차단이 풀린다.
- **다음 작업 찾기**: 지도의 열린 하위 이슈(`gh issue list --state open`, 지도의 하위 이슈나 작업 목록으로 범위를 좁힌다)에서 열린 차단 이슈가 있는 것(`issue_dependencies_summary.blocked_by > 0`, 또는 `Blocked by` 줄에 열린 이슈가 있는 것)과 담당자가 있는 것을 뺀다. 남은 것 중 지도 순서상 첫 번째를 고른다.
- **맡기**: `gh issue edit <n> --add-assignee @me`. 세션에서 가장 먼저 하는 쓰기 작업이다.
- **끝내기**: `gh issue comment <n> --body "<answer>"`, 이어서 `gh issue close <n>`. 그다음 지도의 Decisions-so-far에 요점과 링크를 덧붙인다.
