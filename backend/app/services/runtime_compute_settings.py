from __future__ import annotations

import os
import subprocess
from typing import Any

from app.services.platform_store import create_record, get_record, update_record

STORE_NAME = "runtime_compute_settings"
RECORD_ID = "default"

DEFAULT_RUNTIME_COMPUTE_SETTINGS: dict[str, Any] = {
    "id": RECORD_ID,
    "gpu_enabled": False,
    "cuda_visible_devices": "0",
    "ollama_use_gpu": False,
    "ocr_use_gpu": True,
    "chunk_use_gpu": False,
    "embedding_use_gpu": True,
    "faiss_use_gpu": True,
}

STAGE_TO_FIELD = {
    "ollama": "ollama_use_gpu",
    "ocr": "ocr_use_gpu",
    "chunk": "chunk_use_gpu",
    "embedding": "embedding_use_gpu",
    "faiss": "faiss_use_gpu",
}

STAGE_NOTES = {
    "ollama": "Ollama GPU 사용은 admin 설정 저장 외에 ollama.service 재시작이 필요합니다.",
    "ocr": "OCR는 EasyOCR/CUDA 또는 관련 OCR 엔진이 설치된 경우 GPU를 사용할 수 있습니다.",
    "chunk": "현재 청킹 엔진은 텍스트 분할 중심이라 GPU 가속 이점이 제한적입니다.",
    "embedding": "임베딩은 Ollama 서비스가 GPU 모드로 실행 중일 때 실제 GPU를 사용합니다.",
    "faiss": "FAISS는 faiss-gpu가 설치된 경우에만 GPU 인덱싱을 사용합니다.",
}


def _detect_torch_cuda() -> dict[str, Any]:
    try:
        import torch

        available = bool(torch.cuda.is_available())
        return {
            "available": available,
            "device_count": int(torch.cuda.device_count()),
            "device_name": torch.cuda.get_device_name(0) if available and torch.cuda.device_count() > 0 else "",
        }
    except Exception:
        return {
            "available": False,
            "device_count": 0,
            "device_name": "",
        }


def _detect_nvidia_smi() -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version,cuda_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    cards: list[dict[str, Any]] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        memory_mb = 0
        try:
            memory_mb = int(parts[1])
        except Exception:
            memory_mb = 0
        cards.append(
            {
                "name": parts[0],
                "memory_mb": memory_mb,
                "driver_version": parts[2],
                "cuda_version": parts[3],
            }
        )
    return cards


def _detect_faiss_gpu() -> dict[str, Any]:
    try:
        import faiss  # type: ignore

        available = bool(
            hasattr(faiss, "StandardGpuResources")
            and hasattr(faiss, "index_cpu_to_gpu")
            and hasattr(faiss, "index_gpu_to_cpu")
        )
        return {
            "available": available,
            "version": getattr(faiss, "__version__", ""),
        }
    except Exception as exc:
        return {
            "available": False,
            "version": "",
            "error": str(exc),
        }


def get_runtime_compute_settings() -> dict[str, Any]:
    saved = get_record(STORE_NAME, "id", RECORD_ID) or {}
    return {
        **DEFAULT_RUNTIME_COMPUTE_SETTINGS,
        **saved,
        "id": RECORD_ID,
    }


def save_runtime_compute_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_record(STORE_NAME, "id", RECORD_ID)
    updates = {
        **DEFAULT_RUNTIME_COMPUTE_SETTINGS,
        **(current or {}),
        **payload,
        "id": RECORD_ID,
    }
    if current:
        return update_record(STORE_NAME, "id", RECORD_ID, updates) or updates
    return create_record(STORE_NAME, updates, "id")


def is_stage_gpu_enabled(stage: str, settings: dict[str, Any] | None = None) -> bool:
    current = settings or get_runtime_compute_settings()
    field_name = STAGE_TO_FIELD.get(stage)
    if not field_name:
        return False
    return bool(current.get("gpu_enabled")) and bool(current.get(field_name))


def build_runtime_compute_env(stage: str, settings: dict[str, Any] | None = None) -> dict[str, str]:
    current = settings or get_runtime_compute_settings()
    env = dict(os.environ)
    env["WEESLEE_GPU_MODE"] = "1" if current.get("gpu_enabled") else "0"
    env["WEESLEE_GPU_STAGE"] = stage
    env["WEESLEE_GPU_OCR"] = "1" if is_stage_gpu_enabled("ocr", current) else "0"
    env["WEESLEE_GPU_CHUNK"] = "1" if is_stage_gpu_enabled("chunk", current) else "0"
    env["WEESLEE_GPU_EMBEDDING"] = "1" if is_stage_gpu_enabled("embedding", current) else "0"
    env["WEESLEE_GPU_FAISS"] = "1" if is_stage_gpu_enabled("faiss", current) else "0"
    env["WEESLEE_GPU_OLLAMA"] = "1" if is_stage_gpu_enabled("ollama", current) else "0"

    if current.get("gpu_enabled"):
        env["CUDA_VISIBLE_DEVICES"] = str(current.get("cuda_visible_devices") or "0")
    else:
        env["CUDA_VISIBLE_DEVICES"] = ""

    return env


def describe_stage_compute_mode(stage: str, settings: dict[str, Any] | None = None) -> str:
    current = settings or get_runtime_compute_settings()
    enabled = is_stage_gpu_enabled(stage, current)
    device = str(current.get("cuda_visible_devices") or "0")
    note = STAGE_NOTES.get(stage, "")
    mode = f"GPU {'ON' if enabled else 'OFF'}"
    if enabled:
        mode += f" (CUDA_VISIBLE_DEVICES={device})"
    return f"{mode} - {note}".strip()


def get_runtime_compute_snapshot() -> dict[str, Any]:
    settings = get_runtime_compute_settings()
    torch_cuda = _detect_torch_cuda()
    nvidia_cards = _detect_nvidia_smi()
    faiss_gpu = _detect_faiss_gpu()
    gpu_available = bool(nvidia_cards) or bool(torch_cuda.get("available"))

    return {
        "settings": settings,
        "detection": {
            "gpu_available": gpu_available,
            "torch_cuda": torch_cuda,
            "nvidia_cards": nvidia_cards,
            "faiss_gpu": faiss_gpu,
        },
        "effective": {
            stage: is_stage_gpu_enabled(stage, settings)
            for stage in STAGE_TO_FIELD
        },
        "notes": STAGE_NOTES,
    }
