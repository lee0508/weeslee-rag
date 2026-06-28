# 텍스트 추출 품질 점검 모듈 - OCR/파싱 결과 품질 판정
"""
텍스트 추출 결과의 품질을 점검하고 최적의 처리 방법을 결정합니다.

품질 판정 기준:
  - text_length: 전체 글자 수
  - empty_page_ratio: 빈 페이지 비율
  - korean_ratio: 한글 비율
  - garbage_char_ratio: 의미 없는 특수문자 비율
  - quality_score: 종합 품질 점수 (0-1)

사용 예시:
    checker = TextQualityChecker()
    result = checker.check("추출된 텍스트...")
    if result.quality_score < 0.7:
        # PDF 변환 또는 OCR 실행
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QualityCheckResult:
    """텍스트 품질 점검 결과."""
    text_length: int = 0
    char_count: int = 0
    korean_count: int = 0
    english_count: int = 0
    number_count: int = 0
    space_count: int = 0
    special_count: int = 0
    garbage_count: int = 0

    korean_ratio: float = 0.0
    english_ratio: float = 0.0
    garbage_char_ratio: float = 0.0

    empty_page_count: int = 0
    total_page_count: int = 0
    empty_page_ratio: float = 0.0

    # CID 폰트 인코딩 문제 감지
    cid_count: int = 0
    cid_ratio: float = 0.0
    cid_detected: bool = False

    quality_score: float = 0.0
    decision: str = "use_direct_text"
    decision_reason: str = ""

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text_length": self.text_length,
            "char_count": self.char_count,
            "korean_count": self.korean_count,
            "english_count": self.english_count,
            "number_count": self.number_count,
            "special_count": self.special_count,
            "garbage_count": self.garbage_count,
            "korean_ratio": round(self.korean_ratio, 4),
            "english_ratio": round(self.english_ratio, 4),
            "garbage_char_ratio": round(self.garbage_char_ratio, 4),
            "empty_page_count": self.empty_page_count,
            "total_page_count": self.total_page_count,
            "empty_page_ratio": round(self.empty_page_ratio, 4),
            "cid_count": self.cid_count,
            "cid_ratio": round(self.cid_ratio, 4),
            "cid_detected": self.cid_detected,
            "quality_score": round(self.quality_score, 4),
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "warnings": self.warnings,
        }


class TextQualityChecker:
    """텍스트 추출 품질 점검기."""

    # 품질 임계값 기본값
    DEFAULT_THRESHOLDS = {
        "min_text_length": 100,          # 최소 글자 수
        "max_empty_page_ratio": 0.3,     # 빈 페이지 비율 상한
        "min_korean_ratio": 0.2,         # 한글 비율 하한 (한국어 문서 기준)
        "max_garbage_ratio": 0.15,       # 특수문자 비율 상한
        "quality_score_threshold": 0.6,  # 품질 점수 임계값
        "min_chars_per_page": 30,        # 페이지당 최소 글자 수 (빈 페이지 판정)
        "cid_count_threshold": 20,       # CID 패턴 개수 임계값
        "cid_ratio_threshold": 0.005,    # CID 패턴 비율 임계값
    }

    # 의미 없는 문자 패턴 (OCR 오류, 깨진 문자 등)
    GARBAGE_PATTERNS = [
        r'[\ufffd\ufffe\uffff]',          # 유니코드 대체 문자
        r'[□■○●◎◇◆△▲▽▼]{3,}',            # 연속된 도형 문자
        r'[\x00-\x08\x0b\x0c\x0e-\x1f]',  # 제어 문자
        r'[가-힣]{1}[a-zA-Z]{1}[가-힣]{1}[a-zA-Z]{1}',  # 한글-영어 불규칙 교차
        r'[ㄱ-ㅎㅏ-ㅣ]{5,}',               # 연속된 자음/모음만
    ]

    def __init__(self, thresholds: Optional[dict] = None):
        """
        품질 점검기 초기화.

        Args:
            thresholds: 품질 임계값 (기본값 사용 시 None)
        """
        self.thresholds = {**self.DEFAULT_THRESHOLDS}
        if thresholds:
            self.thresholds.update(thresholds)

        # 정규식 컴파일
        self._garbage_re = re.compile('|'.join(self.GARBAGE_PATTERNS))
        self._korean_re = re.compile(r'[가-힣]')
        self._english_re = re.compile(r'[a-zA-Z]')
        self._number_re = re.compile(r'[0-9]')
        self._space_re = re.compile(r'\s')
        self._cid_re = re.compile(r'\(cid:\d+\)')  # CID 폰트 인코딩 패턴

    def check(self, text: str, page_texts: Optional[list[str]] = None) -> QualityCheckResult:
        """
        텍스트 품질 점검.

        Args:
            text: 전체 추출 텍스트
            page_texts: 페이지별 텍스트 목록 (선택)

        Returns:
            QualityCheckResult 품질 점검 결과
        """
        result = QualityCheckResult()

        if not text:
            result.decision = "need_ocr"
            result.decision_reason = "텍스트가 비어 있음"
            return result

        # 기본 통계
        result.text_length = len(text)
        result.char_count = len(text.replace(' ', '').replace('\n', '').replace('\t', ''))

        # 문자 유형별 카운트
        result.korean_count = len(self._korean_re.findall(text))
        result.english_count = len(self._english_re.findall(text))
        result.number_count = len(self._number_re.findall(text))
        result.space_count = len(self._space_re.findall(text))

        # 특수문자 및 garbage 카운트
        result.garbage_count = len(self._garbage_re.findall(text))
        result.special_count = result.char_count - (
            result.korean_count + result.english_count + result.number_count
        )

        # CID 폰트 인코딩 문제 감지
        cid_matches = self._cid_re.findall(text)
        result.cid_count = len(cid_matches)
        if result.text_length > 0:
            result.cid_ratio = result.cid_count / result.text_length

        # CID 감지 기준: count >= 20 OR ratio >= 0.005
        cid_count_threshold = self.thresholds["cid_count_threshold"]
        cid_ratio_threshold = self.thresholds["cid_ratio_threshold"]
        result.cid_detected = (
            result.cid_count >= cid_count_threshold or
            result.cid_ratio >= cid_ratio_threshold
        )

        # 비율 계산
        if result.char_count > 0:
            result.korean_ratio = result.korean_count / result.char_count
            result.english_ratio = result.english_count / result.char_count
            result.garbage_char_ratio = result.garbage_count / result.char_count

        # 페이지별 분석 (제공된 경우)
        if page_texts:
            result.total_page_count = len(page_texts)
            min_chars = self.thresholds["min_chars_per_page"]
            result.empty_page_count = sum(
                1 for p in page_texts if len(p.strip()) < min_chars
            )
            if result.total_page_count > 0:
                result.empty_page_ratio = result.empty_page_count / result.total_page_count

        # 품질 점수 계산
        result.quality_score = self._calculate_quality_score(result)

        # 경고 생성
        result.warnings = self._generate_warnings(result)

        # 처리 방법 결정
        result.decision, result.decision_reason = self._decide_action(result)

        return result

    def _calculate_quality_score(self, result: QualityCheckResult) -> float:
        """
        종합 품질 점수 계산 (0-1).

        점수 구성:
          - 텍스트 길이 점수 (20%)
          - 한글 비율 점수 (30%)
          - garbage 비율 점수 (25%)
          - 빈 페이지 비율 점수 (25%)
        """
        score = 0.0

        # 1. 텍스트 길이 점수 (0-0.2)
        min_len = self.thresholds["min_text_length"]
        if result.text_length >= min_len * 10:
            len_score = 0.2
        elif result.text_length >= min_len:
            len_score = 0.2 * (result.text_length / (min_len * 10))
        else:
            len_score = 0.1 * (result.text_length / min_len) if min_len > 0 else 0
        score += len_score

        # 2. 한글 비율 점수 (0-0.3)
        min_korean = self.thresholds["min_korean_ratio"]
        if result.korean_ratio >= min_korean:
            # 한글이 충분하면 만점
            korean_score = 0.3
        elif result.korean_ratio > 0:
            # 일부 한글이 있으면 비례 점수
            korean_score = 0.3 * (result.korean_ratio / min_korean)
        else:
            # 한글이 전혀 없으면 영어 비율로 대체 평가
            korean_score = 0.15 * result.english_ratio
        score += korean_score

        # 3. garbage 비율 점수 (0-0.25, 낮을수록 좋음)
        max_garbage = self.thresholds["max_garbage_ratio"]
        if result.garbage_char_ratio == 0:
            garbage_score = 0.25
        elif result.garbage_char_ratio < max_garbage:
            garbage_score = 0.25 * (1 - result.garbage_char_ratio / max_garbage)
        else:
            garbage_score = 0
        score += garbage_score

        # 4. 빈 페이지 비율 점수 (0-0.25, 낮을수록 좋음)
        if result.total_page_count == 0:
            # 페이지 정보 없으면 중간값
            empty_score = 0.15
        else:
            max_empty = self.thresholds["max_empty_page_ratio"]
            if result.empty_page_ratio == 0:
                empty_score = 0.25
            elif result.empty_page_ratio < max_empty:
                empty_score = 0.25 * (1 - result.empty_page_ratio / max_empty)
            else:
                empty_score = 0
        score += empty_score

        return min(score, 1.0)

    def _generate_warnings(self, result: QualityCheckResult) -> list[str]:
        """품질 경고 생성."""
        warnings = []

        if result.text_length < self.thresholds["min_text_length"]:
            warnings.append(f"텍스트 길이 부족: {result.text_length}자 (최소 {self.thresholds['min_text_length']}자)")

        if result.cid_detected:
            warnings.append(f"CID 폰트 깨짐 감지: {result.cid_count}개 패턴 (비율: {result.cid_ratio:.1%})")

        if result.korean_ratio < self.thresholds["min_korean_ratio"] and result.english_ratio < 0.3:
            warnings.append(f"한글 비율 낮음: {result.korean_ratio:.1%}")

        if result.garbage_char_ratio > self.thresholds["max_garbage_ratio"]:
            warnings.append(f"깨진 문자 비율 높음: {result.garbage_char_ratio:.1%}")

        if result.empty_page_ratio > self.thresholds["max_empty_page_ratio"]:
            warnings.append(f"빈 페이지 비율 높음: {result.empty_page_ratio:.1%} ({result.empty_page_count}/{result.total_page_count})")

        return warnings

    def _decide_action(self, result: QualityCheckResult) -> tuple[str, str]:
        """
        처리 방법 결정.

        Returns:
            (decision, reason) 튜플
            - decision: "use_direct_text" | "need_pdf_convert" | "need_ocr" | "need_manual_review"
        """
        threshold = self.thresholds["quality_score_threshold"]

        # CID 폰트 깨짐 감지 → OCR 필요 (최우선)
        if result.cid_detected:
            return "need_ocr", f"CID 폰트 깨짐 감지 ({result.cid_count}개)"

        # 텍스트가 거의 없음 → OCR 필요
        if result.text_length < self.thresholds["min_text_length"]:
            return "need_ocr", f"텍스트 부족 ({result.text_length}자)"

        # 품질 점수가 높음 → 직접 추출 결과 사용
        if result.quality_score >= threshold:
            return "use_direct_text", f"품질 양호 (점수: {result.quality_score:.2f})"

        # garbage 비율이 매우 높음 → OCR 필요
        if result.garbage_char_ratio > self.thresholds["max_garbage_ratio"] * 2:
            return "need_ocr", f"깨진 문자 과다 ({result.garbage_char_ratio:.1%})"

        # 품질이 중간 → PDF 변환 시도
        if result.quality_score >= threshold * 0.5:
            return "need_pdf_convert", f"품질 부족, PDF 변환 권장 (점수: {result.quality_score:.2f})"

        # 품질이 매우 낮음 → OCR 필요
        if result.quality_score < threshold * 0.5:
            return "need_ocr", f"품질 매우 낮음 (점수: {result.quality_score:.2f})"

        return "need_manual_review", "자동 판정 불가"

    def check_page_quality(self, page_text: str) -> dict:
        """
        단일 페이지 품질 빠른 점검.

        Returns:
            {"is_empty": bool, "char_count": int, "has_korean": bool}
        """
        text = page_text.strip()
        char_count = len(text)
        has_korean = bool(self._korean_re.search(text))
        is_empty = char_count < self.thresholds["min_chars_per_page"]

        return {
            "is_empty": is_empty,
            "char_count": char_count,
            "has_korean": has_korean,
        }


# 싱글톤 인스턴스
text_quality_checker = TextQualityChecker()


# ─────────────────────────────────────────────────────────────────────────────
# 테스트
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    checker = TextQualityChecker()

    # 테스트 케이스 1: 양호한 한국어 텍스트
    good_text = """
    본 사업은 정보화전략계획(ISP)을 수립하여 디지털 전환을 추진하는 것을 목표로 합니다.
    현황 분석, 목표 모델 수립, 이행 계획 수립 등의 과업을 수행합니다.
    사업 기간은 2026년 1월부터 12월까지이며, 총 사업비는 10억원입니다.
    주요 추진 전략으로는 클라우드 전환, AI 도입, 데이터 통합 등이 있습니다.
    """

    result1 = checker.check(good_text)
    print("=== 테스트 1: 양호한 텍스트 ===")
    print(f"품질 점수: {result1.quality_score:.2f}")
    print(f"한글 비율: {result1.korean_ratio:.1%}")
    print(f"결정: {result1.decision} - {result1.decision_reason}")
    print()

    # 테스트 케이스 2: 깨진 텍스트
    bad_text = """
    □■○●◎◇◆△▲▽▼□■○●◎◇◆△▲▽▼
    ㅁㄴㅇㄹㅎㅋㅌㅊㅍㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅗㅓㅏㅣㅠㅜㅡ
    a한b글c영d어e혼f합g
    ���깨진문자테스트���
    """

    result2 = checker.check(bad_text)
    print("=== 테스트 2: 깨진 텍스트 ===")
    print(f"품질 점수: {result2.quality_score:.2f}")
    print(f"garbage 비율: {result2.garbage_char_ratio:.1%}")
    print(f"결정: {result2.decision} - {result2.decision_reason}")
    print(f"경고: {result2.warnings}")
    print()

    # 테스트 케이스 3: 빈 텍스트
    empty_text = ""
    result3 = checker.check(empty_text)
    print("=== 테스트 3: 빈 텍스트 ===")
    print(f"품질 점수: {result3.quality_score:.2f}")
    print(f"결정: {result3.decision} - {result3.decision_reason}")
    print()

    # 테스트 케이스 4: 영어 텍스트
    english_text = """
    This is an English document about Information Strategy Planning.
    The project aims to establish digital transformation strategy.
    Key activities include current state analysis, target model design, and implementation planning.
    """

    result4 = checker.check(english_text)
    print("=== 테스트 4: 영어 텍스트 ===")
    print(f"품질 점수: {result4.quality_score:.2f}")
    print(f"영어 비율: {result4.english_ratio:.1%}")
    print(f"결정: {result4.decision} - {result4.decision_reason}")
