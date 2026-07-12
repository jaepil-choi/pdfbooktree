"""experiment 090: tier→level purity로 tree를 무너뜨리는 tier를 찾아 반복 제거한다.

이 실험 이전까지 확인한 사실:
  - 088: overlay font_size 상한 clamp를 없애면 stack이 다단 계층(tier 6개, level
    1~4)을 만들지만, 실제 제목은 여전히 못 쓴다.
  - 089: 거대 병합 line 자체는 드물고(word_count>30인 line 39/19,182개) 짧은데도
    bbox가 큰 표/수식 fragment(2,304개, tier 1~4 후보 풀 전체)가 진짜 원인이다.

사용자 지침: 이 책은 예외적인 사례로 받아들이고, bookmark가 전부 오염되어 있으면
남는 게 없어도 어쩔 수 없다. 대신 "어떤 tier/level이 tree 구조를 방해하는 pollution
인지"를 찾아내는 일반 알고리즘에 집중한다. category는 여전히 쓰지 않는다.

가설: `infer_bpe_outline`의 stack algorithm에서, 진짜 계층 구조를 이루는 tier는
책 전체에 걸쳐 거의 항상 같은 level에 배치된다(예: "장" tier는 항상 level 1,
"절" tier는 항상 level 2). 반면 표/수식 fragment처럼 우연히 큰 bbox를 가진
tier는 문서 어디서든 무작위로 나타나므로, 그 순간의 stack 깊이에 따라 서로
다른 level에 뒤섞여 배치된다("purity"가 낮다).

주의할 confound: 가장 작은 tier 번호(가장 큰 글씨)는 스택 알고리즘 구조상 등장할
때마다 그 아래 모든 걸 pop하므로 "항상 level 1"이 되는 게 당연하다(내용과 무관한
수학적 필연). 그래서 최상위 tier의 purity=1.0은 무의미할 수 있다. 이 실험은
이 confound를 실제로 관찰하고, purity가 전체 tier를 얼마나 잘 구분하는지, 그리고
page burstiness(한두 page에 몰려 나오는지)가 보완 신호가 되는지도 함께 확인한다.

알고리즘(반복 pruning):
  1. 남은 heading candidate로 stack algorithm을 한 번 돌려 tier별 level 분포를 본다.
  2. 각 tier의 purity = (가장 많이 나온 level의 빈도) / (그 tier 총 빈도).
  3. purity가 임계값(min_purity) 미만인 tier 중 가장 나쁜 것 하나를 후보 pool에서
     완전히 제거한다(본문 취급).
  4. 남은 candidate로 다시 stack algorithm을 돌리고 반복한다.
  5. 모든 tier의 purity가 임계값 이상이 되거나 candidate가 바닥날 때까지 반복한다.
     bookmark가 하나도 안 남아도 그대로 받아들인다.

실행:
    uv run python experiments/090_iterative_tier_purity_pruning.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.typography.bpe import BpeHeading, extract_bpe_headings
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "090_iterative_tier_purity_pruning"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

UNCLAMPED_PDF = (
    ROOT_DIR
    / "experiments"
    / "outputs"
    / "088_unclamped_font_size_stack_recovery"
    / "arm_b_unclamped.pdf"
)

MIN_PURITY = 0.8
MIN_TIER_ITEM_COUNT = 5  # 이보다 적은 tier는 표본이 작아 purity 판단이 불안정하다.
MAX_ITERATIONS = 30

KNOWN_REAL_HEADINGS = [
    "머리말",
    "차례",
    "1장 확률분포",
    "1.1 확률의 뜻과 성질",
    "1.3 확률변수와 확률분포",
]


def run_stack(headings: list[BpeHeading]) -> list[tuple[BpeHeading, int]]:
    """infer_bpe_outline의 순수 stack 로직만 복제해 (heading, level) 쌍을 만든다.

    pollution 기반 +1 level 강등이나 body_levels 제거는 여기서 하지 않는다 -
    tier 자체의 구조적 순도만 측정하기 위해서다.
    """

    stack: list[BpeHeading] = []
    result: list[tuple[BpeHeading, int]] = []
    for heading in headings:
        while stack and stack[-1].tier > heading.tier:
            stack.pop()
        if stack and stack[-1].tier == heading.tier:
            level = len(stack)
            stack[-1] = heading
        else:
            stack.append(heading)
            level = len(stack)
        result.append((heading, level))
    return result


def tier_stats(
    pairs: list[tuple[BpeHeading, int]],
) -> dict[int, dict[str, object]]:
    by_tier: dict[int, list[tuple[BpeHeading, int]]] = defaultdict(list)
    for heading, level in pairs:
        by_tier[heading.tier].append((heading, level))

    stats: dict[int, dict[str, object]] = {}
    for tier, items in by_tier.items():
        levels = [level for _, level in items]
        pages = [heading.pdf_page for heading, _ in items]
        level_counts = Counter(levels)
        dominant_level, dominant_count = level_counts.most_common(1)[0]
        page_counts = Counter(pages)
        max_on_one_page = max(page_counts.values())
        stats[tier] = {
            "count": len(items),
            "level_distribution": dict(sorted(level_counts.items())),
            "dominant_level": dominant_level,
            "purity": round(dominant_count / len(items), 4),
            "unique_pages": len(page_counts),
            "max_on_one_page": max_on_one_page,
            "burst_share": round(max_on_one_page / len(items), 4),
        }
    return stats


def iterative_prune(
    headings: list[BpeHeading],
) -> tuple[list[BpeHeading], list[dict[str, object]]]:
    remaining = list(headings)
    trace: list[dict[str, object]] = []

    for iteration in range(MAX_ITERATIONS):
        if not remaining:
            break
        pairs = run_stack(remaining)
        stats = tier_stats(pairs)
        # 표본이 너무 작은 tier는 이번 라운드 판단에서 제외한다(제거 대상에서만
        # 제외할 뿐, purity 계산 자체에는 포함해 기록은 남긴다).
        removable = {
            tier: info
            for tier, info in stats.items()
            if info["count"] >= MIN_TIER_ITEM_COUNT and info["purity"] < MIN_PURITY
        }
        trace.append(
            {
                "iteration": iteration,
                "remaining_count": len(remaining),
                "tier_stats": stats,
                "removable_tiers": sorted(removable),
            }
        )
        if not removable:
            break
        worst_tier = min(removable, key=lambda tier: removable[tier]["purity"])
        trace[-1]["removed_tier"] = worst_tier
        remaining = [h for h in remaining if h.tier != worst_tier]

    return remaining, trace


def build_plan(headings: list[BpeHeading]) -> list[BookmarkPlanItem]:
    pairs = run_stack(headings)
    plan = [
        BookmarkPlanItem(
            title=heading.title,
            level=level,
            pdf_page=heading.pdf_page,
            source="bpe_typography_pruned",
            confidence=0.8,
            evidence=[f"font_tier_{heading.tier}"],
        )
        for heading, level in pairs
    ]
    return normalize_bookmark_plan(plan)


def anchor_report(plan: list[BookmarkPlanItem]) -> list[dict[str, object]]:
    hits = []
    for anchor in KNOWN_REAL_HEADINGS:
        matches = [item for item in plan if anchor in item.title]
        if matches:
            first = matches[0]
            hits.append(
                {
                    "anchor": anchor,
                    "match_count": len(matches),
                    "first_title": first.title,
                    "first_level": first.level,
                    "exact_clean_match": first.title.strip() == anchor,
                }
            )
        else:
            hits.append({"anchor": anchor, "match_count": 0})
    return hits


def record_experiment(summary: dict[str, object]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "088/089에서 남은 문제(표/수식 fragment가 heading tier를 오염시켜 tree가 "
            "안 만들어짐)를 풀기 위해, category 없이 tier -> level 배치의 구조적 "
            "'purity'만으로 tree를 방해하는 tier를 찾아 반복 제거하는 일반 알고리즘을 "
            "검증한다. bookmark가 하나도 안 남는 결과도 그대로 받아들인다."
        ),
        "inputs": [str(UNCLAMPED_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "088의 unclamped overlay PDF에서 extract_bpe_headings로 얻은 heading "
            "token(이미 BPE 병합 완료)에 대해, infer_bpe_outline의 순수 stack "
            "로직만 복제해 tier별 level 분포와 purity(최빈 level 비중)를 측정했다. "
            f"purity<{MIN_PURITY}이고 표본이 {MIN_TIER_ITEM_COUNT}개 이상인 tier 중 "
            "가장 낮은 tier를 후보 pool에서 제거하고 재계산하는 것을 반복했다. "
            "page burstiness(한두 page 집중도)도 보완 신호로 같이 측정했다."
        ),
        "summary": summary,
        "finding": summary["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not UNCLAMPED_PDF.exists():
        raise FileNotFoundError(f"088의 산출물이 없다: {UNCLAMPED_PDF}")

    config = TypographyConfig()
    raw_lines = extract_typography_lines(UNCLAMPED_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    headings = extract_bpe_headings(lines, font_tiers, config)

    initial_pairs = run_stack(headings)
    initial_stats = tier_stats(initial_pairs)
    initial_plan = build_plan(headings)

    pruned_headings, trace = iterative_prune(headings)
    final_plan = build_plan(pruned_headings) if pruned_headings else []

    initial_anchor = anchor_report(initial_plan)
    final_anchor = anchor_report(final_plan) if final_plan else [
        {"anchor": a, "match_count": 0} for a in KNOWN_REAL_HEADINGS
    ]

    removed_tiers = [step["removed_tier"] for step in trace if "removed_tier" in step]
    initial_purity_text = ", ".join(
        f"{tier}:{info['purity']}" for tier, info in sorted(initial_stats.items())
    )

    finding = (
        f"초기: heading candidate {len(headings)}개, tier {len(initial_stats)}개, "
        f"purity={{{initial_purity_text}}}. "
        f"반복 제거로 tier {removed_tiers}를 순서대로 제거했고(iteration {len(trace)}회), "
        f"최종적으로 {len(pruned_headings)}개 candidate, bookmark {len(final_plan)}개가 "
        "남았다. "
        + (
            "남은 tier가 없어 bookmark가 완전히 사라졌다 - 이 책은 예외적으로 "
            "처리된다(사용자 지침대로 허용)."
            if not final_plan
            else f"level_counts={dict(sorted(Counter(item.level for item in final_plan).items()))}."
        )
    )

    summary = {
        "min_purity": MIN_PURITY,
        "min_tier_item_count": MIN_TIER_ITEM_COUNT,
        "initial_candidate_count": len(headings),
        "initial_tier_stats": initial_stats,
        "initial_anchor_hits": initial_anchor,
        "prune_trace": trace,
        "removed_tiers_in_order": removed_tiers,
        "final_candidate_count": len(pruned_headings),
        "final_bookmark_count": len(final_plan),
        "final_level_counts": dict(sorted(Counter(item.level for item in final_plan).items()))
        if final_plan
        else {},
        "final_anchor_hits": final_anchor,
        "final_tree_preview": [
            f"{'  ' * (item.level - 1)}[L{item.level}, p.{item.pdf_page}] {item.title}"
            for item in final_plan[:40]
        ],
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
