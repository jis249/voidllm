package admin_test

import (
	"encoding/json"
	"io"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gofiber/fiber/v3"
	"github.com/voidmind-io/voidllm/internal/auth"
)

func TestDashboardStats_FallsBackToRawUsageWhenHourlyRollupEmpty(t *testing.T) {
	t.Parallel()

	app, database, keyCache := setupTestApp(t, "file:TestDashboardStats_RawFallback?mode=memory&cache=private")
	org := mustCreateOrg(t, database, "Dashboard Org", "dashboard-org-raw-fallback")
	testKey := addTestKey(t, keyCache, auth.RoleOrgAdmin, org.ID)

	now := time.Now().UTC()
	insertUsageEventHTTP(t, database, "dash-raw-1", "key-dashboard", "", org.ID, "qwen3-coder:30b",
		100, 50, 150, now.Add(-30*time.Minute))

	req := httptest.NewRequest("GET", "/api/v1/dashboard/stats", nil)
	req.Header.Set("Authorization", "Bearer "+testKey)

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
		Requests24h int64 `json:"requests_24h"`
		Tokens24h   int64 `json:"tokens_24h"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatalf("decode response: %v", err)
	}

	if got.Requests24h != 1 {
		t.Errorf("requests_24h = %d, want 1", got.Requests24h)
	}
	if got.Tokens24h != 150 {
		t.Errorf("tokens_24h = %d, want 150", got.Tokens24h)
	}
}
