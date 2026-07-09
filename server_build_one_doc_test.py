import asyncio
from app.core.database import SessionLocal
from app.api.admin_dataset_builder_step4 import parse_document, _build_processing_metadata_ctx
from app.api.admin_dataset_builder_step5 import build_chunks, ChunkBuildRequest
from app.api.admin_dataset_builder_step6 import build_embeddings, EmbeddingBuildRequest
from app.api.admin_dataset_builder_step7 import build_faiss_index, FAISSBuildRequest
from app.models.document_metadata import DocumentMetadata
from app.services.ollama import OllamaService

SOURCE_ID = 'src_20260706_124908_1f10b5'
DOCUMENT_ID = 93407
SNAPSHOT_ID = 'snapshot_20260706_src_20260706_124908_1f10b5_TEST1'

async def main():
    db = SessionLocal()
    try:
        doc = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == DOCUMENT_ID).first()
        if not doc:
            raise RuntimeError(f'document_id {DOCUMENT_ID} not found')
        dataset_cache = {}
        metadata_ctx = _build_processing_metadata_ctx(doc, dataset_cache)
        step4 = await parse_document(
            document_id=doc.document_id,
            file_path=doc.file_path,
            force=True,
            metadata_ctx=metadata_ctx,
            parse_config={
                'ocr_dpi': 300,
                'ocr_language': 'kor+eng',
                'ocr_min_text_length': 50,
                'ocr_engine': 'tesseract',
                'ocr_mode': 'auto',
            },
        )
        print('STEP4', step4)

        step5 = await build_chunks(
            ChunkBuildRequest(
                source_id=SOURCE_ID,
                snapshot_id=SNAPSHOT_ID,
                document_ids=[DOCUMENT_ID],
                chunk_size=1000,
                chunk_overlap=200,
                min_chunk_size=100,
                force_rebuild=True,
                chunking_mode='auto',
            ),
            db,
        )
        print('STEP5', step5.model_dump())

        ollama = OllamaService()
        step6 = await build_embeddings(
            EmbeddingBuildRequest(
                source_id=SOURCE_ID,
                snapshot_id=SNAPSHOT_ID,
                document_ids=[DOCUMENT_ID],
                model='bge-m3:latest',
                batch_size=8,
                retry_count=1,
                force_rebuild=True,
            ),
            db,
            ollama,
        )
        print('STEP6', step6.model_dump())

        step7 = await build_faiss_index(
            FAISSBuildRequest(
                collection_name='weeslee_rag_main',
                source_id=SOURCE_ID,
                snapshot_id=SNAPSHOT_ID,
                document_ids=[DOCUMENT_ID],
                index_type='flat',
                metric='l2',
                normalize=True,
            ),
            db,
        )
        print('STEP7', step7.model_dump())
    finally:
        db.close()

asyncio.run(main())
