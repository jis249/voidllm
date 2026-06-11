package admin

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/gofiber/fiber/v3"
)

var systemStartedAt = time.Now().UTC()

type systemUsageResponse struct {
	CollectedAt   time.Time           `json:"collected_at"`
	OS            systemOSInfo        `json:"os"`
	Runtime       systemRuntimeInfo   `json:"runtime"`
	Memory        systemMemoryInfo    `json:"memory"`
	CPU           []systemCPUInfo     `json:"cpu"`
	GPU           []systemDeviceInfo  `json:"gpu"`
	NPU           []systemDeviceInfo  `json:"npu"`
	Storage       []systemStorageInfo `json:"storage"`
	Configuration map[string]string   `json:"configuration"`
}

type systemOSInfo struct {
	GOOS         string `json:"goos"`
	GOARCH       string `json:"goarch"`
	Name         string `json:"name,omitempty"`
	Version      string `json:"version,omitempty"`
	Architecture string `json:"architecture,omitempty"`
}

type systemRuntimeInfo struct {
	GoVersion             string `json:"go_version"`
	NumCPU                int    `json:"num_cpu"`
	UptimeSeconds         int64  `json:"uptime_seconds"`
	ProcessAllocBytes     uint64 `json:"process_alloc_bytes"`
	ProcessSysBytes       uint64 `json:"process_sys_bytes"`
	ProcessHeapAllocBytes uint64 `json:"process_heap_alloc_bytes"`
}

type systemMemoryInfo struct {
	TotalBytes     uint64  `json:"total_bytes"`
	AvailableBytes uint64  `json:"available_bytes"`
	UsedBytes      uint64  `json:"used_bytes"`
	UsedPercent    float64 `json:"used_percent"`
}

type systemCPUInfo struct {
	Name              string `json:"name"`
	Cores             int    `json:"cores"`
	LogicalProcessors int    `json:"logical_processors"`
}

type systemDeviceInfo struct {
	Name        string `json:"name"`
	MemoryBytes uint64 `json:"memory_bytes,omitempty"`
}

type systemStorageInfo struct {
	Name        string  `json:"name"`
	TotalBytes  uint64  `json:"total_bytes"`
	FreeBytes   uint64  `json:"free_bytes"`
	UsedBytes   uint64  `json:"used_bytes"`
	UsedPercent float64 `json:"used_percent"`
	FileSystem  string  `json:"file_system,omitempty"`
	VolumeName  string  `json:"volume_name,omitempty"`
}

// SystemUsage handles GET /api/v1/system/usage.
func (h *Handler) SystemUsage(c fiber.Ctx) error {
	resp := collectSystemUsage(c.Context())
	return c.JSON(resp)
}

func collectSystemUsage(ctx context.Context) systemUsageResponse {
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)

	resp := systemUsageResponse{
		CollectedAt: time.Now().UTC(),
		OS: systemOSInfo{
			GOOS:   runtime.GOOS,
			GOARCH: runtime.GOARCH,
		},
		Runtime: systemRuntimeInfo{
			GoVersion:             runtime.Version(),
			NumCPU:                runtime.NumCPU(),
			UptimeSeconds:         int64(time.Since(systemStartedAt).Seconds()),
			ProcessAllocBytes:     mem.Alloc,
			ProcessSysBytes:       mem.Sys,
			ProcessHeapAllocBytes: mem.HeapAlloc,
		},
		Configuration: safeSystemConfiguration(),
	}

	if runtime.GOOS == "windows" {
		applyWindowsSystemUsage(ctx, &resp)
	}

	return resp
}

func safeSystemConfiguration() map[string]string {
	keys := []string{
		"OLLAMA_HOST",
		"OLLAMA_FLASH_ATTENTION",
		"OLLAMA_KEEP_ALIVE",
		"OLLAMA_MAX_LOADED_MODELS",
		"OLLAMA_NUM_PARALLEL",
		"VOIDLLM_DATABASE_DRIVER",
	}
	cfg := make(map[string]string, len(keys))
	for _, key := range keys {
		if val := os.Getenv(key); val != "" {
			cfg[key] = val
		}
	}
	return cfg
}

type windowsSystemSnapshot struct {
	OS      windowsOSInfo       `json:"os"`
	CPU     []windowsCPUInfo    `json:"cpu"`
	GPU     []windowsDeviceInfo `json:"gpu"`
	NPU     []windowsDeviceInfo `json:"npu"`
	Storage []windowsDiskInfo   `json:"storage"`
}

type windowsOSInfo struct {
	Caption                string `json:"Caption"`
	Version                string `json:"Version"`
	OSArchitecture         string `json:"OSArchitecture"`
	TotalVisibleMemorySize uint64 `json:"TotalVisibleMemorySize"`
	FreePhysicalMemory     uint64 `json:"FreePhysicalMemory"`
}

type windowsCPUInfo struct {
	Name                      string `json:"Name"`
	NumberOfCores             int    `json:"NumberOfCores"`
	NumberOfLogicalProcessors int    `json:"NumberOfLogicalProcessors"`
}

type windowsDeviceInfo struct {
	Name       string  `json:"Name"`
	AdapterRAM *uint64 `json:"AdapterRAM"`
}

type windowsDiskInfo struct {
	DeviceID   string `json:"DeviceID"`
	VolumeName string `json:"VolumeName"`
	FileSystem string `json:"FileSystem"`
	Size       uint64 `json:"Size"`
	FreeSpace  uint64 `json:"FreeSpace"`
}

func applyWindowsSystemUsage(ctx context.Context, resp *systemUsageResponse) {
	snapshot, err := readWindowsSystemSnapshot(ctx)
	if err != nil {
		return
	}

	resp.OS.Name = snapshot.OS.Caption
	resp.OS.Version = snapshot.OS.Version
	resp.OS.Architecture = snapshot.OS.OSArchitecture

	total := snapshot.OS.TotalVisibleMemorySize * 1024
	available := snapshot.OS.FreePhysicalMemory * 1024
	if total > 0 {
		used := total - available
		resp.Memory = systemMemoryInfo{
			TotalBytes:     total,
			AvailableBytes: available,
			UsedBytes:      used,
			UsedPercent:    float64(used) / float64(total) * 100,
		}
	}

	for _, cpu := range snapshot.CPU {
		resp.CPU = append(resp.CPU, systemCPUInfo{
			Name:              cpu.Name,
			Cores:             cpu.NumberOfCores,
			LogicalProcessors: cpu.NumberOfLogicalProcessors,
		})
	}
	for _, gpu := range snapshot.GPU {
		if gpu.Name == "" {
			continue
		}
		var memoryBytes uint64
		if gpu.AdapterRAM != nil {
			memoryBytes = *gpu.AdapterRAM
		}
		resp.GPU = append(resp.GPU, systemDeviceInfo{
			Name:        gpu.Name,
			MemoryBytes: memoryBytes,
		})
	}
	applyNVIDIASMI(ctx, resp)
	for _, npu := range snapshot.NPU {
		if npu.Name == "" {
			continue
		}
		resp.NPU = append(resp.NPU, systemDeviceInfo{Name: npu.Name})
	}
	for _, disk := range snapshot.Storage {
		if disk.Size == 0 {
			continue
		}
		used := disk.Size - disk.FreeSpace
		resp.Storage = append(resp.Storage, systemStorageInfo{
			Name:        disk.DeviceID,
			VolumeName:  disk.VolumeName,
			FileSystem:  disk.FileSystem,
			TotalBytes:  disk.Size,
			FreeBytes:   disk.FreeSpace,
			UsedBytes:   used,
			UsedPercent: float64(used) / float64(disk.Size) * 100,
		})
	}
}

func applyNVIDIASMI(ctx context.Context, resp *systemUsageResponse) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()

	out, err := exec.CommandContext(ctx, "nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits").Output()
	if err != nil {
		return
	}

	reader := csv.NewReader(strings.NewReader(string(out)))
	records, err := reader.ReadAll()
	if err != nil {
		return
	}

	for _, record := range records {
		if len(record) < 2 {
			continue
		}
		name := strings.TrimSpace(record[0])
		totalMiB, err := strconv.ParseUint(strings.TrimSpace(record[1]), 10, 64)
		if err != nil || name == "" || totalMiB == 0 {
			continue
		}
		memoryBytes := totalMiB * 1024 * 1024
		found := false
		for i := range resp.GPU {
			if strings.EqualFold(resp.GPU[i].Name, name) {
				resp.GPU[i].MemoryBytes = memoryBytes
				found = true
				break
			}
		}
		if !found {
			resp.GPU = append(resp.GPU, systemDeviceInfo{
				Name:        name,
				MemoryBytes: memoryBytes,
			})
		}
	}
}

func readWindowsSystemSnapshot(ctx context.Context) (windowsSystemSnapshot, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	script := `$os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory; ` +
		`$cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); ` +
		`$gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM); ` +
		`$npu = @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'NPU|Neural|AI Boost|VPU|Vision Processing' } | Select-Object Name); ` +
		`$storage = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,VolumeName,FileSystem,Size,FreeSpace); ` +
		`[pscustomobject]@{ os=$os; cpu=$cpu; gpu=$gpu; npu=$npu; storage=$storage } | ConvertTo-Json -Depth 5 -Compress`

	out, err := exec.CommandContext(ctx, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script).Output()
	if err != nil {
		return windowsSystemSnapshot{}, err
	}

	var snapshot windowsSystemSnapshot
	if err := json.Unmarshal(out, &snapshot); err != nil {
		return windowsSystemSnapshot{}, err
	}
	return snapshot, nil
}
