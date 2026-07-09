# RFP 패턴 분석 강화 메타데이터 생성 테스트 스크립트
"""
test_enhanced_metadata.py

RFP 패턴 분석 기반 메타데이터 자동 생성 기능 테스트
"""

import sys
from pathlib import Path

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.services.metadata_auto_generator_enhanced import metadata_auto_generator_enhanced
from app.services.rfp_pattern_analyzer import rfp_pattern_analyzer
import json


def test_filename_analysis():
    """파일명 패턴 분석 테스트"""
    print("\n" + "=" * 80)
    print("TEST 1: 파일명 패턴 분석")
    print("=" * 80)

    test_cases = [
        "RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp",
        "RFP_AFSIS 협력사업 활용실태 조사 및 개선방안 도출 용역.hwp",
        "RFP_AI 기반 지능형 진로교육정보망 통합 구축을 위한 정보화전략계획(ISP) 수립 사업.hwp",
        "전략및방법론_AI 기반 e-감사시스템 재구축 ISP 컨설팅.pptx",
        "환경분석_소방출동 데이터 기반, AI빅데이터 분석시스템 구축 ISP.pptx"
    ]

    for filename in test_cases:
        print(f"\n파일명: {filename}")
        result = rfp_pattern_analyzer.analyze_filename(filename)
        print(f"  프로젝트명: {result.get('project_name')}")
        print(f"  프로젝트 유형: {result.get('project_type')}")
        print(f"  문서 유형: {result.get('document_type')}")
        print(f"  기술 키워드: {result.get('technology_keywords')}")
        print(f"  도메인: {result.get('domain')}")
        print(f"  신뢰도: {result.get('confidence')}")


def test_cover_page_extraction():
    """표지(Cover Page) 추출 테스트"""
    print("\n" + "=" * 80)
    print("TEST 2: 표지(Cover Page) 추출")
    print("=" * 80)

    cover_text = """
    제안요청서

    AI 기반 e-감사시스템 재구축
    정보화전략계획(ISP) 수립

    발주기관: 한국수자원공사
    사업명: AI 기반 e-감사시스템 재구축 ISP 컨설팅
    2024년 3월
    """

    print(f"\n표지 텍스트 길이: {len(cover_text)} 자")
    result = rfp_pattern_analyzer.extract_cover_page_metadata(cover_text)
    print(f"\n제목: {result.get('title')}")
    print(f"기관명: {result.get('organization')}")
    print(f"프로젝트명: {result.get('project_name')}")
    print(f"날짜: {result.get('date')}")
    print(f"문서 유형: {result.get('document_type')}")
    print(f"키워드: {result.get('keywords')}")
    print(f"신뢰도: {result.get('confidence')}")


def test_toc_extraction():
    """목차(TOC) 추출 테스트"""
    print("\n" + "=" * 80)
    print("TEST 3: 목차(TOC) 추출")
    print("=" * 80)

    toc_text = """
    목차

    I. 사업개요 ........................... 3
        1. 추진배경 ....................... 5
        2. 사업목적 ....................... 7

    II. 추진배경 및 목적 ................... 9
        1. 현황분석 ....................... 11
        2. 문제점 도출 ..................... 13

    III. 사업범위 ......................... 15
        1. 요구사항 분석 ................... 17
        2. 시스템 설계 ..................... 19
        3. 개발 및 구축 .................... 21

    IV. 요구사항 상세 ..................... 23
        1. 기능 요구사항 ................... 25
        2. 데이터 요구사항 ................. 27
        3. 성능 요구사항 ................... 29
    """

    print(f"\n목차 텍스트 길이: {len(toc_text)} 자")
    result = rfp_pattern_analyzer.extract_toc_sections(toc_text)
    print(f"\n감지된 섹션 수: {len(result.get('sections', []))}")
    print(f"섹션 목록 (상위 10개):")
    for i, section in enumerate(result.get('sections', [])[:10], 1):
        print(f"  {i}. [{section.get('level')}단계] {section.get('title')} (페이지: {section.get('page')})")
    print(f"\n섹션 제목 목록: {result.get('section_titles')[:10]}")
    print(f"키워드: {result.get('keywords')}")
    print(f"신뢰도: {result.get('confidence')}")


def test_text_analysis():
    """텍스트 내용 분석 테스트 (표지 + 목차 + 본문 통합)"""
    print("\n" + "=" * 80)
    print("TEST 4: 텍스트 내용 종합 분석 (표지 + 목차 + 본문)")
    print("=" * 80)

    sample_text = """
    제안요청서

    AI 기반 e-감사시스템 재구축
    정보화전략계획(ISP) 수립

    사업명: AI 기반 e-감사시스템 재구축
    주관기관: 한국수자원공사
    2024년 3월

    목차

    I. 사업개요 ............... 3
    II. 추진배경 및 목적 ....... 9
    III. 사업범위 ............. 15
    IV. 요구사항 상세 ......... 23

    I. 사업개요
    본 사업은 기존 감사시스템을 AI 기술을 활용하여 재구축하고,
    감사 업무의 효율성을 높이는 것을 목표로 합니다.

    II. 추진배경 및 목적
    기존 시스템의 노후화와 AI 기술 발전에 따라 시스템 재구축이 필요합니다.

    III. 사업범위
    - 요구사항 분석
    - 시스템 설계
    - 개발 및 구축

    IV. 요구사항 상세
    1. 기능 요구사항
    2. 데이터 요구사항
    3. 성능 요구사항
    """

    print(f"\n샘플 텍스트 길이: {len(sample_text)} 자")
    result = rfp_pattern_analyzer.analyze_text_content(sample_text)

    print("\n[표지 정보]")
    cover_page = result.get('cover_page', {})
    print(f"  제목: {cover_page.get('title')}")
    print(f"  기관명: {cover_page.get('organization')}")
    print(f"  프로젝트명: {cover_page.get('project_name')}")
    print(f"  날짜: {cover_page.get('date')}")
    print(f"  신뢰도: {cover_page.get('confidence')}")

    print("\n[목차 정보]")
    toc = result.get('toc', {})
    print(f"  섹션 수: {len(toc.get('sections', []))}")
    print(f"  섹션 목록: {toc.get('section_titles', [])[:5]}")
    print(f"  신뢰도: {toc.get('confidence')}")

    print("\n[본문 분석 결과]")
    print(f"  감지된 섹션: {result.get('detected_sections', [])[:10]}")
    print(f"  기관명: {result.get('organization')}")
    print(f"  연도: {result.get('year')}")
    print(f"  키워드 (상위 10개): {result.get('keywords')[:10]}")
    print(f"  요약: {result.get('summary')[:150]}...")
    print(f"  종합 신뢰도: {result.get('confidence')}")


def test_enhanced_metadata():
    """강화된 메타데이터 생성 테스트 (표지 + 목차 포함)"""
    print("\n" + "=" * 80)
    print("TEST 5: 강화된 메타데이터 생성 (표지 + 목차 포함)")
    print("=" * 80)

    filename = "RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp"
    relative_path = "01. RFP/RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp"

    text_content = """
    제안요청서

    AI 기반 e-감사시스템 재구축
    정보화전략계획(ISP) 수립

    발주기관: 한국수자원공사
    사업명: AI 기반 e-감사시스템 재구축 ISP 컨설팅
    사업기간: 2024년 3월 ~ 12월

    목차

    I. 사업개요 .................. 3
    II. 추진배경 및 목적 .......... 9
    III. 사업범위 ................ 15
    IV. 요구사항 상세 ............ 23

    I. 사업개요
    본 사업은 AI 기술을 활용한 차세대 감사시스템을 구축합니다.

    II. 추진배경
    기존 시스템의 한계를 극복하고 AI 기반 자동화를 도입합니다.

    III. 요구사항
    - AI 기반 이상거래 탐지
    - 빅데이터 분석 기능
    - 실시간 모니터링
    """

    print(f"\n파일명: {filename}")
    print(f"경로: {relative_path}")
    print(f"텍스트 길이: {len(text_content)} 자")

    # 강화된 메타데이터 생성
    result = metadata_auto_generator_enhanced.extract_metadata(
        file_name=filename,
        file_content=text_content,
        relative_path=relative_path,
        use_rfp_patterns=True
    )

    print("\n[생성된 메타데이터]")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 표지/목차 정보 포함 여부 확인
    print("\n[표지/목차 정보 포함 확인]")
    print(f"  폴더명 포함: {'folder_name' in result}")
    print(f"  표지 정보 포함: {'cover_page' in result}")
    print(f"  목차 정보 포함: {'toc' in result}")
    if 'cover_page' in result:
        print(f"  표지 제목: {result['cover_page'].get('title', 'N/A')}")
    if 'toc' in result:
        print(f"  목차 섹션 수: {len(result['toc'].get('sections', []))}")


def test_document_classification():
    """문서 그룹 분류 테스트"""
    print("\n" + "=" * 80)
    print("TEST 4: 문서 그룹 분류")
    print("=" * 80)

    test_cases = [
        ("RFP_AI ISP.hwp", "01. RFP/"),
        ("전략및방법론_AI.pptx", "02. 제안서/01. 전략및방법론/"),
        ("환경분석_소방.pptx", "03. 산출물/01. 환경분석/"),
        ("현황분석.pptx", "03. 산출물/02. 현황분석/")
    ]

    for filename, relative_path in test_cases:
        document_group, category = rfp_pattern_analyzer.classify_document_group(filename, relative_path)
        print(f"\n파일: {filename}")
        print(f"  경로: {relative_path}")
        print(f"  문서 그룹: {document_group}")
        print(f"  카테고리: {category}")


def test_batch_keyword_extraction():
    """일괄 키워드 추출 테스트"""
    print("\n" + "=" * 80)
    print("TEST 5: 일괄 키워드 추출")
    print("=" * 80)

    file_list = [
        {
            "file_name": "RFP_AI 기반 e-감사시스템 재구축 ISP 컨설팅.hwp",
            "file_content": "AI 기반 감사시스템 ISP 컨설팅 빅데이터",
            "relative_path": "01. RFP/"
        },
        {
            "file_name": "RFP_빅데이터 플랫폼 구축 ISP.hwp",
            "file_content": "빅데이터 플랫폼 클라우드 데이터 분석",
            "relative_path": "01. RFP/"
        },
        {
            "file_name": "전략및방법론_AI 교육 시스템.pptx",
            "file_content": "AI 교육 LLM 챗봇",
            "relative_path": "02. 제안서/"
        }
    ]

    print(f"\n파일 수: {len(file_list)}")
    result = metadata_auto_generator_enhanced.extract_keywords_batch(file_list)

    print("\n[추출된 키워드]")
    print(f"전체 키워드: {result['all_keywords'][:15]}")
    print(f"기술 키워드: {result['technology_keywords']}")
    print(f"업무 키워드: {result['business_keywords']}")
    print(f"도메인 키워드: {result['domain_keywords']}")


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 80)
    print("RFP 패턴 분석 강화 메타데이터 생성 기능 테스트")
    print("표지(Cover Page) 및 목차(TOC) 추출 포함")
    print("=" * 80)

    try:
        test_filename_analysis()
        test_cover_page_extraction()
        test_toc_extraction()
        test_text_analysis()
        test_enhanced_metadata()
        test_document_classification()
        test_batch_keyword_extraction()

        print("\n" + "=" * 80)
        print("모든 테스트 완료")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR] 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
