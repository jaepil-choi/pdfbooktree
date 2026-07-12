"""experiment 089: 거대 pollution line을 tiering 이전에 걸러내면 tree가 얼마나 회복되는지 본다.

088에서 overlay font_size 상한 clamp를 없애자 flat 552개(all level 1)가 다단(level
1~4, tier 3->6)으로 갈라졌지만, 실제 제목을 까 보면 여전히 못 쓴다. 원인은
`overlay_mode="element"`로 삽입되는 equation/table/chart/figure가 원본의 여러 줄을
통째로 하나의 TypographyLine으로 합쳐서, bbox 높이만 큰 게 아니라 텍스트 자체도
비정상적으로 길다("정리 1.1.3 확률측도의 연속성 | | --- | | (a) A1⊂A2⊂...이면
P(∪An)=lim P(An)"). 이런 line이 tier 계산과 heading 후보 풀에 섞여 들어가면 tier
분포와 BPE 병합이 같이 오염된다.

이 실험은 category(OCR engine 의존)를 전혀 쓰지 않고, 순수 텍스트 길이(단어 수)라는
line 고유 속성만으로 이런 pollution line을 **tiering 이전에** 제거했을 때 tree
구조가 얼마나 회복되는지 본다. 책 전체(exp088 unclamped arm, 19,182줄) 단어 수
분포를 보면 중앙값 5단어, 90%ile 13단어, 99%ile 22단어인데 30단어를 넘는 line은
39개(0.2%)뿐이고 최댓값은 336단어다 - 즉 매우 드문 극단치만 제거하면 된다.
`bpe_max_node_words=30`(기존 config 기본값, 지금은 사후 레벨 강등에만 쓰임)과 같은
임계값을 그대로 재사용해 사전 제거 arm을 만든다.

동시에, 088 조사에서 실제 절 제목("1.3 확률변수와 확률분포", p.18, font_size
10.95pt)이 애초에 body tier(peak 9.7)와 구분되지 않아 heading 후보에도 못 들어간
사실을 확인했다. 이 실험은 pollution 제거가 이 문제까지 고쳐주는지(아닐 가능성이
높다 - 이 줄 자체는 pollution이 아니라 이미 정상적인 단일 line이므로), 아니면
equation/table/chart 노이즈만 청소해주는지 정확히 구분해서 기록한다.

비교 arm:
  - arm_b(=088의 unclamped, 재사용): pollution 미제거.
  - arm_c(pollution_filtered): exclude_margin_artifacts 다음, compute_tier_set
    이전에 word_count > 30인 line을 제거한다.

실행:
    uv run python experiments/089_pollution_line_filter_before_tiering.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import TypographyLine
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.typography.bpe import extract_bpe_headings, infer_bpe_outline
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import assign_tier, compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "089_pollution_line_filter_before_tiering"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

UNCLAMPED_PDF = (
    ROOT_DIR
    / "experiments"
    / "outputs"
    / "088_unclamped_font_size_stack_recovery"
    / "arm_b_unclamped.pdf"
)

POLLUTION_WORD_THRESHOLD = 30  # 기존 TypographyConfig.bpe_max_node_words 기본값 재사용

# 실제 육안 확인된 진짜 heading 전체 문구(088 조사에서 raw cache로 직접 확인).
# 짧은 "1.3" 같은 substring은 "정리 1.1.3"처럼 다른 번호 안에 우연히 포함될 수 있어
# 반드시 이렇게 유일한 전체 문구로 anchor를 잡는다.
KNOWN_REAL_HEADINGS = [
    "머리말",
    "차례",
    "1장 확률분포",
    "1.1 확률의 뜻과 성질",
    "1.3 확률변수와 확률분포",
]


def word_count(text: str) -> int:
    return len(text.split())


def run_bpe_pipeline(
    lines: list[TypographyLine], config: TypographyConfig
) -> dict[str, object]:
    font_tiers = compute_tier_set(lines, "font_size", config)
    candidates = extract_bpe_headings(lines, font_tiers, config)
    plan = normalize_bookmark_plan(infer_bpe_outline(candidates, config))

    level_counts = dict(sorted(Counter(item.level for item in plan).items()))
    anchor_hits = []
    for anchor in KNOWN_REAL_HEADINGS:
        matches = [item for item in plan if anchor in item.title]
        if matches:
            first = matches[0]
            anchor_hits.append(
                {
                    "anchor": anchor,
                    "match_count": len(matches),
                    "first_title": first.title,
                    "first_level": first.level,
                    "first_pdf_page": first.pdf_page,
                    "exact_clean_match": first.title.strip() == anchor,
                }
            )
        else:
            anchor_hits.append({"anchor": anchor, "match_count": 0})

    tree_lines = [
        f"{'  ' * (item.level - 1)}[L{item.level}, p.{item.pdf_page}] {item.title}"
        for item in plan
    ]

    return {
        "line_count": len(lines),
        "font_tier_count": font_tiers.final_tier_count,
        "tier_peaks": [round(tier.peak, 2) for tier in font_tiers.tiers],
        "bookmark_count": len(plan),
        "level_counts": level_counts,
        "max_level": max(level_counts) if level_counts else 0,
        "anchor_hits": anchor_hits,
        "tree_preview": tree_lines[:40],
    }


def where_is_known_heading(
    lines: list[TypographyLine], font_tiers, text: str
) -> dict[str, object] | None:
    """진짜 heading line이 body tier로 뭉개졌는지 직접 확인한다."""

    for line in lines:
        if text in line.text:
            tier = assign_tier(line.font_size, font_tiers.cut_points)
            return {
                "text": line.text,
                "pdf_page": line.pdf_page,
                "font_size": round(line.font_size, 2),
                "height": round(line.height, 2),
                "is_bold": line.is_bold,
                "tier": tier,
            }
    return None


def record_experiment(summary: dict[str, object]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "088에서 확인한 것처럼 overlay_mode='element'가 만드는 거대 병합 line이 "
            "tier 계산과 BPE 후보 풀을 오염시킨다. category를 쓰지 않고 순수 단어 수 "
            "(line 자체 속성)만으로 이런 pollution line을 tiering 이전에 제거하면 "
            "tree 구조가 얼마나 회복되는지, 그리고 이것이 사용자가 지적한 '1.3 "
            "확률변수와 확률분포' 같은 실제 heading 누락 문제(font_size가 body tier와 "
            "구분 안 되는 별개 원인)까지 고쳐주는지 확인한다."
        ),
        "inputs": [str(UNCLAMPED_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            f"088의 unclamped overlay PDF(arm_b)를 그대로 재사용해 "
            f"extract_typography_lines -> exclude_margin_artifacts까지는 동일하게 "
            f"수행하고, arm_c에서만 word_count > {POLLUTION_WORD_THRESHOLD}인 line을 "
            "compute_tier_set 이전에 제거했다. 나머지 파이프라인(BPE heading 추출, "
            "stack outline 추론)은 Processor와 동일한 함수, 기본 config를 그대로 "
            "썼다. 알려진 실제 heading 5개(머리말/차례/1장/1.1/1.3)를 정확한 전체 "
            "문구로 anchor 매칭했고, '1.3 확률변수와 확률분포'는 tier 배정 결과를 "
            "직접 조회해 body tier에 묶이는지도 별도로 확인했다."
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
        raise FileNotFoundError(
            f"088의 unclamped overlay PDF가 없다(먼저 088을 실행해야 한다): {UNCLAMPED_PDF}"
        )

    config = TypographyConfig()
    raw_lines = extract_typography_lines(UNCLAMPED_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)

    counts = [word_count(line.text) for line in lines]
    pollution_lines = [
        line for line, count in zip(lines, counts) if count > POLLUTION_WORD_THRESHOLD
    ]
    filtered_lines = [
        line for line, count in zip(lines, counts) if count <= POLLUTION_WORD_THRESHOLD
    ]

    result_unfiltered = run_bpe_pipeline(lines, config)
    result_filtered = run_bpe_pipeline(filtered_lines, config)

    # '1.3 확률변수와 확률분포'가 애초에 body tier로 뭉개지는지, 필터링 여부와
    # 무관하게 직접 확인한다(088에서 발견한 별개 원인).
    baseline_tiers = compute_tier_set(lines, "font_size", config)
    filtered_tiers = compute_tier_set(filtered_lines, "font_size", config)
    heading_1_3_unfiltered = where_is_known_heading(
        lines, baseline_tiers, "1.3 확률변수와 확률분포"
    )
    heading_1_3_filtered = where_is_known_heading(
        filtered_lines, filtered_tiers, "1.3 확률변수와 확률분포"
    )

    exact_clean_before = sum(
        1
        for hit in result_unfiltered["anchor_hits"]
        if hit.get("exact_clean_match")
    )
    exact_clean_after = sum(
        1 for hit in result_filtered["anchor_hits"] if hit.get("exact_clean_match")
    )

    finding = (
        f"pollution 제거 전: line={result_unfiltered['line_count']}, "
        f"font_tier={result_unfiltered['font_tier_count']}, "
        f"level_counts={result_unfiltered['level_counts']}, "
        f"정확히 깨끗하게 매칭된 known heading={exact_clean_before}/{len(KNOWN_REAL_HEADINGS)}. "
        f"pollution 제거 후(word_count>{POLLUTION_WORD_THRESHOLD} line {len(pollution_lines)}개 "
        f"제거): line={result_filtered['line_count']}, "
        f"font_tier={result_filtered['font_tier_count']}, "
        f"level_counts={result_filtered['level_counts']}, "
        f"정확히 깨끗하게 매칭된 known heading={exact_clean_after}/{len(KNOWN_REAL_HEADINGS)}. "
        f"'1.3 확률변수와 확률분포'는 제거 전 tier={heading_1_3_unfiltered['tier'] if heading_1_3_unfiltered else None}, "
        f"제거 후 tier={heading_1_3_filtered['tier'] if heading_1_3_filtered else None}로 "
        + (
            "여전히 body tier에 묶여 heading 후보 자체가 되지 못했다(pollution "
            "필터와 무관한 별개 원인: 이 heading의 font_size가 body와 구분되지 "
            "않는다)."
            if heading_1_3_filtered
            and heading_1_3_unfiltered
            and heading_1_3_filtered["tier"] == heading_1_3_unfiltered["tier"]
            else "필터 적용으로 tier 배정이 달라졌다(추가 확인 필요)."
        )
    )

    summary = {
        "pollution_word_threshold": POLLUTION_WORD_THRESHOLD,
        "pollution_line_count": len(pollution_lines),
        "pollution_sample": [
            {"pdf_page": line.pdf_page, "word_count": word_count(line.text), "text": line.text[:120]}
            for line in sorted(pollution_lines, key=lambda l: -word_count(l.text))[:10]
        ],
        "result_unfiltered": result_unfiltered,
        "result_filtered": result_filtered,
        "heading_1_3_unfiltered": heading_1_3_unfiltered,
        "heading_1_3_filtered": heading_1_3_filtered,
        "exact_clean_match_before": exact_clean_before,
        "exact_clean_match_after": exact_clean_after,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
