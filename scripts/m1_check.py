#!/usr/bin/env python3
"""outputs/m1/evidence.md 각 행의 값에 든 숫자가 위치 칸의 원문에 글자 그대로 있는지 찾기만 한다.
뜻은 판단하지 않는다. 파일을 고치지 않고 표준 출력으로만 결과를 보인다. 표준 라이브러리만 사용."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "inputs" / "m1"
EVIDENCE = ROOT / "outputs" / "m1" / "evidence.md"

# 날짜(연도 선택) | 시각 | 숫자(+단위 한 글자)
TOKEN = re.compile(r"(?:\d{4}\.\s*)?\d{1,2}\.\s*\d{1,2}\.|\d{1,2}:\d{2}|\d+[건개%㎡명일주]?")


def find_file(file_id):
    hits = sorted(INPUT_DIR.glob(file_id + "*"))
    return hits[0] if hits else None


def utterances(text):
    """전사본을 {순번(정수): 발언 텍스트}로 나눈다."""
    result, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"\*\*\[(\d+)\]", line)
        if m:
            cur = int(m.group(1))
            result[cur] = line
        elif cur is not None and line.strip() and not line.startswith(("---", "#")):
            result[cur] += "\n" + line
    return result


def split_row(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def main():
    rows = []
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            cells = split_row(line)
            if len(cells) >= 6 and cells[0].isdigit():
                rows.append(cells)

    out = ["| # | 위치 | 값 | 결과 | 못 찾은 글자 |", "|---|---|---|---|---|"]
    for num, _sentence, value, source, location, _proc in rows:
        tokens = [m.group(0) for m in TOKEN.finditer(value)]
        if not tokens:
            out.append(f"| {num} | {location} | {value} | 직접 확인 | - |")
            continue
        refs = [int(n) for n in re.findall(r"\[(\d+)\]", location)]
        scope = []
        for fid in re.findall(r"A-M1-\d{2}", source):
            path = find_file(fid)
            if path is None:
                continue
            text = path.read_text(encoding="utf-8-sig")
            if fid == "A-M1-01" and refs:
                utts = utterances(text)
                scope.extend(utts[n] for n in refs if n in utts)
            else:
                scope.append(text)
        haystack = "\n".join(scope)
        missing = [t for t in tokens if t not in haystack]
        result = "없음" if missing else "있음"
        out.append(f"| {num} | {location} | {value} | {result} | {', '.join(missing) if missing else '-'} |")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
