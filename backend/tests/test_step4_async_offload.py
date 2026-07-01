import asyncio
import time
from pathlib import Path

import pytest

from app.api import admin_dataset_builder_step4 as step4


@pytest.mark.asyncio
async def test_extract_document_in_worker_offloads_blocking_work(monkeypatch, tmp_path):
    sample_file = tmp_path / "sample.pdf"
    sample_file.write_text("dummy", encoding="utf-8")

    def slow_sync_extract(file_path: str, ocr_use_gpu: bool) -> dict:
        assert file_path == str(sample_file)
        assert ocr_use_gpu is True
        time.sleep(0.08)
        return {"success": True, "content": "ok"}

    monkeypatch.setattr(step4, "_extract_document_sync", slow_sync_extract)

    heartbeat_ticks = 0

    async def heartbeat():
        nonlocal heartbeat_ticks
        started = time.perf_counter()
        while time.perf_counter() - started < 0.08:
            heartbeat_ticks += 1
            await asyncio.sleep(0.01)

    result, _ = await asyncio.gather(
        step4._extract_document_in_worker(str(sample_file), True),
        heartbeat(),
    )

    assert result["success"] is True
    assert heartbeat_ticks >= 3


@pytest.mark.asyncio
async def test_parse_document_uses_worker_offload(monkeypatch, tmp_path):
    sample_file = tmp_path / "sample.pdf"
    sample_file.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(step4.processed_text_store, "exists", lambda document_id: False)
    monkeypatch.setattr(step4.processed_text_store, "save_result", lambda result: True)
    monkeypatch.setattr(step4, "get_runtime_compute_settings", lambda: {"gpu_enabled": True, "ocr_use_gpu": True})
    monkeypatch.setattr(step4, "is_stage_gpu_enabled", lambda stage, settings=None: True)

    worker_calls = {}

    async def fake_worker(file_path: str, ocr_use_gpu: bool) -> dict:
        worker_calls["file_path"] = file_path
        worker_calls["ocr_use_gpu"] = ocr_use_gpu
        return {
            "success": True,
            "content": "A" * 600,
            "method": "fake-worker",
            "metadata": {"quality": {}, "pages": 1},
        }

    monkeypatch.setattr(step4, "_extract_document_in_worker", fake_worker)

    result = await step4.parse_document(
        document_id=101,
        file_path=str(sample_file),
        force=True,
        metadata_ctx={"source_id": "src_test", "dataset_id": "dataset_test"},
    )

    assert result["success"] is True
    assert worker_calls == {
        "file_path": str(sample_file),
        "ocr_use_gpu": True,
    }
