"""System usage / host metrics handler."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from wai.api.admin.common import KeyInfo, ROLE_SYSTEM_ADMIN
from wai.api.admin.handler import get_handler, require_role

router = APIRouter()

_STARTED_AT = time.time()


class SystemOSInfo(BaseModel):
    goos: str = Field(alias="goos")
    goarch: str = Field(alias="goarch")
    name: str = ""
    version: str = ""
    architecture: str = ""

    model_config = {"populate_by_name": True}


class SystemRuntimeInfo(BaseModel):
    go_version: str
    num_cpu: int
    uptime_seconds: int
    process_alloc_bytes: int = 0
    process_sys_bytes: int = 0
    process_heap_alloc_bytes: int = 0


class SystemMemoryInfo(BaseModel):
    total_bytes: int = 0
    available_bytes: int = 0
    used_bytes: int = 0
    used_percent: float = 0


class SystemCPUInfo(BaseModel):
    name: str
    cores: int
    logical_processors: int


class SystemDeviceInfo(BaseModel):
    name: str
    memory_bytes: int = 0


class SystemStorageInfo(BaseModel):
    name: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    used_percent: float
    file_system: str = ""
    volume_name: str = ""


class SystemUsageResponse(BaseModel):
    collected_at: datetime
    os: SystemOSInfo
    runtime: SystemRuntimeInfo
    memory: SystemMemoryInfo
    cpu: list[SystemCPUInfo] = Field(default_factory=list)
    gpu: list[SystemDeviceInfo] = Field(default_factory=list)
    npu: list[SystemDeviceInfo] = Field(default_factory=list)
    storage: list[SystemStorageInfo] = Field(default_factory=list)
    configuration: dict[str, str] = Field(default_factory=dict)


class ServerConfigResponse(BaseModel):
    fallback_max_depth: int


def _safe_config() -> dict[str, str]:
    keys = [
        "OLLAMA_HOST", "OLLAMA_FLASH_ATTENTION", "OLLAMA_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_NUM_PARALLEL", "WAI_DATABASE_PATH",
    ]
    return {k: v for k in keys if (v := os.environ.get(k))}


def _collect_windows(resp: SystemUsageResponse) -> None:
    script = (
        "$os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture,"
        "TotalVisibleMemorySize,FreePhysicalMemory; "
        "$cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); "
        "$storage = @(Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" | "
        "Select-Object DeviceID,VolumeName,FileSystem,Size,FreeSpace); "
        "[pscustomobject]@{ os=$os; cpu=$cpu; storage=$storage } | ConvertTo-Json -Depth 5 -Compress"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=5,
        )
        snap = json.loads(out)
        osinfo = snap.get("os") or {}
        resp.os.name = osinfo.get("Caption") or ""
        resp.os.version = osinfo.get("Version") or ""
        resp.os.architecture = osinfo.get("OSArchitecture") or ""
        total = int(osinfo.get("TotalVisibleMemorySize") or 0) * 1024
        avail = int(osinfo.get("FreePhysicalMemory") or 0) * 1024
        if total:
            used = total - avail
            resp.memory = SystemMemoryInfo(
                total_bytes=total, available_bytes=avail, used_bytes=used,
                used_percent=used / total * 100,
            )
        cpus = snap.get("cpu") or []
        if isinstance(cpus, dict):
            cpus = [cpus]
        for c in cpus:
            resp.cpu.append(SystemCPUInfo(
                name=c.get("Name") or "",
                cores=int(c.get("NumberOfCores") or 0),
                logical_processors=int(c.get("NumberOfLogicalProcessors") or 0),
            ))
        disks = snap.get("storage") or []
        if isinstance(disks, dict):
            disks = [disks]
        for d in disks:
            size = int(d.get("Size") or 0)
            if not size:
                continue
            free = int(d.get("FreeSpace") or 0)
            used = size - free
            resp.storage.append(SystemStorageInfo(
                name=d.get("DeviceID") or "",
                volume_name=d.get("VolumeName") or "",
                file_system=d.get("FileSystem") or "",
                total_bytes=size, free_bytes=free, used_bytes=used,
                used_percent=used / size * 100,
            ))
    except Exception:
        pass


@router.get("/system/usage", response_model=SystemUsageResponse)
async def system_usage(_: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN))) -> SystemUsageResponse:
    resp = SystemUsageResponse(
        collected_at=datetime.now(timezone.utc),
        os=SystemOSInfo(
            goos=platform.system().lower(),
            goarch=platform.machine(),
        ),
        runtime=SystemRuntimeInfo(
            go_version=sys.version.split()[0],
            num_cpu=os.cpu_count() or 1,
            uptime_seconds=int(time.time() - _STARTED_AT),
        ),
        memory=SystemMemoryInfo(),
        configuration=_safe_config(),
    )
    if platform.system().lower() == "windows":
        _collect_windows(resp)
    return resp


@router.get("/server-config", response_model=ServerConfigResponse)
async def server_config(_: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN))) -> ServerConfigResponse:
    h = get_handler()
    return ServerConfigResponse(fallback_max_depth=h.fallback_max_depth)
