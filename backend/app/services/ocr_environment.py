from __future__ import annotations

import importlib
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, "installed"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _detect_gpu() -> dict[str, Any]:
    info = {
        "available": False,
        "device_count": 0,
        "device_name": "",
        "nvidia_smi": False,
    }

    try:
        import torch

        info["available"] = bool(torch.cuda.is_available())
        info["device_count"] = int(torch.cuda.device_count())
        if info["available"] and info["device_count"] > 0:
            info["device_name"] = torch.cuda.get_device_name(0)
    except Exception:
        pass

    try:
        subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        info["nvidia_smi"] = True
    except Exception:
        info["nvidia_smi"] = False

    return info


def _build_engine_entry(
    *,
    engine_id: str,
    name: str,
    description: str,
    installed: bool,
    installable: bool,
    supported_by_app: bool,
    gpu_recommended: bool,
    gpu_info: dict[str, Any],
    detail: str,
) -> dict[str, Any]:
    return {
        "id": engine_id,
        "name": name,
        "description": description,
        "installed": installed,
        "installable": installable,
        "supported_by_app": supported_by_app,
        "selectable": bool(installed and supported_by_app),
        "gpu_recommended": gpu_recommended,
        "gpu_available": bool(gpu_info.get("available")),
        "detail": detail,
    }


def detect_ocr_environment() -> dict[str, Any]:
    gpu_info = _detect_gpu()

    tesseract_installed = shutil.which("tesseract") is not None
    olmocr_installed = shutil.which("olmocr") is not None

    easyocr_installed, easyocr_detail = _safe_import("easyocr")
    paddleocr_installed, paddleocr_detail = _safe_import("paddleocr")
    rapidocr_installed, rapidocr_detail = _safe_import("rapidocr_onnxruntime")

    engines = [
        _build_engine_entry(
            engine_id="easyocr",
            name="EasyOCR",
            description="딥러닝 기반 OCR, GPU 사용 가능",
            installed=easyocr_installed,
            installable=True,
            supported_by_app=True,
            gpu_recommended=True,
            gpu_info=gpu_info,
            detail=easyocr_detail,
        ),
        _build_engine_entry(
            engine_id="tesseract",
            name="Tesseract OCR",
            description="범용 로컬 OCR 엔진",
            installed=tesseract_installed,
            installable=True,
            supported_by_app=True,
            gpu_recommended=False,
            gpu_info=gpu_info,
            detail="installed" if tesseract_installed else "tesseract command not found",
        ),
        _build_engine_entry(
            engine_id="olmocr",
            name="olmOCR",
            description="GPU 기반 고품질 OCR CLI",
            installed=olmocr_installed,
            installable=bool(gpu_info.get("available")),
            supported_by_app=True,
            gpu_recommended=True,
            gpu_info=gpu_info,
            detail="installed" if olmocr_installed else "olmocr command not found",
        ),
        _build_engine_entry(
            engine_id="paddleocr",
            name="PaddleOCR",
            description="고품질 OCR, 한글/문서 인식 강화",
            installed=paddleocr_installed,
            installable=True,
            supported_by_app=True,
            gpu_recommended=True,
            gpu_info=gpu_info,
            detail=paddleocr_detail,
        ),
        _build_engine_entry(
            engine_id="rapidocr",
            name="RapidOCR",
            description="경량 OCR, CPU/ONNX 기반",
            installed=rapidocr_installed,
            installable=True,
            supported_by_app=False,
            gpu_recommended=False,
            gpu_info=gpu_info,
            detail=rapidocr_detail,
        ),
    ]

    recommended_engine = "easyocr" if easyocr_installed else ("tesseract" if tesseract_installed else "")

    return {
        "checked_at": _now_iso(),
        "gpu": gpu_info,
        "recommended_engine": recommended_engine,
        "engines": engines,
    }


def detect_selectable_ocr_engines() -> list[dict[str, Any]]:
    snapshot = detect_ocr_environment()
    return [engine for engine in snapshot["engines"] if engine.get("supported_by_app")]


def build_engine_option_map(snapshot: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    current = snapshot or detect_ocr_environment()
    return {
        str(engine.get("id")): engine
        for engine in current.get("engines", [])
        if engine.get("id")
    }
