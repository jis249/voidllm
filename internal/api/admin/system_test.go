package admin_test

import (
	"encoding/json"
	"io"
	"net/http/httptest"
	"testing"

	"github.com/gofiber/fiber/v3"
	"github.com/voidmind-io/voidllm/internal/auth"
)

func TestSystemUsage_RequiresSystemAdmin(t *testing.T) {
	t.Parallel()

	app, database, keyCache := setupTestApp(t, "file:TestSystemUsage_RequiresSystemAdmin?mode=memory&cache=private")
	org := mustCreateOrg(t, database, "System Usage Org", "system-usage-org")
	memberKey := addTestKey(t, keyCache, auth.RoleMember, org.ID)

	req := httptest.NewRequest("GET", "/api/v1/system/usage", nil)
	req.Header.Set("Authorization", "Bearer "+memberKey)

	resp, err := app.Test(req, fiber.TestConfig{Timeout: testTimeout})
	if err != nil {
		t.Fatalf("app.Test: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != fiber.StatusForbidden {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 403; body: %s", resp.StatusCode, body)
	}
}

func TestSystemUsage_SystemAdminCanRead(t *testing.T) {
	t.Parallel()

	app, _, keyCache := setupTestApp(t, "file:TestSystemUsage_SystemAdminCanRead?mode=memory&cache=private")
	adminKey := addTestKey(t, keyCache, auth.RoleSystemAdmin, "")

	req := httptest.NewRequest("GET", "/api/v1/system/usage", nil)
	req.Header.Set("Authorization", "Bearer "+adminKey)

	resp, err := app.Test(req, fiber.TestConfig{Timeout: testTimeout})
	if err != nil {
		t.Fatalf("app.Test: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != fiber.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, want 200; body: %s", resp.StatusCode, body)
	}

	var got struct {
		Runtime struct {
			NumCPU int `json:"num_cpu"`
		} `json:"runtime"`
		Configuration map[string]string `json:"configuration"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if got.Runtime.NumCPU <= 0 {
		t.Errorf("runtime.num_cpu = %d, want > 0", got.Runtime.NumCPU)
	}
}
