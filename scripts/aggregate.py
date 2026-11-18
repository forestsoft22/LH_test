#!/usr/bin/env python3
"""하자접수대장 집계 (rules/aggregation_rules.md 기준). 표준 라이브러리만 사용.

실행: python3 scripts/aggregate.py
입력은 읽기만 한다. 결과는 outputs/m2/ 에 새로 쓴다.
"""
import csv
import re
import sys
from collections import Counter, OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "inputs" / "m2" / "A-M2-01_하자접수대장_week1.csv"
OUT = ROOT / "outputs" / "m2"

PYEONG = Fraction(400, 121)  # 1평 = 400/121 ㎡ (3.305785...)
AREA_TRADES = {"마감", "방수결로"}  # 면적 대상 공종
ID_RE = re.compile(r"^HA-\d+$")
LOC_STD = re.compile(r"^\d+-\d+-\S+$")
LOC_DONGHO = re.compile(r"^(\d+)동\s*(\d+)호\s+(\S+)$")
LOC_SPACE = re.compile(r"^(\d+-\d+)\s+(\S+)$")


def round1(x: Fraction) -> Decimal:
    d = Decimal(x.numerator) / Decimal(x.denominator)
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def main():
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        raw_lines = f.read().splitlines()
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        rows = list(rdr)
    col = {h: i for i, h in enumerate(header)}
    n_before = len(rows)

    excluded = []   # (원본행, 사유, 원본값)
    fixed = []      # (행, 규칙, 원본값, 수정값)
    flags = []      # (행, 규칙, 설명)
    rule_excl = Counter()
    kept = []       # dict per kept row

    def raw_value(i):
        return raw_lines[i]  # 머리행이 0번이므로 데이터 행 i는 raw_lines[i]

    # R1 합계 행
    stage = []
    original_total = None
    for i, r in enumerate(rows, 1):
        if not ID_RE.match(r[col["접수번호"]]):
            excluded.append((i, "R1 합계 행", raw_value(i)))
            rule_excl["R1"] += 1
            original_total = (r[col["하자내용"]], r[col["보수면적"]], r[col["면적단위"]])
        else:
            stage.append((i, list(r)))

    # R2 위치코드 표준화 (확정 불가면 R2-c로 제외)
    stage1 = []
    for i, r in stage:
        loc = r[col["위치코드"]]
        if LOC_STD.match(loc):
            stage1.append((i, r))
            continue
        m = LOC_DONGHO.match(loc)
        if m:
            new = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = LOC_SPACE.match(loc)
            new = f"{m.group(1)}-{m.group(2)}" if m else None
        if new and LOC_STD.match(new):
            fixed.append((i, "R2 위치코드 표준화", loc, new))
            r[col["위치코드"]] = new
            stage1.append((i, r))
        else:
            excluded.append((i, "R2-c 위치코드 확정 불가 {확인 필요: 위치코드}", raw_value(i)))
            rule_excl["R2-c"] += 1
    stage = stage1

    # R3 완전 중복 (원본 값 기준, 표준화 전후와 무관하게 모든 열 동일)
    orig = {i: tuple(rows[i - 1]) for i, _ in stage}
    seen = {}
    stage2 = []
    for i, r in stage:
        key = orig[i]
        if key in seen:
            excluded.append((i, f"R3 완전 중복 (유지: {seen[key]}행)", raw_value(i)))
            rule_excl["R3"] += 1
        else:
            seen[key] = i
            stage2.append((i, r))

    # R4 유사 중복 (접수번호만 다름): 먼저 접수된 행만 남기고 나중 행 제외
    first = {}
    stage3 = []
    for i, r in stage2:
        k = (r[col["접수일"]], r[col["위치코드"]], r[col["공종"]], r[col["하자내용"]])
        if k in first:
            excluded.append((i, f"R4 유사 중복 (유지: {first[k]}행) {{확인 필요: 재접수 여부}}", raw_value(i)))
            rule_excl["R4"] += 1
        else:
            first[k] = i
            stage3.append((i, r))
    stage2 = stage3

    # R5/R6 면적
    area_na = 0
    area_missing = []
    for i, r in stage2:
        v, u, trade = r[col["보수면적"]].strip(), r[col["면적단위"]].strip(), r[col["공종"]]
        area = None
        if v == "":
            if trade in AREA_TRADES:
                area_missing.append(i)
                flags.append((i, "R6-b", "면적 빈칸 -> 포함, {확인 필요: 보수면적}"))
            else:
                area_na += 1
        else:
            try:
                num = Fraction(v)
                if num < 0 or u not in ("㎡", "평"):
                    raise ValueError
            except (ValueError, ZeroDivisionError):
                excluded.append((i, "R6-c 면적 계산 불가", raw_value(i)))
                rule_excl["R6-c"] += 1
                continue
            if u == "평":
                area = num * PYEONG
                fixed.append((i, "R5 평->㎡ 환산", f"{v}평", f"{round1(area)}㎡ (정확값 {float(area):.6f})"))
            else:
                area = num
        if "아래층" in r[col["하자내용"]]:
            flags.append((i, "참고", "하자내용에 다른 세대(아래층) 언급 -> 1건으로 포함, {확인 필요: 별도 접수 여부}"))
        kept.append({"row": i, "trade": trade, "status": r[col["처리상태"]],
                     "urgent": r[col["긴급구분"]], "area": area})

    # R7 집계
    agg = OrderedDict()
    for k in sorted({(k["trade"], k["status"], k["urgent"]) for k in kept}):
        agg[k] = [0, None]
    total_area = Fraction(0)
    for k in kept:
        a = agg[(k["trade"], k["status"], k["urgent"])]
        a[0] += 1
        if k["area"] is not None:
            a[1] = (a[1] or Fraction(0)) + k["area"]
            total_area += k["area"]

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["공종", "처리상태", "긴급", "건수", "면적(㎡)"])
        for (t, s, u), (n, a) in agg.items():
            w.writerow([t, s, u, n, "" if a is None else round1(a)])
    with open(OUT / "excluded_rows.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["원본행", "사유", "원본값"])
        for e in sorted(excluded):
            w.writerow(e)

    n_after = len(kept)
    cmd = "python3 " + " ".join(sys.argv)
    L = []
    L.append("# 실행 기록 (M2 집계)\n")
    L.append(f"- 실행 명령: `{cmd}`")
    L.append(f"- 입력 파일: `{SRC.relative_to(ROOT)}` (읽기만 함)")
    L.append(f"- 적용 규칙: `rules/aggregation_rules.md`")
    L.append(f"- 행 수 전후: 전 {n_before}행(합계 행 포함) -> 후 {n_after}행\n")
    L.append("## 규칙별 제외 수\n")
    L.append("| 규칙 | 제외 수 | 행 |\n|---|---|---|")
    for rule in ["R1", "R2-c", "R3", "R4", "R6-c"]:
        idx = [e[0] for e in sorted(excluded) if e[1].startswith(rule)]
        L.append(f"| {rule} | {len(idx)} | {', '.join(map(str, idx)) or '-'} |")
    L.append("\n## 고쳐서 포함한 행\n")
    L.append("| 행 | 규칙 | 원본값 | 수정값 |\n|---|---|---|---|")
    for i, rule, a, b in sorted(fixed):
        L.append(f"| {i} | {rule} | {a} | {b} |")
    L.append("\n## 표시·확인 필요\n")
    L.append("| 행 | 규칙 | 내용 |\n|---|---|---|")
    for i, rule, d in sorted(flags):
        L.append(f"| {i} | {rule} | {d} |")
    L.append(f"\n## 집계 결과\n")
    L.append(f"- 접수 건수: {n_after}건")
    L.append(f"- 면적 합계: {round1(total_area)}㎡ (환산·합산 중 반올림 없이 마지막에 1회 반올림)")
    L.append(f"- 면적 해당 없음(설비·창호·전기 빈칸): {area_na}건")
    L.append(f"- 면적 `{{확인 필요}}`(마감·방수결로 빈칸): {len(area_missing)}건")
    if original_total:
        L.append(f"- 원본 합계 행(참고, 미사용): {original_total[0]} / {original_total[1]}{original_total[2]}")
    L.append("- summary.csv 묶음별 면적은 각각 1회 반올림한 값이라 합이 총합과 0.1 어긋날 수 있다.")
    (OUT / "run_log.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
