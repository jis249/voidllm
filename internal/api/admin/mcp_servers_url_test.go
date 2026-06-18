package admin

import (
	"net/http/httptest"
	"testing"

	"github.com/gofiber/fiber/v3"
)

func TestPublicBaseURLFromRequest(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		headers map[string]string
		want    string
	}{
		{
			name: "forwarded proto and host",
			headers: map[string]string{
				"X-Forwarded-Proto": "https",
				"X-Forwarded-Host":  "ai.waiin.com",
			},
			want: "https://ai.waiin.com",
		},
		{
			name: "host only defaults to https",
			headers: map[string]string{
				"Host": "ai.waiin.com",
			},
			want: "https://ai.waiin.com",
		},
		{
			name: "localhost defaults to http",
			headers: map[string]string{
				"Host": "localhost:8080",
			},
			want: "http://localhost:8080",
		},
		{
			name: "first forwarded value wins",
			headers: map[string]string{
				"X-Forwarded-Proto": "https, http",
				"X-Forwarded-Host":  "ai.waiin.com, internal.local",
			},
			want: "https://ai.waiin.com",
		},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			app := fiber.New()
			var got string
			app.Get("/", func(c fiber.Ctx) error {
				got = publicBaseURLFromRequest(c)
				return nil
			})

			req := httptest.NewRequest("GET", "/", nil)
			for k, v := range tc.headers {
				if k == "Host" {
					req.Host = v
				} else {
					req.Header.Set(k, v)
				}
			}

			resp, err := app.Test(req)
			if err != nil {
				t.Fatalf("app.Test: %v", err)
			}
			resp.Body.Close()

			if got != tc.want {
				t.Errorf("publicBaseURLFromRequest() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestBuiltinMCPProxyURL(t *testing.T) {
	t.Parallel()

	got := builtinMCPProxyURL("https://ai.waiin.com", "voidllm")
	want := "https://ai.waiin.com/api/v1/mcp/voidllm"
	if got != want {
		t.Errorf("builtinMCPProxyURL() = %q, want %q", got, want)
	}
}
