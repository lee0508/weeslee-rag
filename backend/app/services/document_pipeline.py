# -*- coding: utf-8 -*-
"""
Document Processing Pipeline Service
Complete RAG pipeline: Extract → Chunk → Embed → Store
"""
import os
import uuid
import json
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.document import Document, DocumentChunk, ProcessingLog, DocumentStatus, FileType
from app.models.collection import Collection
from app.extractors.extractor import document_extractor
from app.services.chunking import chunking_service, TextChunk
from app.services.metadata_extractor import metadata_extractor_service, DocumentMetadata
from app.services.ollama import ollama_service
from app.services.vectordb import vectordb_service


class PipelineStage(str, Enum):
    """Pipeline processing stages"""
    INITIALIZED = "initialized"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineProgress:
    """Pipeline progress tracking"""
    stage: PipelineStage
    progress: int  # 0-100
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class PipelineResult:
    """Result of document processing pipeline"""
    success: bool
    document_id: Optional[int] = None
    collection_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    chunk_count: int = 0
    vector_ids: List[str] = None
    processing_time: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.vector_ids is None:
            self.vector_ids = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DocumentPipelineService:
    """
    Complete document processing pipeline for RAG system

    Pipeline stages:
    1. Extract text from document (PDF, DOCX, etc.)
    2. Analyze document and extract metadata (title, summary, keywords)
    3. Chunk text into optimal segments
    4. Generate embeddings for chunks
    5. Store in VectorDB and MySQL
    """

    def __init__(self):
        self.progress_callback: Optional[Callable[[PipelineProgress], None]] = None

    def _report_progress(
        self,
        stage: PipelineStage,
        progress: int,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """Report progress to callback if set"""
        if self.progress_callback:
            self.progress_callback(PipelineProgress(
                stage=stage,
                progress=progress,
                message=message,
                details=details
            ))

    def _get_file_type(self, filename: str) -> Optional[FileType]:
        """Determine file type from extension"""
        ext = os.path.splitext(filename)[1].lower().lstrip('.')
        try:
            return FileType(ext)
        except ValueError:
            return None

    def _log_progress(
        self,
        db: Session,
        document_id: int,
        status: str,
        message: str,
        progress: int
    ):
        """Log progress to database"""
        log = ProcessingLog(
            document_id=document_id,
            status=status,
            message=message,
            progress=progress
        )
        db.add(log)
        db.commit()

    async def process_document(
        self,
        file_path: str,
        collection_name: str,
        progress_callback: Optional[Callable[[PipelineProgress], None]] = None
    ) -> PipelineResult:
        """
        Process a single document through the complete RAG pipeline

        Args:
            file_path: Path to the document file
            collection_name: Target collection name
            progress_callback: Optional callback for progress updates

        Returns:
            PipelineResult with processing outcome
        """
        self.progress_callback = progress_callback
        start_time = datetime.now()
        db = SessionLocal()

        try:
            # Validate file exists
            if not os.path.exists(file_path):
                return PipelineResult(
                    success=False,
                    error=f"File not found: {file_path}"
                )

            filename = os.path.basename(file_path)
            file_type = self._get_file_type(filename)

            if not file_type:
                return PipelineResult(
                    success=False,
                    error=f"Unsupported file type: {filename}"
                )

            self._report_progress(
                PipelineStage.INITIALIZED,
                0,
                f"Processing started: {filename}"
            )

            # Get or create collection
            collection = db.query(Collection).filter(
                Collection.name == collection_name
            ).first()

            if not collection:
                collection = Collection(
                    name=collection_name,
                    description=f"Auto-created collection for {collection_name}"
                )
                db.add(collection)
                db.commit()
                db.refresh(collection)

            # Create document record
            file_stat = os.stat(file_path)
            document = Document(
                collection_id=collection.id,
                filename=filename,
                original_path=file_path,
                file_type=file_type,
                file_size=file_stat.st_size,
                status=DocumentStatus.EXTRACTING
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            self._log_progress(
                db, document.id,
                "extracting", "Started text extraction", 10
            )

            # Stage 1: Extract text
            self._report_progress(
                PipelineStage.EXTRACTING,
                10,
                "Extracting text from document..."
            )

            extraction_result = await document_extractor.extract(file_path)

            if not extraction_result.get('success', False):
                document.status = DocumentStatus.FAILED
                document.error_message = extraction_result.get('error', 'Extraction failed')
                db.commit()
                return PipelineResult(
                    success=False,
                    document_id=document.id,
                    error=document.error_message
                )

            full_text = extraction_result.get('text', '')
            page_count = extraction_result.get('page_count', 1)

            self._log_progress(
                db, document.id,
                "extracting", f"Extracted {len(full_text)} characters from {page_count} pages", 25
            )

            # Stage 2: Extract metadata
            self._report_progress(
                PipelineStage.ANALYZING,
                30,
                "Analyzing document and extracting metadata..."
            )

            document.status = DocumentStatus.CHUNKING  # Using as "analyzing" stage

            metadata = await metadata_extractor_service.extract_metadata(
                full_text,
                filename=filename
            )

            self._log_progress(
                db, document.id,
                "analyzing",
                f"Extracted metadata: {metadata.title}",
                40
            )

            # Stage 3: Chunk text
            self._report_progress(
                PipelineStage.CHUNKING,
                45,
                "Chunking text into segments..."
            )

            chunks = chunking_service.chunk_document(
                text=full_text,
                document_id=document.id,
                document_name=filename,
                metadata={
                    'category': metadata.category,
                    'document_type': metadata.document_type
                }
            )

            self._log_progress(
                db, document.id,
                "chunking",
                f"Created {len(chunks)} chunks",
                55
            )

            # Stage 4: Generate embeddings
            self._report_progress(
                PipelineStage.EMBEDDING,
                60,
                f"Generating embeddings for {len(chunks)} chunks..."
            )

            document.status = DocumentStatus.EMBEDDING

            chunk_texts = [chunk.content for chunk in chunks]
            embeddings = await ollama_service.get_embeddings_batch(
                chunk_texts,
                batch_size=16
            )

            self._log_progress(
                db, document.id,
                "embedding",
                f"Generated {len(embeddings)} embeddings",
                80
            )

            # Stage 5: Store in VectorDB and MySQL
            self._report_progress(
                PipelineStage.STORING,
                85,
                "Storing vectors and metadata..."
            )

            # Prepare metadata for each chunk
            chunk_metadatas = []
            for chunk in chunks:
                chunk_metadata = {
                    'document_id': document.id,
                    'document_name': filename,
                    'chunk_index': chunk.index,
                    'page_number': chunk.page_number,
                    'token_count': chunk.token_count,
                    'category': metadata.category,
                    'document_type': metadata.document_type,
                    'title': metadata.title
                }
                chunk_metadatas.append(chunk_metadata)

            # Store in ChromaDB
            vector_ids = vectordb_service.add_documents(
                collection_name=collection_name,
                documents=chunk_texts,
                embeddings=embeddings,
                metadatas=chunk_metadatas
            )

            # Store chunks in MySQL
            for i, (chunk, vector_id) in enumerate(zip(chunks, vector_ids)):
                db_chunk = DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    vector_id=vector_id
                )
                db.add(db_chunk)

            # Update document status
            document.status = DocumentStatus.COMPLETED
            document.chunk_count = len(chunks)
            db.commit()

            # Update collection stats
            collection.document_count += 1
            collection.vector_count += len(chunks)
            db.commit()

            self._log_progress(
                db, document.id,
                "completed",
                f"Successfully processed: {len(chunks)} chunks stored",
                100
            )

            # Stage 6: Create metadata file
            metadata_file = await self._save_metadata_file(
                document.id,
                filename,
                metadata,
                len(chunks),
                collection_name
            )

            self._report_progress(
                PipelineStage.COMPLETED,
                100,
                f"Document processed successfully: {len(chunks)} chunks"
            )

            processing_time = (datetime.now() - start_time).total_seconds()

            return PipelineResult(
                success=True,
                document_id=document.id,
                collection_id=collection.id,
                metadata=metadata.to_dict(),
                chunk_count=len(chunks),
                vector_ids=vector_ids,
                processing_time=processing_time
            )

        except Exception as e:
            # Update document status to failed
            if 'document' in locals() and document.id:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                db.commit()

            self._report_progress(
                PipelineStage.FAILED,
                0,
                f"Processing failed: {str(e)}"
            )

            return PipelineResult(
                success=False,
                error=str(e),
                processing_time=(datetime.now() - start_time).total_seconds()
            )

        finally:
            db.close()

    async def _save_metadata_file(
        self,
        document_id: int,
        filename: str,
        metadata: DocumentMetadata,
        chunk_count: int,
        collection_name: str
    ) -> str:
        """Save metadata to JSON file"""
        from app.core.config import settings

        metadata_dir = os.path.join(settings.upload_dir, "metadata")
        os.makedirs(metadata_dir, exist_ok=True)

        metadata_filename = f"{document_id}_{os.path.splitext(filename)[0]}_meta.json"
        metadata_path = os.path.join(metadata_dir, metadata_filename)

        metadata_dict = {
            "document_id": document_id,
            "file_name": filename,
            "title": metadata.title,
            "summary": metadata.summary,
            "keywords": metadata.keywords,
            "category": metadata.category,
            "document_type": metadata.document_type,
            "organization": metadata.organization,
            "project_name": metadata.project_name,
            "year": metadata.year,
            "language": metadata.language,
            "chunk_count": chunk_count,
            "collection_name": collection_name,
            "confidence_score": metadata.confidence_score,
            "extracted_at": metadata.extracted_at,
            "status": "completed"
        }

        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata_dict, f, ensure_ascii=False, indent=2)

        return metadata_path

    async def process_from_knowledge_source(
        self,
        relative_path: str,
        collection_name: str,
        progress_callback: Optional[Callable[[PipelineProgress], None]] = None
    ) -> PipelineResult:
        """
        Process a document from the knowledge source (network drive)

        Args:
            relative_path: Path relative to knowledge source root
            collection_name: Target collection name
            progress_callback: Optional callback for progress updates

        Returns:
            PipelineResult
        """
        from app.services.knowledge_source import knowledge_source_service

        full_path = os.path.join(
            knowledge_source_service.get_root_path(),
            relative_path
        )

        return await self.process_document(
            file_path=full_path,
            collection_name=collection_name,
            progress_callback=progress_callback
        )

    def get_document_status(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Get current processing status of a document"""
        db = SessionLocal()
        try:
            document = db.query(Document).filter(Document.id == document_id).first()
            if not document:
                return None

            # Get latest processing log
            latest_log = db.query(ProcessingLog).filter(
                ProcessingLog.document_id == document_id
            ).order_by(ProcessingLog.created_at.desc()).first()

            return {
                "document_id": document.id,
                "filename": document.filename,
                "status": document.status.value,
                "chunk_count": document.chunk_count,
                "error_message": document.error_message,
                "latest_progress": {
                    "status": latest_log.status if latest_log else None,
                    "message": latest_log.message if latest_log else None,
                    "progress": latest_log.progress if latest_log else 0
                } if latest_log else None,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat()
            }
        finally:
            db.close()

    def list_processed_documents(
        self,
        collection_id: Optional[int] = None,
        status: Optional[DocumentStatus] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List processed documents"""
        db = SessionLocal()
        try:
            query = db.query(Document)

            if collection_id:
                query = query.filter(Document.collection_id == collection_id)
            if status:
                query = query.filter(Document.status == status)

            documents = query.order_by(Document.created_at.desc()).limit(limit).all()

            return [
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "file_type": doc.file_type.value,
                    "status": doc.status.value,
                    "chunk_count": doc.chunk_count,
                    "file_size": doc.file_size,
                    "collection_id": doc.collection_id,
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat()
                }
                for doc in documents
            ]
        finally:
            db.close()


# Singleton instance
document_pipeline_service = DocumentPipelineService()


def get_document_pipeline() -> DocumentPipelineService:
    """Dependency to get document pipeline service"""
    return document_pipeline_service
