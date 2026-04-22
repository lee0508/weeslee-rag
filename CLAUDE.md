# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PromptoRAG** is a consulting document reuse and AI draft generation system. It enables users to search existing consulting documents (ISP/ISMP/ODA proposals, reports) stored on network drives and generate new document drafts using RAG (Retrieval-Augmented Generation).

### Core Workflow
1. Select document type (template)
2. Specify knowledge source (document repositories)
3. Input context (organization, project name, purpose)
4. AI searches existing documents
5. Generate draft using retrieved documents as reference
6. Review, edit, and export

## Architecture

### Current State
- **Frontend only**: Single HTML file (`PromptoRAG_UI_v1.0.html`) with inline CSS/JavaScript
- **No backend yet**: API server, database, and RAG pipeline are documented but not implemented

### Planned Tech Stack
- **Backend**: FastAPI (Python) with SQLAlchemy ORM
- **Database**: MySQL 8.0 for metadata, FAISS/Chroma for vector storage
- **LLM**: Claude API (Sonnet/Opus) with SSE streaming
- **Document Processing**: pdfplumber (PDF), python-docx (DOCX), pyhwpx/hwp5 (HWP)
- **Embeddings**: KoSimCSE (Korean) or OpenAI text-embedding-3

### Document Storage
Primary source: `\\diskstation\W2_프로젝트폴더` (network share containing all consulting documents)

Subfolders map to knowledge sources:
- `/ISP` - ISP project documents
- `/ISMP` - ISMP project documents
- `/ODA` - ODA proposals
- `/정책연구` - Policy/regulation documents

### UI Layout (3-panel design)
```
┌────────────┬─────────────────────┬────────────┐
│  Left      │     Center          │   Right    │
│  Sidebar   │     (Step Wizard)   │   Panel    │
│  (270px)   │     (flex: 1)       │  (320px)   │
│            │                     │            │
│  Template  │  1. Template Header │  Knowledge │
│  Search    │  2. Input Params    │  Source    │
│  & List    │  3. Extra Request   │  Selection │
│            │  4. AI Result       │  & Search  │
│            │  5. Execution Bar   │  Options   │
└────────────┴─────────────────────┴────────────┘
```

### Step Wizard (5 steps)
1. **업무선택** - Select document category
2. **템플릿선택** - Choose template from sidebar
3. **입력값설정** - Fill input parameters
4. **지식원선택** - Configure knowledge sources (right panel)
5. **결과검토** - Review AI-generated result

## Key Design Concepts

### Variable-based Prompt Templates
Templates contain placeholders like `{{기관명}}`, `{{사업명}}` that are filled from input parameters. The `prompt_variables` table defines each variable's type, label, validation rules.

### Knowledge Sources
Each knowledge source points to a folder path and maintains document index. The system scans folders periodically to detect new/modified files for re-indexing.

### Execution History as Reusable Assets
Every AI generation is logged with full context (inputs, settings, results, referenced documents) for later reuse or modification.

## Database Schema (Key Tables)

- `prompts` - Template definitions with system/user prompts
- `prompt_variables` - Variable definitions per template
- `knowledge_sources` - Document repository metadata
- `documents` - Indexed document metadata
- `document_chunks` - RAG chunks with embeddings
- `execution_logs` - Generation history
- `reference_logs` - Documents referenced in each execution

## CSS Design System

3-color scheme defined in CSS variables:
- `--navy` (#1B3A6B) - Primary brand color
- `--amber` (#E8971F) - Accent color
- `--white`/grays - Backgrounds

## Development Notes

### Korean Language
- All UI text, documentation, and user-facing content is in Korean
- Use Korean-optimized embedding models (KoSimCSE) for RAG

### File Format Support
Priority formats: PDF, HWP/HWPX (Korean word processor), DOCX, XLSX
