# 지식원 선택 기능 상세 설계서

**작성일:** 2026-04-22
**버전:** 1.0
**관련 파일:** PromptoRAG_UI_v1.0.html (우측 패널 - 지식원 선택)

---

## 1. 기능 개요

### 1.1 목적

RAG(Retrieval-Augmented Generation) 시스템에서 AI가 답변 생성 시 참조할 **문서 컬렉션(지식원)**을 선택하는 기능입니다.

### 1.2 핵심 요구사항

| 구분 | 요구사항 |
|------|----------|
| **전체 문서 저장소** | 항상 고정 표시, VectorDB 전체 컬렉션 통합 검색 |
| **카테고리 관리** | 사용자가 업로드한 문서를 카테고리별로 분류 |
| **문서 업로드** | 새 카테고리 생성 또는 기존 카테고리에 문서 추가 |
| **VectorDB 연동** | 각 카테고리 = VectorDB의 컬렉션, 문서 수 실시간 조회 |
| **다중 선택** | 여러 지식원을 동시에 선택하여 통합 검색 가능 |

### 1.3 현재 UI 구조

```
┌─────────────────────────────────────┐
│ 📚 지식원 선택                    [?]│
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 📁 전체 문서 저장소        ✓   │ │  ← 고정 (삭제 불가)
│ │    문서 2,847개                 │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 🏗 과기정통부 사업 문서          │ │  ← 카테고리 (수정/삭제 가능)
│ │    문서 412개                   │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ ⚖️ 정책/법령 문서                │ │
│ │    문서 1,203개                 │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 📂 부서 공유 문서                │ │
│ │    문서 89개                    │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 👤 개인 업로드 문서              │ │
│ │    문서 14개                    │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [＋ 문서 업로드]                    │
└─────────────────────────────────────┘
```

---

## 2. 데이터 모델 설계

### 2.1 지식원 유형 정의

| 유형 코드 | 유형명 | 설명 | 삭제 가능 | 소유자 |
|-----------|--------|------|-----------|--------|
| `global` | 전체 문서 저장소 | 모든 컬렉션 통합 (가상) | ❌ | 시스템 |
| `organization` | 조직 공유 | 전사/부서 공유 문서 | 관리자만 | 조직 |
| `project` | 프로젝트 | 특정 프로젝트 관련 | 관리자만 | 프로젝트 |
| `personal` | 개인 업로드 | 사용자 개인 문서 | ✅ | 사용자 |

### 2.2 데이터베이스 스키마

```sql
-- =====================================================
-- 지식원(Knowledge Source) 테이블
-- =====================================================
CREATE TABLE knowledge_sources (
    id              INT PRIMARY KEY AUTO_INCREMENT,

    -- 기본 정보
    name            VARCHAR(100) NOT NULL,          -- 표시명 (예: "과기정통부 사업 문서")
    description     TEXT,                           -- 설명
    icon            VARCHAR(10) DEFAULT '📁',       -- 아이콘 이모지

    -- 유형 및 권한
    ks_type         ENUM('global', 'organization', 'project', 'personal')
                    DEFAULT 'personal',
    access_level    TINYINT DEFAULT 1,              -- 접근 권한 레벨 (1=일반, 2=제한, 3=기밀)
    is_system       BOOLEAN DEFAULT FALSE,          -- 시스템 고정 항목 여부
    is_active       BOOLEAN DEFAULT TRUE,           -- 활성화 여부

    -- 소유 정보
    owner_id        INT,                            -- 소유자 (personal 타입)
    dept_id         INT,                            -- 부서 (organization 타입)

    -- VectorDB 연동
    collection_name VARCHAR(100) UNIQUE NOT NULL,   -- VectorDB 컬렉션명
    doc_count       INT DEFAULT 0,                  -- 문서 수 (캐시)
    chunk_count     INT DEFAULT 0,                  -- 청크 수 (캐시)

    -- 정렬 및 표시
    sort_order      INT DEFAULT 100,                -- 표시 순서

    -- 타임스탬프
    last_updated_at DATETIME,                       -- 마지막 문서 업데이트
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME ON UPDATE CURRENT_TIMESTAMP,

    -- 외래 키
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (dept_id) REFERENCES departments(id) ON DELETE SET NULL,

    -- 인덱스
    INDEX idx_ks_type (ks_type),
    INDEX idx_ks_owner (owner_id),
    INDEX idx_ks_active (is_active)
);

-- =====================================================
-- 문서(Document) 테이블
-- =====================================================
CREATE TABLE documents (
    id              INT PRIMARY KEY AUTO_INCREMENT,

    -- 소속 지식원
    ks_id           INT NOT NULL,

    -- 파일 정보
    title           VARCHAR(500) NOT NULL,          -- 문서 제목
    file_name       VARCHAR(255) NOT NULL,          -- 원본 파일명
    file_path       VARCHAR(500),                   -- 저장 경로
    file_type       VARCHAR(20) NOT NULL,           -- 파일 확장자 (pdf, hwp, docx 등)
    file_size       BIGINT DEFAULT 0,               -- 파일 크기 (bytes)

    -- 문서 메타
    page_count      INT,                            -- 페이지 수
    author          VARCHAR(100),                   -- 작성자
    doc_date        DATE,                           -- 문서 작성일

    -- 처리 상태
    status          ENUM('pending', 'processing', 'completed', 'failed')
                    DEFAULT 'pending',
    error_message   TEXT,                           -- 처리 실패 시 오류 메시지

    -- 청크 정보
    chunk_count     INT DEFAULT 0,                  -- 생성된 청크 수

    -- 업로드 정보
    uploaded_by     INT,                            -- 업로드한 사용자
    uploaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    processed_at    DATETIME,                       -- 처리 완료 시각

    -- 외래 키
    FOREIGN KEY (ks_id) REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,

    -- 인덱스
    INDEX idx_doc_ks (ks_id),
    INDEX idx_doc_status (status),
    INDEX idx_doc_type (file_type)
);

-- =====================================================
-- 문서 청크(Document Chunk) 테이블
-- =====================================================
CREATE TABLE document_chunks (
    id              INT PRIMARY KEY AUTO_INCREMENT,

    -- 소속 문서
    doc_id          INT NOT NULL,

    -- 청크 정보
    chunk_index     INT NOT NULL,                   -- 청크 순서 (0부터 시작)
    chunk_text      TEXT NOT NULL,                  -- 청크 텍스트

    -- 위치 정보
    page_num        INT,                            -- 페이지 번호
    start_char      INT,                            -- 시작 문자 위치
    end_char        INT,                            -- 끝 문자 위치

    -- 토큰 정보
    token_count     INT,                            -- 토큰 수

    -- VectorDB 연동
    vector_id       VARCHAR(100),                   -- VectorDB 벡터 ID

    -- 타임스탬프
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 외래 키
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,

    -- 인덱스
    INDEX idx_chunk_doc (doc_id),
    UNIQUE INDEX idx_chunk_vector (vector_id)
);

-- =====================================================
-- 초기 데이터: 시스템 고정 지식원
-- =====================================================
INSERT INTO knowledge_sources (
    name, description, icon, ks_type, is_system, collection_name, sort_order
) VALUES (
    '전체 문서 저장소',
    '시스템에 등록된 모든 문서를 통합 검색합니다.',
    '📁',
    'global',
    TRUE,
    '_all_',  -- 특수 컬렉션명: 전체 통합 검색 의미
    0
);
```

### 2.3 VectorDB 컬렉션 구조 (Chroma)

```python
# VectorDB 컬렉션 설계

# 컬렉션 명명 규칙
# - 조직: org_{dept_id}_{name_slug}
# - 프로젝트: prj_{project_id}_{name_slug}
# - 개인: usr_{user_id}_{name_slug}

# 예시:
# - org_1_policy_law           → 정책/법령 문서 (부서 ID 1)
# - prj_123_isp_2026           → ISP 2026 프로젝트
# - usr_42_personal            → 사용자 42의 개인 문서

# 메타데이터 스키마
{
    "doc_id": int,              # documents 테이블 ID
    "ks_id": int,               # knowledge_sources 테이블 ID
    "chunk_index": int,         # 청크 순서
    "page_num": int,            # 페이지 번호
    "file_type": str,           # 파일 유형
    "doc_title": str,           # 문서 제목
    "doc_date": str,            # 문서 작성일 (YYYY-MM-DD)
    "uploaded_at": str,         # 업로드 일시 (ISO 8601)
}
```

---

## 3. API 설계

### 3.1 지식원 목록 조회

```
GET /api/v1/knowledge-sources
```

**Query Parameters:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `type` | string | ❌ | 필터: global, organization, project, personal |
| `include_counts` | boolean | ❌ | 문서/청크 수 포함 여부 (기본: true) |

**Response:**

```json
{
  "success": true,
  "data": {
    "total_stats": {
      "collection_count": 5,
      "document_count": 2847,
      "chunk_count": 28470
    },
    "knowledge_sources": [
      {
        "id": 1,
        "name": "전체 문서 저장소",
        "description": "시스템에 등록된 모든 문서를 통합 검색합니다.",
        "icon": "📁",
        "ks_type": "global",
        "is_system": true,
        "collection_name": "_all_",
        "doc_count": 2847,
        "chunk_count": 28470,
        "is_selectable": true,
        "is_deletable": false,
        "last_updated_at": "2026-04-22T10:30:00Z"
      },
      {
        "id": 2,
        "name": "과기정통부 사업 문서",
        "description": "과학기술정보통신부 관련 ISP/ISMP 사업 문서",
        "icon": "🏗",
        "ks_type": "organization",
        "is_system": false,
        "collection_name": "org_1_msit_projects",
        "doc_count": 412,
        "chunk_count": 4120,
        "is_selectable": true,
        "is_deletable": false,
        "last_updated_at": "2026-04-20T14:22:00Z"
      },
      {
        "id": 5,
        "name": "개인 업로드 문서",
        "description": null,
        "icon": "👤",
        "ks_type": "personal",
        "is_system": false,
        "collection_name": "usr_42_personal",
        "doc_count": 14,
        "chunk_count": 140,
        "is_selectable": true,
        "is_deletable": true,
        "last_updated_at": "2026-04-21T09:15:00Z"
      }
    ]
  }
}
```

### 3.2 지식원 생성 (새 카테고리)

```
POST /api/v1/knowledge-sources
```

**Request Body:**

```json
{
  "name": "디지털플랫폼정부 자료",
  "description": "디지털플랫폼정부위원회 관련 정책 문서",
  "icon": "🏛",
  "ks_type": "organization",
  "dept_id": 1
}
```

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 6,
    "name": "디지털플랫폼정부 자료",
    "collection_name": "org_1_digital_platform",
    "doc_count": 0,
    "created_at": "2026-04-22T11:00:00Z"
  },
  "message": "지식원이 생성되었습니다."
}
```

### 3.3 지식원 수정

```
PUT /api/v1/knowledge-sources/{id}
```

**Request Body:**

```json
{
  "name": "디지털플랫폼정부 정책자료",
  "description": "업데이트된 설명",
  "icon": "🏢"
}
```

### 3.4 지식원 삭제

```
DELETE /api/v1/knowledge-sources/{id}
```

**제약 조건:**
- `is_system = true`인 항목은 삭제 불가
- `ks_type = 'personal'`이 아닌 경우 관리자 권한 필요
- 삭제 시 관련 documents, document_chunks, VectorDB 컬렉션 함께 삭제

**Response:**

```json
{
  "success": true,
  "message": "지식원 및 관련 문서가 삭제되었습니다.",
  "data": {
    "deleted_documents": 14,
    "deleted_chunks": 140
  }
}
```

### 3.5 문서 업로드

```
POST /api/v1/knowledge-sources/{ks_id}/documents
Content-Type: multipart/form-data
```

**Form Data:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `files` | File[] | ✅ | 업로드할 파일 (복수 가능) |
| `category_name` | string | ❌ | 새 카테고리 생성 시 이름 |
| `category_icon` | string | ❌ | 새 카테고리 아이콘 (기본: 📁) |

**지원 파일 형식:**
- PDF (`.pdf`)
- HWP/HWPX (`.hwp`, `.hwpx`)
- Word (`.docx`)
- Excel (`.xlsx`)
- 텍스트 (`.txt`)
- 최대 파일 크기: 50MB

**Response:**

```json
{
  "success": true,
  "data": {
    "upload_id": "upload_abc123",
    "knowledge_source_id": 5,
    "files": [
      {
        "file_name": "ISP_계획서_v2.pdf",
        "file_size": 2456789,
        "status": "queued",
        "document_id": 156
      },
      {
        "file_name": "정책분석_보고서.hwp",
        "file_size": 1234567,
        "status": "queued",
        "document_id": 157
      }
    ]
  },
  "message": "2개 파일이 업로드되었습니다. 처리가 시작됩니다."
}
```

### 3.6 업로드 진행 상태 조회

```
GET /api/v1/uploads/{upload_id}/status
```

**Response:**

```json
{
  "success": true,
  "data": {
    "upload_id": "upload_abc123",
    "total_files": 2,
    "completed": 1,
    "processing": 1,
    "failed": 0,
    "files": [
      {
        "document_id": 156,
        "file_name": "ISP_계획서_v2.pdf",
        "status": "completed",
        "chunk_count": 45,
        "processed_at": "2026-04-22T11:05:30Z"
      },
      {
        "document_id": 157,
        "file_name": "정책분석_보고서.hwp",
        "status": "processing",
        "progress": 60,
        "current_step": "임베딩 생성 중..."
      }
    ]
  }
}
```

### 3.7 지식원 내 문서 목록 조회

```
GET /api/v1/knowledge-sources/{ks_id}/documents
```

**Query Parameters:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `page` | int | ❌ | 페이지 번호 (기본: 1) |
| `per_page` | int | ❌ | 페이지당 개수 (기본: 20) |
| `status` | string | ❌ | 상태 필터 |
| `file_type` | string | ❌ | 파일 유형 필터 |
| `search` | string | ❌ | 제목 검색 |

**Response:**

```json
{
  "success": true,
  "data": {
    "documents": [
      {
        "id": 156,
        "title": "ISP 계획서 v2",
        "file_name": "ISP_계획서_v2.pdf",
        "file_type": "pdf",
        "file_size": 2456789,
        "page_count": 45,
        "chunk_count": 45,
        "status": "completed",
        "uploaded_by": {
          "id": 42,
          "name": "김위즐"
        },
        "uploaded_at": "2026-04-22T11:00:00Z"
      }
    ],
    "pagination": {
      "total": 14,
      "page": 1,
      "per_page": 20,
      "total_pages": 1
    }
  }
}
```

### 3.8 문서 삭제

```
DELETE /api/v1/documents/{doc_id}
```

**Response:**

```json
{
  "success": true,
  "message": "문서가 삭제되었습니다.",
  "data": {
    "deleted_chunks": 45
  }
}
```

---

## 4. 프론트엔드 컴포넌트 설계

### 4.1 컴포넌트 구조

```
components/
├── knowledge/
│   ├── KnowledgeSourcePanel.tsx      # 우측 패널 전체
│   ├── KnowledgeSourceList.tsx       # 지식원 목록
│   ├── KnowledgeSourceItem.tsx       # 개별 지식원 항목
│   ├── KnowledgeSourceStats.tsx      # 통계 표시
│   └── modals/
│       ├── UploadModal.tsx           # 문서 업로드 모달
│       ├── CreateCategoryModal.tsx   # 새 카테고리 생성 모달
│       ├── DocumentListModal.tsx     # 문서 목록 모달
│       └── UploadProgressModal.tsx   # 업로드 진행 상태 모달
```

### 4.2 상태 관리 (Zustand)

```typescript
// stores/useKnowledgeStore.ts

interface KnowledgeSource {
  id: number;
  name: string;
  description: string | null;
  icon: string;
  ks_type: 'global' | 'organization' | 'project' | 'personal';
  is_system: boolean;
  collection_name: string;
  doc_count: number;
  chunk_count: number;
  is_selectable: boolean;
  is_deletable: boolean;
  last_updated_at: string;
}

interface KnowledgeState {
  // 데이터
  knowledgeSources: KnowledgeSource[];
  totalStats: {
    collection_count: number;
    document_count: number;
    chunk_count: number;
  };

  // 선택 상태
  selectedIds: Set<number>;

  // 로딩 상태
  isLoading: boolean;
  error: string | null;

  // 액션
  fetchKnowledgeSources: () => Promise<void>;
  toggleSelection: (id: number) => void;
  selectAll: () => void;
  deselectAll: () => void;
  createKnowledgeSource: (data: CreateKSInput) => Promise<KnowledgeSource>;
  deleteKnowledgeSource: (id: number) => Promise<void>;
  uploadDocuments: (ksId: number, files: File[]) => Promise<UploadResult>;
  refreshCounts: () => Promise<void>;
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  knowledgeSources: [],
  totalStats: { collection_count: 0, document_count: 0, chunk_count: 0 },
  selectedIds: new Set([1]), // 기본: 전체 문서 저장소 선택
  isLoading: false,
  error: null,

  fetchKnowledgeSources: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await api.get('/knowledge-sources?include_counts=true');
      set({
        knowledgeSources: response.data.knowledge_sources,
        totalStats: response.data.total_stats,
        isLoading: false,
      });
    } catch (error) {
      set({ error: '지식원 목록을 불러오는데 실패했습니다.', isLoading: false });
    }
  },

  toggleSelection: (id: number) => {
    const { selectedIds, knowledgeSources } = get();
    const newSelected = new Set(selectedIds);

    // 전체 문서 저장소(id=1) 선택 시 다른 항목 선택 해제
    const ks = knowledgeSources.find(k => k.id === id);
    if (ks?.ks_type === 'global') {
      set({ selectedIds: new Set([id]) });
      return;
    }

    // 다른 항목 선택 시 전체 문서 저장소 선택 해제
    newSelected.delete(1);

    if (newSelected.has(id)) {
      newSelected.delete(id);
      // 아무것도 선택 안 되면 전체 문서 저장소 선택
      if (newSelected.size === 0) {
        newSelected.add(1);
      }
    } else {
      newSelected.add(id);
    }

    set({ selectedIds: newSelected });
  },

  // ... 나머지 액션 구현
}));
```

### 4.3 KnowledgeSourceItem 컴포넌트

```tsx
// components/knowledge/KnowledgeSourceItem.tsx

interface KnowledgeSourceItemProps {
  source: KnowledgeSource;
  isSelected: boolean;
  onToggle: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}

export function KnowledgeSourceItem({
  source,
  isSelected,
  onToggle,
  onContextMenu,
}: KnowledgeSourceItemProps) {
  return (
    <div
      className={cn(
        "ks-item",
        "flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all",
        isSelected
          ? "border-amber bg-amber-50"
          : "border-gray-200 bg-gray-50 hover:border-navy hover:bg-navy-50"
      )}
      onClick={onToggle}
      onContextMenu={onContextMenu}
    >
      {/* 아이콘 */}
      <span className="text-xl flex-shrink-0">{source.icon}</span>

      {/* 정보 */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm text-gray-900 truncate">
            {source.name}
          </span>
          {source.is_system && (
            <span className="text-xs px-1.5 py-0.5 bg-navy-100 text-navy rounded">
              고정
            </span>
          )}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">
          문서 {source.doc_count.toLocaleString()}개
        </div>
      </div>

      {/* 체크 표시 */}
      {isSelected && (
        <span className="text-amber font-bold">✓</span>
      )}
    </div>
  );
}
```

### 4.4 UploadModal 컴포넌트 (개선)

```tsx
// components/knowledge/modals/UploadModal.tsx

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultKsId?: number;
}

export function UploadModal({ isOpen, onClose, defaultKsId }: UploadModalProps) {
  const [mode, setMode] = useState<'existing' | 'new'>('existing');
  const [selectedKsId, setSelectedKsId] = useState(defaultKsId);
  const [newCategory, setNewCategory] = useState({ name: '', icon: '📁' });
  const [files, setFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const { knowledgeSources, uploadDocuments, createKnowledgeSource } = useKnowledgeStore();

  // 개인/조직 카테고리만 필터링 (global 제외)
  const uploadableCategories = knowledgeSources.filter(
    ks => ks.ks_type !== 'global' && !ks.is_system
  );

  const handleUpload = async () => {
    if (files.length === 0) {
      toast.error('업로드할 파일을 선택해주세요.');
      return;
    }

    setIsUploading(true);
    try {
      let targetKsId = selectedKsId;

      // 새 카테고리 생성 모드
      if (mode === 'new') {
        if (!newCategory.name.trim()) {
          toast.error('카테고리 이름을 입력해주세요.');
          return;
        }
        const created = await createKnowledgeSource({
          name: newCategory.name,
          icon: newCategory.icon,
          ks_type: 'personal',
        });
        targetKsId = created.id;
      }

      // 문서 업로드
      const result = await uploadDocuments(targetKsId!, files);

      toast.success(`${result.files.length}개 파일이 업로드되었습니다.`);
      onClose();

      // 업로드 진행 모달 열기
      // openUploadProgressModal(result.upload_id);

    } catch (error) {
      toast.error('업로드 중 오류가 발생했습니다.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="문서 업로드">
      {/* 업로드 대상 선택 */}
      <div className="space-y-4">
        {/* 탭: 기존 카테고리 / 새 카테고리 */}
        <div className="flex border-b">
          <button
            className={cn(
              "px-4 py-2 font-medium",
              mode === 'existing' ? "border-b-2 border-navy text-navy" : "text-gray-500"
            )}
            onClick={() => setMode('existing')}
          >
            기존 카테고리에 추가
          </button>
          <button
            className={cn(
              "px-4 py-2 font-medium",
              mode === 'new' ? "border-b-2 border-navy text-navy" : "text-gray-500"
            )}
            onClick={() => setMode('new')}
          >
            새 카테고리 생성
          </button>
        </div>

        {/* 기존 카테고리 선택 */}
        {mode === 'existing' && (
          <div>
            <label className="block text-sm font-medium mb-2">카테고리 선택</label>
            <select
              className="w-full p-2 border rounded"
              value={selectedKsId}
              onChange={(e) => setSelectedKsId(Number(e.target.value))}
            >
              <option value="">카테고리를 선택하세요</option>
              {uploadableCategories.map((ks) => (
                <option key={ks.id} value={ks.id}>
                  {ks.icon} {ks.name} ({ks.doc_count}개)
                </option>
              ))}
            </select>
          </div>
        )}

        {/* 새 카테고리 생성 */}
        {mode === 'new' && (
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium mb-2">카테고리 이름</label>
              <input
                type="text"
                className="w-full p-2 border rounded"
                placeholder="예: 2026년 ISP 사업자료"
                value={newCategory.name}
                onChange={(e) => setNewCategory({ ...newCategory, name: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">아이콘</label>
              <div className="flex gap-2">
                {['📁', '📂', '🏗', '⚖️', '📊', '📋', '🏛', '🌏'].map((icon) => (
                  <button
                    key={icon}
                    className={cn(
                      "w-10 h-10 text-xl rounded border",
                      newCategory.icon === icon
                        ? "border-amber bg-amber-50"
                        : "border-gray-200 hover:border-navy"
                    )}
                    onClick={() => setNewCategory({ ...newCategory, icon })}
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 파일 드롭존 */}
        <FileDropzone
          files={files}
          onFilesChange={setFiles}
          accept={{
            'application/pdf': ['.pdf'],
            'application/haansofthwp': ['.hwp'],
            'application/vnd.hancom.hwpx': ['.hwpx'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'text/plain': ['.txt'],
          }}
          maxSize={50 * 1024 * 1024} // 50MB
        />

        {/* 처리 흐름 안내 */}
        <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm">
          <strong className="text-amber-800">처리 흐름:</strong>
          <ol className="mt-1 text-amber-700 list-decimal list-inside space-y-0.5">
            <li>파일 업로드 → 서버 저장</li>
            <li>텍스트 추출 (PDF, HWP, DOCX 등)</li>
            <li>청크 분할 (500토큰 단위)</li>
            <li>임베딩 생성 (KoSimCSE)</li>
            <li>VectorDB 저장 (Chroma)</li>
          </ol>
        </div>
      </div>

      {/* 버튼 */}
      <div className="flex justify-end gap-2 mt-6">
        <Button variant="outline" onClick={onClose}>
          취소
        </Button>
        <Button
          onClick={handleUpload}
          disabled={isUploading || files.length === 0}
        >
          {isUploading ? '업로드 중...' : `업로드 시작 (${files.length}개)`}
        </Button>
      </div>
    </Modal>
  );
}
```

---

## 5. 백엔드 서비스 설계

### 5.1 서비스 구조

```
backend/app/services/
├── knowledge_service.py      # 지식원 CRUD
├── document_service.py       # 문서 관리
├── upload_service.py         # 업로드 처리
├── extractor_service.py      # 텍스트 추출
├── chunker_service.py        # 청킹
├── embedder_service.py       # 임베딩
└── vectordb_service.py       # VectorDB 연동
```

### 5.2 VectorDB Service (Chroma)

```python
# backend/app/services/vectordb_service.py

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
import os

class VectorDBService:
    """Chroma VectorDB 연동 서비스"""

    PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
    GLOBAL_COLLECTION = "_all_"  # 전체 통합 검색용 가상 컬렉션

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=self.PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        self._embedder = None

    @property
    def embedder(self):
        """임베딩 모델 (Lazy Loading)"""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("BM-K/KoSimCSE-roberta")
        return self._embedder

    def create_collection(self, collection_name: str) -> chromadb.Collection:
        """새 컬렉션 생성"""
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}  # 코사인 유사도
        )

    def delete_collection(self, collection_name: str) -> bool:
        """컬렉션 삭제"""
        try:
            self.client.delete_collection(collection_name)
            return True
        except Exception:
            return False

    def get_collection_stats(self, collection_name: str) -> Dict:
        """컬렉션 통계 조회"""
        try:
            collection = self.client.get_collection(collection_name)
            return {
                "name": collection_name,
                "count": collection.count(),
            }
        except Exception:
            return {"name": collection_name, "count": 0}

    def get_all_collections_stats(self) -> Dict:
        """모든 컬렉션 통계 조회"""
        collections = self.client.list_collections()
        total_count = 0
        stats = []

        for col in collections:
            count = col.count()
            total_count += count
            stats.append({
                "name": col.name,
                "count": count,
            })

        return {
            "total_count": total_count,
            "collections": stats,
        }

    def add_documents(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: List[Dict],
        ids: List[str]
    ) -> None:
        """문서 청크 추가"""
        collection = self.client.get_or_create_collection(collection_name)

        # 임베딩 생성
        embeddings = self.embedder.encode(documents).tolist()

        # Chroma에 추가
        collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

    def delete_by_doc_id(self, collection_name: str, doc_id: int) -> int:
        """특정 문서의 모든 청크 삭제"""
        try:
            collection = self.client.get_collection(collection_name)

            # doc_id로 필터링하여 삭제
            results = collection.get(
                where={"doc_id": doc_id},
                include=[]
            )

            if results["ids"]:
                collection.delete(ids=results["ids"])
                return len(results["ids"])
            return 0
        except Exception:
            return 0

    def search(
        self,
        query: str,
        collection_names: List[str],
        top_k: int = 5,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """벡터 검색 수행"""

        # 쿼리 임베딩
        query_embedding = self.embedder.encode([query])[0].tolist()

        all_results = []

        # 전체 검색 (_all_) 처리
        if self.GLOBAL_COLLECTION in collection_names:
            collection_names = [c.name for c in self.client.list_collections()]

        # 각 컬렉션에서 검색
        for col_name in collection_names:
            try:
                collection = self.client.get_collection(col_name)

                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=filters,
                    include=["documents", "metadatas", "distances"]
                )

                # 결과 통합
                for i, doc_id in enumerate(results["ids"][0]):
                    all_results.append({
                        "id": doc_id,
                        "collection": col_name,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                        "score": 1 - results["distances"][0][i],  # 코사인 거리 → 유사도
                    })
            except Exception as e:
                print(f"Search error in {col_name}: {e}")
                continue

        # 점수 기준 정렬 및 상위 K개 반환
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]


# 싱글톤 인스턴스
vectordb_service = VectorDBService()
```

### 5.3 Document Processing Pipeline

```python
# backend/app/services/upload_service.py

from celery import shared_task
from typing import List, BinaryIO
import uuid

class UploadService:
    """문서 업로드 처리 서비스"""

    def __init__(
        self,
        db: AsyncSession,
        extractor: ExtractorService,
        chunker: ChunkerService,
        vectordb: VectorDBService,
    ):
        self.db = db
        self.extractor = extractor
        self.chunker = chunker
        self.vectordb = vectordb

    async def upload_files(
        self,
        ks_id: int,
        files: List[UploadFile],
        user_id: int
    ) -> UploadResult:
        """
        파일 업로드 및 처리 시작

        1. 파일 저장
        2. documents 레코드 생성
        3. Celery 태스크로 비동기 처리 시작
        """
        upload_id = f"upload_{uuid.uuid4().hex[:12]}"
        results = []

        # 지식원 조회
        ks = await self.db.get(KnowledgeSource, ks_id)
        if not ks:
            raise NotFoundException("지식원을 찾을 수 없습니다.")

        for file in files:
            # 파일 저장
            file_path = await self._save_file(file, ks.collection_name)

            # DB 레코드 생성
            document = Document(
                ks_id=ks_id,
                title=self._extract_title(file.filename),
                file_name=file.filename,
                file_path=file_path,
                file_type=self._get_file_type(file.filename),
                file_size=file.size,
                status="pending",
                uploaded_by=user_id,
            )
            self.db.add(document)
            await self.db.flush()

            results.append({
                "document_id": document.id,
                "file_name": file.filename,
                "status": "queued",
            })

            # 비동기 처리 태스크 시작
            process_document_task.delay(
                document_id=document.id,
                collection_name=ks.collection_name,
            )

        await self.db.commit()

        return UploadResult(
            upload_id=upload_id,
            knowledge_source_id=ks_id,
            files=results,
        )


@shared_task(bind=True, max_retries=3)
def process_document_task(self, document_id: int, collection_name: str):
    """
    Celery 태스크: 문서 처리 파이프라인

    1. 텍스트 추출
    2. 청킹
    3. 임베딩 & VectorDB 저장
    4. 상태 업데이트
    """
    from app.core.database import get_sync_session
    from app.services import extractor_service, chunker_service, vectordb_service

    with get_sync_session() as db:
        document = db.query(Document).get(document_id)

        try:
            # 상태 업데이트: processing
            document.status = "processing"
            db.commit()

            # 1. 텍스트 추출
            text = extractor_service.extract(
                file_path=document.file_path,
                file_type=document.file_type,
            )

            # 2. 청킹
            chunks = chunker_service.chunk(
                text=text,
                chunk_size=500,
                chunk_overlap=50,
            )

            # 3. VectorDB 저장
            documents = []
            metadatas = []
            ids = []

            for i, chunk in enumerate(chunks):
                documents.append(chunk.text)
                metadatas.append({
                    "doc_id": document_id,
                    "ks_id": document.ks_id,
                    "chunk_index": i,
                    "page_num": chunk.page_num,
                    "doc_title": document.title,
                    "file_type": document.file_type,
                })
                ids.append(f"doc_{document_id}_chunk_{i}")

                # DB에 청크 레코드 저장
                db_chunk = DocumentChunk(
                    doc_id=document_id,
                    chunk_index=i,
                    chunk_text=chunk.text,
                    page_num=chunk.page_num,
                    token_count=chunk.token_count,
                    vector_id=ids[-1],
                )
                db.add(db_chunk)

            # VectorDB에 추가
            vectordb_service.add_documents(
                collection_name=collection_name,
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )

            # 상태 업데이트: completed
            document.status = "completed"
            document.chunk_count = len(chunks)
            document.processed_at = datetime.utcnow()

            # 지식원 문서 수 갱신
            ks = db.query(KnowledgeSource).get(document.ks_id)
            ks.doc_count = db.query(Document).filter(
                Document.ks_id == ks.id,
                Document.status == "completed"
            ).count()
            ks.chunk_count = db.query(DocumentChunk).join(Document).filter(
                Document.ks_id == ks.id
            ).count()
            ks.last_updated_at = datetime.utcnow()

            db.commit()

        except Exception as e:
            document.status = "failed"
            document.error_message = str(e)
            db.commit()
            raise self.retry(exc=e, countdown=60)  # 1분 후 재시도
```

---

## 6. 처리 흐름 다이어그램

### 6.1 문서 업로드 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              사용자 (Frontend)                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                           1. 파일 선택 & 업로드
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           POST /api/knowledge-sources/{id}/documents         │
│                                   (FastAPI)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  • 파일 유효성 검증 (확장자, 크기)                                           │
│  • 파일 저장 (로컬/S3)                                                       │
│  • documents 레코드 생성 (status: pending)                                   │
│  • Celery 태스크 큐에 추가                                                   │
│  • upload_id 반환                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                           2. 태스크 큐 (비동기)
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Celery Worker                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Step 1: 텍스트 추출 (ExtractorService)                              │    │
│  │ • PDF → pdfplumber                                                   │    │
│  │ • HWP → pyhwpx                                                       │    │
│  │ • DOCX → python-docx                                                 │    │
│  │ • XLSX → openpyxl                                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Step 2: 청킹 (ChunkerService)                                        │    │
│  │ • RecursiveCharacterTextSplitter                                     │    │
│  │ • chunk_size: 500 tokens                                             │    │
│  │ • chunk_overlap: 50 tokens                                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Step 3: 임베딩 & 저장 (VectorDBService)                              │    │
│  │ • KoSimCSE-roberta 임베딩 생성                                       │    │
│  │ • Chroma 컬렉션에 벡터 저장                                          │    │
│  │ • document_chunks 테이블 저장                                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Step 4: 상태 업데이트                                                │    │
│  │ • documents.status = 'completed'                                     │    │
│  │ • knowledge_sources.doc_count 갱신                                   │    │
│  │ • knowledge_sources.last_updated_at 갱신                             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                           3. 상태 폴링 / WebSocket
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              사용자 (Frontend)                               │
│                           업로드 완료 알림 표시                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 RAG 검색 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  사용자 선택:                                                                │
│  ☑ 전체 문서 저장소    또는    ☑ 과기정통부 사업 문서                        │
│                              ☑ 정책/법령 문서                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                              검색 쿼리 입력
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           POST /api/rag/search                               │
│                                                                              │
│  Request:                                                                    │
│  {                                                                           │
│    "query": "ISP 사업계획서 작성 방법",                                      │
│    "knowledge_source_ids": [1] 또는 [2, 3],                                  │
│    "top_k": 5,                                                               │
│    "filters": { "file_type": ["pdf", "hwp"] }                               │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          VectorDBService.search()                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. knowledge_source_ids → collection_names 변환                             │
│     • [1] (전체) → 모든 컬렉션 목록                                          │
│     • [2, 3] → ["org_1_msit_projects", "org_1_policy_law"]                  │
│                                                                              │
│  2. 쿼리 임베딩 생성                                                         │
│     • KoSimCSE-roberta.encode(query)                                         │
│                                                                              │
│  3. 각 컬렉션에서 유사도 검색                                                │
│     • collection.query(query_embeddings, n_results=top_k)                    │
│                                                                              │
│  4. 결과 통합 & 정렬                                                         │
│     • 모든 결과 score 기준 정렬                                              │
│     • 상위 top_k개 반환                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Response:                                                                   │
│  {                                                                           │
│    "results": [                                                              │
│      {                                                                       │
│        "chunk_text": "ISP 사업계획서 작성 시 고려사항...",                   │
│        "doc_title": "2025 ISP 표준 가이드",                                  │
│        "page_num": 23,                                                       │
│        "score": 0.94,                                                        │
│        "collection": "org_1_msit_projects"                                   │
│      },                                                                      │
│      ...                                                                     │
│    ]                                                                         │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. UI 인터랙션 시나리오

### 7.1 지식원 선택 시나리오

| 사용자 액션 | 시스템 응답 |
|-------------|-------------|
| 페이지 진입 | "전체 문서 저장소" 기본 선택됨 |
| "전체 문서 저장소" 클릭 | 다른 선택 모두 해제, 전체만 선택 |
| 개별 카테고리 클릭 | "전체 문서 저장소" 선택 해제, 해당 카테고리 선택 |
| 추가 카테고리 클릭 | 다중 선택 (기존 + 추가) |
| 선택된 카테고리 클릭 | 해당 카테고리 선택 해제 |
| 모든 개별 카테고리 해제 | 자동으로 "전체 문서 저장소" 선택 |

### 7.2 문서 업로드 시나리오

| 단계 | 사용자 액션 | 시스템 응답 |
|------|-------------|-------------|
| 1 | "+ 문서 업로드" 버튼 클릭 | 업로드 모달 열림 |
| 2a | "기존 카테고리에 추가" 탭 선택 | 카테고리 드롭다운 표시 |
| 2b | "새 카테고리 생성" 탭 선택 | 이름/아이콘 입력 폼 표시 |
| 3 | 파일 드래그&드롭 또는 선택 | 파일 목록 표시 |
| 4 | "업로드 시작" 클릭 | 모달 닫힘, 처리 시작 알림 |
| 5 | (백그라운드 처리) | 토스트: "처리 중... 60%" |
| 6 | (처리 완료) | 토스트: "2개 파일 처리 완료" |
| 7 | - | 지식원 목록의 문서 수 자동 갱신 |

### 7.3 카테고리 관리 시나리오

| 사용자 액션 | 시스템 응답 |
|-------------|-------------|
| 카테고리 우클릭 | 컨텍스트 메뉴: 이름 변경, 문서 목록, 삭제 |
| "문서 목록" 선택 | 해당 카테고리의 문서 목록 모달 표시 |
| "삭제" 선택 | 확인 다이얼로그 표시 |
| 삭제 확인 | 카테고리 + 문서 + 벡터 삭제, 목록 갱신 |

---

## 8. 에러 처리

### 8.1 업로드 에러

| 에러 코드 | 상황 | 사용자 메시지 |
|-----------|------|---------------|
| `INVALID_FILE_TYPE` | 지원하지 않는 파일 형식 | "지원하지 않는 파일 형식입니다. (PDF, HWP, DOCX, XLSX, TXT)" |
| `FILE_TOO_LARGE` | 파일 크기 초과 | "파일 크기가 50MB를 초과합니다." |
| `EXTRACTION_FAILED` | 텍스트 추출 실패 | "문서 처리 중 오류가 발생했습니다. 파일이 손상되었을 수 있습니다." |
| `EMBEDDING_FAILED` | 임베딩 생성 실패 | "문서 인덱싱 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요." |

### 8.2 검색 에러

| 에러 코드 | 상황 | 사용자 메시지 |
|-----------|------|---------------|
| `NO_KNOWLEDGE_SELECTED` | 지식원 미선택 | "검색할 지식원을 선택해주세요." |
| `COLLECTION_NOT_FOUND` | 컬렉션 없음 | "선택한 지식원에 문서가 없습니다." |
| `SEARCH_FAILED` | 검색 실패 | "검색 중 오류가 발생했습니다." |

---

## 9. 보안 고려사항

### 9.1 접근 권한

| 지식원 유형 | 조회 | 문서 추가 | 삭제 |
|-------------|------|-----------|------|
| global (시스템) | 모든 사용자 | 관리자 | ❌ |
| organization | 조직 구성원 | 관리자 | 관리자 |
| project | 프로젝트 멤버 | 프로젝트 관리자 | 프로젝트 관리자 |
| personal | 본인만 | 본인 | 본인 |

### 9.2 파일 보안

- 업로드 파일 바이러스 검사 (선택)
- 파일명 sanitization (특수문자 제거)
- 저장 경로 난독화 (UUID 사용)
- 직접 파일 접근 차단 (API 통해서만 접근)

---

## 10. 성능 고려사항

### 10.1 캐싱 전략

| 항목 | 캐시 위치 | TTL | 갱신 조건 |
|------|-----------|-----|-----------|
| 지식원 목록 | Redis | 5분 | 문서 업로드/삭제 시 |
| 문서 수 카운트 | DB 컬럼 | - | 문서 처리 완료 시 |
| 임베딩 모델 | 메모리 | 앱 생명주기 | - |

### 10.2 대용량 처리

- 청크 단위 배치 처리 (100개씩)
- 임베딩 생성 GPU 활용 (가능 시)
- VectorDB 인덱스 최적화 (HNSW)
- 대용량 파일 스트리밍 업로드

---

## 11. 향후 확장

### 11.1 추가 기능 (Phase 2)

- [ ] 지식원 공유 (다른 사용자에게 공유)
- [ ] 문서 버전 관리
- [ ] 문서 미리보기
- [ ] 중복 문서 감지
- [ ] 자동 태깅 (AI 기반)

### 11.2 고도화 (Phase 3)

- [ ] 하이브리드 검색 (키워드 + 벡터)
- [ ] 다국어 임베딩 지원
- [ ] 실시간 인덱싱 (WebSocket)
- [ ] 분산 VectorDB (클러스터)

---

**문서 끝**
