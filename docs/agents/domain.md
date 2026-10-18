# 도메인 문서

엔지니어링 스킬이 코드베이스를 살펴볼 때 이 저장소의 도메인 문서를 어떻게 읽고 쓰는지 정한다.

## 살펴보기 전에 읽을 것

- 루트의 **`GLOSSARY.md`**. 또는
- 루트에 **`GLOSSARY-MAP.md`**가 있으면 그것. 맥락마다 하나씩 있는 `GLOSSARY.md`를 가리키므로, 다루는 주제와 관련된 것을 모두 읽는다.
- **`docs/adr/`**: 작업할 영역과 관련된 ADR을 읽는다. 맥락이 여럿인 저장소라면 맥락별 결정이 있는 `src/<context>/docs/adr/`도 확인한다.

이 파일들이 없으면 **아무 말 없이 넘어간다**. 없다고 지적하지 말고, 미리 만들자고 제안하지도 않는다. `/domain-modeling` 스킬(`/grill-with-docs`, `/improve-codebase-architecture`를 통해서도 쓰인다)이 용어나 결정이 실제로 정해질 때 필요한 만큼 만든다.

## 파일 구조

맥락이 하나인 저장소(대부분):

```
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

맥락이 여럿인 저장소(루트에 `GLOSSARY-MAP.md`가 있음):

```
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← 시스템 전체 결정
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← 맥락별 결정
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## 용어집의 용어를 쓴다

결과물에서 도메인 개념을 부를 때(이슈 제목, 리팩터링 제안, 가설, 테스트 이름)는 `GLOSSARY.md`에 정의된 용어를 그대로 쓴다. 용어집이 피하라고 한 동의어로 바꾸지 않는다.

필요한 개념이 용어집에 없다면 둘 중 하나다. 프로젝트에서 쓰지 않는 말을 지어내고 있거나(다시 생각한다), 용어집에 정말 빈 곳이 있다(`/domain-modeling`에서 다루도록 적어 둔다).

## ADR과 충돌하면 드러낸다

결과물이 기존 ADR과 어긋나면 조용히 덮어쓰지 말고 분명히 밝힌다.

> _ADR-0007(event-sourced orders)과 어긋나지만, 다음 이유로 다시 논의할 만하다…_
