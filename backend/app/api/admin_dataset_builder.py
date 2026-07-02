# ============================================================
# DEPRECATED: 2026-06-12
# ============================================================
# 이 파일은 과거 Dataset Builder API 실험용 파일입니다.
# 실제 운영 라우터는 main.py에서 import되는 파일을 기준으로 합니다.
#
# 운영 파일:
#   - admin_dataset_builder_simple.py (Step 1-3)
#   - admin_dataset_builder_step4.py ~ step10.py
#
# 신규 수정은 운영 라우터 파일에만 적용하세요.
# 삭제 예정: Dataset Builder Step 1~10 통합 완료 및 안정화 확인 후
# ============================================================

# Dataset Builder 10단계 워크플로우 API (DEPRECATED)
"""
Dataset Builder 10-Step Workflow API

Step 1: Source Scan - 소스 폴더 스캔 및 documents, document_metadata 레코드 생성
Step 2: Metadata Auto - 자동 메타데이터 생성 (프로젝트명, 기관명, 연도 등)

[DEPRECATED] 이 모듈은 더 이상 main.py에서 import되지 않습니다.
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth import require_admin_token
from app.core.config import settings
from app.core.database import get_db
from app.core.mappings import mappings
from app.models.document import Document
from app.models.document_metadata import DocumentMetadata, MetaStatus

router = APIRouter(
    prefix="/admin/dataset-builder",
    tags=["Admin - Dataset Builder"],
    dependencies=[Depends(require_admin_token)],
)

# 설정 및 매핑 (config.py, entity_mappings.json에서 로드)
SUPPORTED_EXTENSIONS = mappings.SUPPORTED_EXTENSIONS
RAG_SOURCE_ROOT = settings.rag_source_root
SOURCE_ID_MAP = mappings.SOURCE_ID_MAP
CATEGORY_ID_MAP = mappings.CATEGORY_ID_MAP


# ── Request/Response Models ─────────────────────────────────────────────────


class ScanRequest(BaseModel):
    """Step 1: Source Scan 요청"""
    source_id: str
    overwrite: bool = False


class ScanResponse(BaseModel):
    """Step 1: Source Scan 응답"""
    success: bool
    total_files: int
    documents: int
    by_source: dict  # 소스별 파일 수 {"src_rfp": 10, "src_proposal": 20, "src_output": 15}
    excluded: int    # 제외된 파일 수 (지원하지 않는 확장자)
    message: str


class MetadataAutoRequest(BaseModel):
    """Step 2: Metadata Auto 요청"""
    only_missing: bool = True
    overwrite: bool = False


class MetadataAutoResponse(BaseModel):
    """Step 2: Metadata Auto 응답"""
    success: bool
    processed: int
    updated: int
    skipped: int
    message: str


# ── Helper Functions ────────────────────────────────────────────────────────


def scan_folder(folder_path: str, extensions: set) -> tuple[List[dict], int]:
    """폴더를 재귀적으로 스캔하여 파일 목록 반환

    Returns:
        (files, excluded_count): 지원 파일 목록과 제외된 파일 수
    """
    files = []
    excluded_count = 0

    if not os.path.exists(folder_path):
        return files, excluded_count

    for root, dirs, filenames in os.walk(folder_path):
        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext in extensions:
                filepath = os.path.join(root, filename)
                stat = os.stat(filepath)
                files.append({
                    "filename": filename,
                    "filepath": filepath,
                    "extension": ext.lstrip("."),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime),
                })
            elif ext:  # 확장자는 있지만 지원하지 않는 파일
                excluded_count += 1

    return files, excluded_count


def _is_sentence_fragment(text: str) -> bool:
    """
    문장 일부인지 검사

    다음 패턴이 있으면 문장 일부로 간주:
    - 조사로 끝남 (을, 를, 의, 에, 로, 와, 과, 이, 가 등)
    - 동사/형용사 어미로 끝남 (합니다, 했습니다, 됩니다 등)
    - 불완전한 문장 패턴
    """
    import re

    # 조사로 끝나는 경우
    if re.search(r'[을를의에로와과이가은는도부터까지만]$', text):
        return True

    # 동사/형용사 어미로 끝나는 경우
    verb_endings = [
        '합니다', '했습니다', '됩니다', '되었습니다', '수행합니다',
        '진행합니다', '완료되었습니다', '시작됩니다', '종료됩니다'
    ]
    if any(text.endswith(ending) for ending in verb_endings):
        return True

    # 연결어미로 끝나는 경우
    if re.search(r'(하여|하고|하며|되어|되고|되며)$', text):
        return True

    return False


def _is_valid_project_name(text: str) -> bool:
    """
    유효한 프로젝트명인지 검증

    다음 조건을 만족해야 함:
    - 길이 10~150자
    - 문장 일부가 아님
    - 일반적인 문서명이 아님
    """
    if not text or len(text) < 10 or len(text) > 150:
        return False

    # 문장 일부인 경우 제외
    if _is_sentence_fragment(text):
        return False

    # 일반적인 문서명 패턴 제외
    generic_names = [
        r'^(환경|현황|목표|전략|방법론|기술|기능|관리|지원|계획|분석|설계|개발|구축|이행)',
        r'^(사업|프로젝트|연구|개발|구축|수행|추진|진행|완료)',
        r'(의\s+이해|의\s+개요|의\s+현황|의\s+목표|의\s+방향|의\s+전략)$'
    ]

    for pattern in generic_names:
        if re.search(pattern, text):
            return False

    return True


def extract_project_name_from_path(filepath: str) -> tuple[str, float]:
    """
    폴더 경로에서 실제 프로젝트명 추출

    경로 예시: W:\\01. 국내사업폴더\\202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP\\01. 제안서\\...
    → "AX기반의 차세대 업무 시스템 구축을 위한 ISMP"

    Returns:
        tuple[str, float]: (프로젝트명, 신뢰도)
    """
    import re
    import os

    # 경로를 정규화하고 분리
    normalized_path = filepath.replace('\\\\', '/').replace('\\', '/')
    parts = normalized_path.split('/')

    # "202603. AX기반의..." 같은 패턴 찾기
    for part in parts:
        # 연도코드(6자리). 프로젝트명 패턴
        match = re.match(r'^(\d{6})\.\s*(.+)$', part)
        if match:
            project_name = match.group(2).strip()
            # 너무 짧거나 긴 경우 제외
            if 10 <= len(project_name) <= 150:
                return project_name, 0.90

    # 백업: "[제안실주]" 같은 표시가 있는 폴더 다음 항목
    for i, part in enumerate(parts):
        if part.startswith('[제안실주]') or part.startswith('[제안중]'):
            if i + 1 < len(parts):
                project_name = parts[i + 1]
                # 연도코드 제거
                project_name = re.sub(r'^\d{6}\.\s*', '', project_name)
                if 10 <= len(project_name) <= 150:
                    return project_name, 0.80

    # 추가: 상위 폴더에서 프로젝트명 후보 찾기
    # "01. 제안서", "02. 계약", "03. 산출물" 등을 제외한 폴더명 중 가장 긴 것
    project_candidates = []
    exclude_patterns = [
        r'^\d+\.\s*(제안서|계약|산출물|RFP|요청서|보고서|발표|회의|참고|기타|temp|tmp)',
        r'^(문서|자료|참고자료|backup|old|archive|test)'
    ]

    for part in reversed(parts):  # 역순으로 검사 (파일에 가까운 폴더부터)
        # 제외 패턴과 매칭되면 스킵
        if any(re.match(pattern, part, re.IGNORECASE) for pattern in exclude_patterns):
            continue

        # 연도코드 제거
        cleaned = re.sub(r'^\d{6}\.\s*', '', part).strip()

        # 길이 제약 및 검증
        if 10 <= len(cleaned) <= 150 and not _is_sentence_fragment(cleaned):
            project_candidates.append((cleaned, len(cleaned)))

    # 가장 긴 후보 선택 (일반적으로 더 구체적인 프로젝트명)
    if project_candidates:
        project_candidates.sort(key=lambda x: x[1], reverse=True)
        return project_candidates[0][0], 0.70

    # 최후 수단: 파일명에서 추출 (검증 후)
    filename = Path(filepath).stem
    extracted = extract_project_name_from_filename(filename)

    # 파일명 추출 결과 검증
    if _is_valid_project_name(extracted):
        return extracted, 0.50

    # 검증 실패 시 빈 문자열 반환
    return "", 0.0


def extract_project_name_from_filename(filename: str) -> str:
    """파일명에서 프로젝트명 추출 (기존 로직)"""
    name = filename

    prefixes = [
        "RFP_", "전략및방법론_", "기술및기능_", "프로젝트관리_",
        "프로젝트지원_", "연구과제_", "감리_", "PMO_", "PoC_",
        "환경분석_", "현황분석_", "목표모델_", "이행계획_"
    ]

    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # 언더스코어로 시작하는 경우 첫 부분 제거
    if "_" in name and not any(name.startswith(p) for p in prefixes):
        parts = name.split("_", 1)
        if len(parts) > 1 and len(parts[0]) < 10:
            name = parts[1]

    return name.strip()


def extract_organization_from_path(filepath: str, project_name: str = None) -> tuple[str, float]:
    """
    폴더 경로 또는 프로젝트명에서 기관명 추출

    Returns:
        tuple[str, float]: (기관명, 신뢰도)
    """
    import re

    # 기관명 패턴
    org_suffixes = (
        "부", "청", "처", "공사", "공단", "연구원", "연구소", "재단",
        "위원회", "센터", "병원", "대학교", "대학", "학교", "진흥원",
        "협회", "본부", "관리원", "교육원", "평가원"
    )

    # 기관명이 아닌 일반 단어 필터 (블랙리스트)
    excluded_orgs = {
        "출처", "참조", "참고", "자료", "문서", "내용", "요약", "개요",
        "배경", "목적", "범위", "대상", "기간", "방법", "결과", "결론"
    }

    # 프로젝트명에서 기관명 찾기 ("법무부_디지털플랫폼..." 형태)
    if project_name:
        match = re.match(r'^([^_]+)_', project_name)
        if match:
            org_candidate = match.group(1)
            if org_candidate.endswith(org_suffixes) and org_candidate not in excluded_orgs:
                return org_candidate, 0.85

    # 경로를 정규화하고 분리
    normalized_path = filepath.replace('\\\\', '/').replace('\\', '/')
    parts = normalized_path.split('/')
    for part in parts:
        # 연도코드 제거
        part = re.sub(r'^\d{6}\.\s*', '', part)

        # 기관명 패턴 검색
        match = re.search(r'([가-힣A-Za-z·&-]{2,30}(?:' + '|'.join(org_suffixes) + r'))', part)
        if match:
            org = match.group(1)
            # 블랙리스트 체크 및 길이 제약
            if len(org) <= 30 and org not in excluded_orgs:
                return org, 0.70

    return None, 0.0


def extract_section_types_from_path(filepath: str) -> dict:
    """
    폴더 경로에서 산출물 유형 추출

    Returns:
        dict: {
            'deliverable_section': str,
            'proposal_section': str,
            'confidence': float
        }
    """
    import re

    # 경로를 정규화하고 분리
    normalized_path = filepath.replace('\\\\', '/').replace('\\', '/')
    parts = normalized_path.split('/')

    deliverable_section = None
    proposal_section = None
    confidence = 0.0

    for part in parts:
        # "02. 환경분석", "01. 제안서" 등의 패턴
        match = re.match(r'^\d+\.\s*(.+)$', part)
        if not match:
            continue

        section = match.group(1).strip()

        # 산출물 유형 매칭
        if any(keyword in section for keyword in ['환경분석', '환경 분석']):
            deliverable_section = '환경분석'
            confidence = max(confidence, 0.90)
        elif any(keyword in section for keyword in ['현황분석', '현황 분석']):
            deliverable_section = '현황분석'
            confidence = max(confidence, 0.90)
        elif any(keyword in section for keyword in ['목표모델', '목표 모델']):
            deliverable_section = '목표모델'
            confidence = max(confidence, 0.90)
        elif any(keyword in section for keyword in ['이행계획', '이행 계획']):
            deliverable_section = '이행계획'
            confidence = max(confidence, 0.90)
        elif any(keyword in section for keyword in ['사업수행', '사업 수행']):
            deliverable_section = '사업수행'
            confidence = max(confidence, 0.85)

        # 제안서 관련
        if any(keyword in section for keyword in ['제안서', '제안 서', 'Proposal']):
            proposal_section = '제안서'
            confidence = max(confidence, 0.90)
        elif any(keyword in section for keyword in ['RFP', '제안요청서', '제안요청 서']):
            proposal_section = 'RFP'
            confidence = max(confidence, 0.95)

    return {
        'deliverable_section': deliverable_section,
        'proposal_section': proposal_section,
        'confidence': confidence
    }


def extract_project_name(filename: str) -> str:
    """
    하위 호환성을 위한 래퍼 함수
    filepath가 아닌 filename만 받는 기존 호출을 지원
    """
    return extract_project_name_from_filename(filename)


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.post("/step1/scan", response_model=ScanResponse)
async def step1_source_scan(request: ScanRequest, db: Session = Depends(get_db)):
    """
    Step 1: Source Scan

    - 네트워크 마운트 경로의 RAG 소스 폴더를 스캔
    - documents 테이블에 파일 정보 저장
    - document_metadata 테이블에 초기 레코드 생성 (meta_status='registered')
    """
    try:
        if not os.path.exists(RAG_SOURCE_ROOT):
            raise HTTPException(
                status_code=404,
                detail=f"RAG 소스 폴더를 찾을 수 없습니다: {RAG_SOURCE_ROOT}"
            )

        total_files = 0
        documents_created = 0
        total_excluded = 0
        by_source = {"src_rfp": 0, "src_proposal": 0, "src_output": 0}

        # 01. RFP 폴더 스캔
        rfp_folder = os.path.join(RAG_SOURCE_ROOT, "01. RFP")
        if os.path.exists(rfp_folder):
            files, excluded = scan_folder(rfp_folder, SUPPORTED_EXTENSIONS)
            total_excluded += excluded

            for file_info in files:
                # file_path + source_id 조합으로 중복 체크
                existing_meta = db.query(DocumentMetadata).filter(
                    DocumentMetadata.file_path == file_info["filepath"],
                    DocumentMetadata.source_id == request.source_id
                ).first()

                if existing_meta:
                    if request.overwrite:
                        # 기존 Document 레코드 업데이트
                        existing_doc = db.query(Document).filter(
                            Document.id == existing_meta.document_id
                        ).first()
                        if existing_doc:
                            existing_doc.filename = file_info["filename"]
                            existing_doc.file_size = file_info["size"]
                            existing_doc.file_extension = file_info["extension"]
                            existing_doc.updated_at = datetime.utcnow()
                else:
                    # 새로운 Document + DocumentMetadata 생성
                    new_doc = Document(
                        filename=file_info["filename"],
                        file_path=file_info["filepath"],
                        file_size=file_info["size"],
                        file_extension=file_info["extension"],
                        status="registered",
                    )
                    db.add(new_doc)
                    db.flush()  # ID 생성

                    # document_metadata 레코드 생성
                    new_meta = DocumentMetadata(
                        document_id=new_doc.id,
                        source_id=request.source_id,
                        file_path=file_info["filepath"],
                        category_id="cat_rfp",
                        meta_status=MetaStatus.REGISTERED.value,
                        include_in_rag=True,
                        include_in_graph=True,
                        include_in_wiki=True,
                    )
                    db.add(new_meta)
                    documents_created += 1

                total_files += 1
                by_source["src_rfp"] += 1

        # 02. 제안서 폴더 스캔
        proposal_folder = os.path.join(RAG_SOURCE_ROOT, "02. 제안서")
        if os.path.exists(proposal_folder):
            for category_folder in os.listdir(proposal_folder):
                category_path = os.path.join(proposal_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files, excluded = scan_folder(category_path, SUPPORTED_EXTENSIONS)
                total_excluded += excluded

                for file_info in files:
                    # file_path + source_id 조합으로 중복 체크
                    existing_meta = db.query(DocumentMetadata).filter(
                        DocumentMetadata.file_path == file_info["filepath"],
                        DocumentMetadata.source_id == request.source_id
                    ).first()

                    if existing_meta:
                        if request.overwrite:
                            # 기존 Document 레코드 업데이트
                            existing_doc = db.query(Document).filter(
                                Document.id == existing_meta.document_id
                            ).first()
                            if existing_doc:
                                existing_doc.filename = file_info["filename"]
                                existing_doc.file_size = file_info["size"]
                                existing_doc.file_extension = file_info["extension"]
                                existing_doc.updated_at = datetime.utcnow()
                    else:
                        # 새로운 Document + DocumentMetadata 생성
                        new_doc = Document(
                            filename=file_info["filename"],
                            file_path=file_info["filepath"],
                            file_size=file_info["size"],
                            file_extension=file_info["extension"],
                            status="registered",
                        )
                        db.add(new_doc)
                        db.flush()

                        new_meta = DocumentMetadata(
                            document_id=new_doc.id,
                            source_id=request.source_id,
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        documents_created += 1

                    total_files += 1
                    by_source["src_proposal"] += 1

        # 03. 산출물 폴더 스캔
        output_folder = os.path.join(RAG_SOURCE_ROOT, "03. 산출물")
        if os.path.exists(output_folder):
            for category_folder in os.listdir(output_folder):
                category_path = os.path.join(output_folder, category_folder)
                if not os.path.isdir(category_path):
                    continue

                category_id = CATEGORY_ID_MAP.get(category_folder, f"cat_{category_folder}")
                files, excluded = scan_folder(category_path, SUPPORTED_EXTENSIONS)
                total_excluded += excluded

                for file_info in files:
                    # file_path + source_id 조합으로 중복 체크
                    existing_meta = db.query(DocumentMetadata).filter(
                        DocumentMetadata.file_path == file_info["filepath"],
                        DocumentMetadata.source_id == request.source_id
                    ).first()

                    if existing_meta:
                        if request.overwrite:
                            # 기존 Document 레코드 업데이트
                            existing_doc = db.query(Document).filter(
                                Document.id == existing_meta.document_id
                            ).first()
                            if existing_doc:
                                existing_doc.filename = file_info["filename"]
                                existing_doc.file_size = file_info["size"]
                                existing_doc.file_extension = file_info["extension"]
                                existing_doc.updated_at = datetime.utcnow()
                    else:
                        # 새로운 Document + DocumentMetadata 생성
                        new_doc = Document(
                            filename=file_info["filename"],
                            file_path=file_info["filepath"],
                            file_size=file_info["size"],
                            file_extension=file_info["extension"],
                            status="registered",
                        )
                        db.add(new_doc)
                        db.flush()

                        new_meta = DocumentMetadata(
                            document_id=new_doc.id,
                            source_id=request.source_id,
                            file_path=file_info["filepath"],
                            category_id=category_id,
                            meta_status=MetaStatus.REGISTERED.value,
                            include_in_rag=True,
                            include_in_graph=True,
                            include_in_wiki=True,
                        )
                        db.add(new_meta)
                        documents_created += 1

                    total_files += 1
                    by_source["src_output"] += 1

        db.commit()

        return ScanResponse(
            success=True,
            total_files=total_files,
            documents=documents_created,
            by_source=by_source,
            excluded=total_excluded,
            message=f"Source Scan 완료: {total_files}개 파일 스캔, {documents_created}개 문서 등록, {total_excluded}개 파일 제외됨"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Source Scan 실패: {str(e)}")


@router.post("/step2/metadata-auto", response_model=MetadataAutoResponse)
async def step2_metadata_auto(request: MetadataAutoRequest, db: Session = Depends(get_db)):
    """
    Step 2: Metadata Auto

    - 파일명에서 프로젝트명 추출
    - meta_status를 'metadata_suggested'로 변경
    - 자동 추출된 메타데이터는 confidence 필드에 0.5 설정
    """
    try:
        # meta_status가 'registered'인 레코드 조회
        query = db.query(DocumentMetadata)

        if request.only_missing:
            query = query.filter(DocumentMetadata.meta_status == MetaStatus.REGISTERED.value)

        metadata_list = query.all()

        processed = 0
        updated = 0
        skipped = 0

        for metadata in metadata_list:
            # Document 조회
            doc = db.query(Document).filter(Document.id == metadata.document_id).first()
            if not doc:
                skipped += 1
                continue

            # 이미 메타데이터가 있고 overwrite가 False면 건너뜀
            if metadata.project_name and not request.overwrite:
                skipped += 1
                continue

            # 파일 경로에서 메타데이터 추출
            filepath = metadata.file_path

            # 프로젝트명 추출
            project_name, pn_confidence = extract_project_name_from_path(filepath)

            # 기관명 추출
            organization, org_confidence = extract_organization_from_path(filepath, project_name)

            # 산출물 유형 추출
            section_info = extract_section_types_from_path(filepath)

            # 메타데이터 업데이트
            metadata.project_name = project_name
            metadata.project_name_confidence = pn_confidence

            if organization and org_confidence >= 0.70:
                metadata.organization = organization

            if section_info['deliverable_section']:
                metadata.deliverable_section = section_info['deliverable_section']

            if section_info['proposal_section']:
                metadata.proposal_section = section_info['proposal_section']

            metadata.meta_status = MetaStatus.METADATA_SUGGESTED.value
            metadata.updated_at = datetime.utcnow()

            updated += 1
            processed += 1

        db.commit()

        return MetadataAutoResponse(
            success=True,
            processed=processed,
            updated=updated,
            skipped=skipped,
            message=f"Metadata Auto 완료: {processed}개 처리, {updated}개 업데이트, {skipped}개 건너뜀"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Metadata Auto 실패: {str(e)}")


@router.get("/stats")
async def get_dataset_builder_stats(db: Session = Depends(get_db)):
    """
    Dataset Builder 통계 조회

    - 전체 문서 수
    - Step별 문서 수
    - source_id별 문서 수
    """
    try:
        # 전체 문서 수
        total_documents = db.query(func.count(Document.id)).scalar()

        # 전체 메타데이터 수
        total_metadata = db.query(func.count(DocumentMetadata.id)).scalar()

        # meta_status별 카운트
        status_counts = {}
        status_stats = db.query(
            DocumentMetadata.meta_status,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.meta_status).all()

        for status, count in status_stats:
            status_counts[status or "registered"] = count

        # source_id별 카운트
        source_counts = {}
        source_stats = db.query(
            DocumentMetadata.source_id,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.source_id).all()

        for source_id, count in source_stats:
            source_counts[source_id or "unknown"] = count

        return {
            "success": True,
            "total_documents": total_documents,
            "total_metadata": total_metadata,
            "status_counts": status_counts,
            "source_counts": source_counts,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")


@router.get("/inventory/list")
async def get_inventory_list(source_id: Optional[str] = None):
    """
    OCR Inventory 목록을 반환합니다.
    Wiki 생성 메뉴에서 프로젝트 목록을 표시할 때 사용합니다.
    
    Args:
        source_id: 특정 source_id의 inventory만 조회 (선택)
    
    Returns:
        inventory: 프로젝트별 문서 목록
        total_folders: 전체 폴더 수
    """
    try:
        # 기본 경로: data/staged/project_inventory.json
        inventory_path = STAGED_DIR / "project_inventory.json"
        
        # source_id가 지정된 경우 해당 inventory 파일 사용
        if source_id:
            source_inventory = STAGED_DIR / f"{source_id}_inventory.json"
            if source_inventory.exists():
                inventory_path = source_inventory
        
        if not inventory_path.exists():
            return {
                "success": False,
                "inventory": {},
                "total_folders": 0,
                "message": "Inventory 파일이 존재하지 않습니다."
            }
        
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        
        return {
            "success": True,
            "inventory": inventory,
            "total_folders": len(inventory),
            "source": inventory_path.name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inventory 조회 실패: {str(e)}")
