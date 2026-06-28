# Dataset Builder 스크립트

rag_source (250개 문서, 9,956 청크)를 위한 FAISS 인덱스 빌드 스크립트입니다.

## 사전 조건

- Step 1-5 완료 상태 (웹 UI 또는 API로 이미 완료됨)
- Ollama에 `bge-m3:latest` 모델 설치됨
- 서버 API 실행 중 (port 8080)

## 사용법

### 1. 상태 확인
```bash
cd /data/weeslee/weeslee-rag/backend/databuilder
python3 check_status.py
```

### 2. Step 6: 임베딩 생성 (약 30분~1시간 소요)
```bash
# 포그라운드 실행 (진행 상황 표시)
python3 run_embed_step6.py

# 백그라운드 실행 (로그 파일로 저장)
nohup python3 run_embed_step6.py > embed_job.log 2>&1 &
tail -f embed_job.log
```

### 3. Step 7: FAISS 인덱스 빌드
```bash
python3 run_index_step7.py
```

### 4. 인덱스 활성화
```bash
python3 activate_index.py
```

## 웹 UI 대안

`https://server.weeslee.co.kr/weeslee-rag/frontend/admin.html` 접속 후:
1. Dataset Builder 탭 → Source: rag_source 선택
2. Step 6 (Embed) 버튼 클릭
3. Step 7 (Index Build) 버튼 클릭
4. 활성화 버튼 클릭

## 설정값

| 항목 | 값 |
|------|-----|
| 임베딩 모델 | bge-m3:latest (1024 차원) |
| 배치 크기 | 8 |
| 인덱스 타입 | flat |
| 메트릭 | ip (내적, 코사인 유사도) |

## 현재 상태

- **rag_source**: 250개 문서, 9,956 청크 (Step 5까지 완료)
- **staged/batch003**: 4개 문서, 306 청크 (FAISS 완료, 현재 활성)
