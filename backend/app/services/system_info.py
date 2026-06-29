from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT


def _round_gb(num_bytes: int | float) -> float:
    return round(float(num_bytes) / (1024 ** 3), 1)


def _get_memory_total_bytes() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * phys_pages)
    except Exception:
        pass

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb * 1024
        except Exception:
            return None
    return None


def _get_disk_info(path: str | Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_gb": _round_gb(usage.total),
        "used_gb": _round_gb(usage.used),
        "free_gb": _round_gb(usage.free),
    }


def _run_nvidia_smi() -> list[dict[str, Any]]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version,cuda_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    gpus: list[dict[str, Any]] = []
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
        gpus.append(
            {
                "name": parts[0],
                "memory_mb": memory_mb,
                "memory_gb": round(memory_mb / 1024, 1) if memory_mb else 0,
                "driver_version": parts[2],
                "cuda_version": parts[3],
            }
        )
    return gpus


def _torch_cuda_info() -> dict[str, Any]:
    try:
        import torch

        available = bool(torch.cuda.is_available())
        info = {
            "available": available,
            "device_count": int(torch.cuda.device_count()),
            "device_name": torch.cuda.get_device_name(0) if available and torch.cuda.device_count() > 0 else "",
        }
        return info
    except Exception:
        return {
            "available": False,
            "device_count": 0,
            "device_name": "",
        }


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _module_exists(module_name: str) -> bool:
    try:
        import_module(module_name)
        return True
    except Exception:
        return False


def _tesseract_languages() -> set[str]:
    if not _command_exists("tesseract"):
        return set()
    try:
        proc = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return set()
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return set()
        return set(lines[1:] if "List of available languages" in lines[0] else lines)
    except Exception:
        return set()


def _venv_hwp5txt_exists() -> bool:
    bin_dir = Path(sys.executable).parent
    return (bin_dir / "hwp5txt").exists() or (bin_dir / "hwp5txt.exe").exists() or _command_exists("hwp5txt")


def _build_required_programs() -> tuple[list[dict[str, Any]], str]:
    langs = _tesseract_languages()
    items = [
        {
            "id": "ollama",
            "label": "Ollama",
            "installed": _command_exists("ollama"),
            "required": True,
            "purpose": "LLM 응답 생성 및 임베딩 모델 실행",
            "install_hint": "Ollama 설치 및 서비스 실행이 필요합니다.",
        },
        {
            "id": "tesseract",
            "label": "Tesseract OCR",
            "installed": _command_exists("tesseract"),
            "required": True,
            "purpose": "스캔 PDF 및 이미지 OCR",
            "install_hint": "tesseract-ocr 패키지 설치가 필요합니다.",
        },
        {
            "id": "tesseract_lang",
            "label": "Tesseract 언어팩 (kor, eng)",
            "installed": "kor" in langs and "eng" in langs,
            "required": True,
            "purpose": "한글/영문 OCR 정확도 확보",
            "install_hint": "tesseract-ocr-kor, tesseract-ocr-eng 설치가 필요합니다.",
        },
        {
            "id": "poppler",
            "label": "Poppler (pdftoppm)",
            "installed": _command_exists("pdftoppm"),
            "required": True,
            "purpose": "PDF를 이미지로 변환해 OCR 수행",
            "install_hint": "poppler-utils 설치가 필요합니다.",
        },
        {
            "id": "libreoffice",
            "label": "LibreOffice (soffice)",
            "installed": _command_exists("soffice"),
            "required": True,
            "purpose": "HWP/PPTX 등을 PDF로 변환하는 fallback 처리",
            "install_hint": "libreoffice 설치가 필요합니다.",
        },
        {
            "id": "hwp5txt",
            "label": "hwp5txt / pyhwp",
            "installed": _venv_hwp5txt_exists(),
            "required": True,
            "purpose": "구형 HWP 직접 텍스트 추출",
            "install_hint": "가상환경에 pyhwp 설치가 필요합니다.",
        },
        {
            "id": "easyocr",
            "label": "EasyOCR",
            "installed": _module_exists("easyocr"),
            "required": False,
            "purpose": "GPU 기반 고품질 OCR 보완 엔진",
            "install_hint": "pip로 easyocr 설치 시 GPU OCR 품질을 높일 수 있습니다.",
        },
    ]

    missing_required = [item["label"] for item in items if item["required"] and not item["installed"]]
    if missing_required:
        message = "운영 전 필수 프로그램 설치 필요: " + ", ".join(missing_required)
    else:
        message = "운영에 필요한 기본 프로그램이 설치되어 있습니다."

    return items, message


def collect_system_info() -> dict[str, Any]:
    cpu_count = os.cpu_count() or 0
    memory_total = _get_memory_total_bytes()
    root_disk = _get_disk_info(PROJECT_ROOT)
    gpus = _run_nvidia_smi()
    torch_cuda = _torch_cuda_info()
    required_programs, required_program_message = _build_required_programs()

    install_checks: list[dict[str, Any]] = [
        {
            "id": "cpu",
            "label": "CPU 코어 수",
            "ok": cpu_count >= 4,
            "detail": f"{cpu_count} cores",
        },
        {
            "id": "memory",
            "label": "메모리",
            "ok": (memory_total or 0) >= 8 * 1024 ** 3,
            "detail": f"{_round_gb(memory_total) if memory_total else 0} GB",
        },
        {
            "id": "disk",
            "label": "프로젝트 디스크 여유 공간",
            "ok": root_disk["free_gb"] >= 20,
            "detail": f"{root_disk['free_gb']} GB free",
        },
        {
            "id": "gpu",
            "label": "GPU OCR 가속",
            "ok": bool(gpus) or bool(torch_cuda["available"]),
            "detail": gpus[0]["name"] if gpus else (torch_cuda["device_name"] or "GPU 없음"),
        },
    ]

    install_ready = all(check["ok"] for check in install_checks[:3])
    gpu_ready = install_checks[3]["ok"]

    return {
        "hostname": platform.node(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "cpu": {
            "cores_logical": cpu_count,
            "processor": platform.processor() or platform.machine(),
        },
        "memory": {
            "total_gb": _round_gb(memory_total) if memory_total else 0,
        },
        "disk": root_disk,
        "gpu": {
            "cards": gpus,
            "torch_cuda": torch_cuda,
        },
        "required_programs": required_programs,
        "required_program_message": required_program_message,
        "install_checks": install_checks,
        "install_ready": install_ready,
        "gpu_ocr_ready": gpu_ready,
    }
