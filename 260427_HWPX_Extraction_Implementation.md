# 2026-04-27 HWPX 직접 추출 경로 추가

## 1. 목적

실제 RFP 문서가 `HWPX` 형식이므로, RFP 기반 추천 품질을 높이기 위해 추출기 단계에서 HWPX를 직접 처리하도록 보강했다.

## 2. 구현 내용

### 2.1 새 추출기 추가

- `backend/app/extractors/hwpx_extractor.py`

동작 방식:

1. HWPX ZIP 파일을 연다.
2. `Preview/PrvText.txt`가 있으면 우선 사용한다.
3. 없으면 `Contents/section*.xml`을 순회한다.
4. XML 내부 텍스트를 합쳐서 하나의 본문으로 만든다.

### 2.2 추출기 라우팅 연결

- `backend/app/extractors/extractor.py`

HWPX 확장자가 unified extractor에 포함되도록 추가했다.

### 2.3 공개 export 연결

- `backend/app/extractors/__init__.py`

HWPX extractor를 패키지 레벨에서 import 가능하게 정리했다.

## 3. 검증

문법 검사는 통과했다.

- `python -m py_compile backend/app/extractors/hwpx_extractor.py backend/app/extractors/extractor.py backend/app/extractors/__init__.py`

## 4. 의미

이제 RFP 원본이 HWPX로 들어와도 별도 수동 추출 없이 파이프라인에 태울 수 있다.
이 변경은 `RFP -> proposal` 추천 정확도와 재현성을 높이는 1차 기반 작업이다.

## 5. 다음 작업

1. 서버 반영 후 실제 HWPX RFP 재추출
2. 추출 텍스트 품질 점검
3. RFP 문서의 제목/섹션/요구사항을 구조화 메타데이터로 저장
4. `RFP -> proposal` 관계 그래프 반영
