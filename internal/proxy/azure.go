package proxy

import (
	"net/http"
	"strings"

	"github.com/voidmind-io/voidllm/internal/jsonx"
)

// AzureAdapter adapts requests for the Azure OpenAI Service. Most Azure models
// speak the OpenAI wire format natively, so only URL construction and auth
// headers change. Newer GPT-5 deployments reject max_tokens and require
// max_completion_tokens instead, so that field is normalized when needed.
type AzureAdapter struct{}

// TransformRequest returns the body unchanged for most Azure deployments. GPT-5
// style deployments require max_completion_tokens instead of max_tokens.
func (a *AzureAdapter) TransformRequest(body []byte, model Model) ([]byte, error) {
	if !azureRequiresMaxCompletionTokens(model) {
		return body, nil
	}

	var doc map[string]jsonx.RawMessage
	if err := jsonx.Unmarshal(body, &doc); err != nil {
		return nil, err
	}
	if maxTokens, ok := doc["max_tokens"]; ok {
		if _, hasMaxCompletionTokens := doc["max_completion_tokens"]; !hasMaxCompletionTokens {
			doc["max_completion_tokens"] = maxTokens
		}
		delete(doc, "max_tokens")
	}
	return jsonx.Marshal(doc)
}

func azureRequiresMaxCompletionTokens(model Model) bool {
	name := strings.ToLower(model.Name)
	deployment := strings.ToLower(model.AzureDeployment)
	return strings.HasPrefix(name, "gpt-5") || strings.HasPrefix(deployment, "gpt-5")
}

// TransformURL builds the Azure OpenAI deployment URL from the base URL and
// model metadata. The resulting URL has the form:
//
//	{baseURL}/openai/deployments/{deployment}/{upstreamPath}?api-version={version}
//
// When AzureAPIVersion is not set on the model, the current GA version
// "2024-10-21" is used as the default.
func (a *AzureAdapter) TransformURL(baseURL, upstreamPath string, model Model) string {
	version := model.AzureAPIVersion
	if version == "" {
		version = "2024-10-21"
	}
	u := strings.TrimRight(baseURL, "/") +
		"/openai/deployments/" + model.AzureDeployment +
		"/" + upstreamPath +
		"?api-version=" + version
	return u
}

// SetHeaders configures Azure-specific authentication. Azure uses the "api-key"
// header instead of Bearer Authorization.
func (a *AzureAdapter) SetHeaders(req *http.Request, model Model) {
	req.Header.Del("Authorization")
	if model.APIKey != "" {
		req.Header.Set("api-key", model.APIKey)
	}
}

// TransformResponse returns the body unchanged; Azure responses are already in
// OpenAI format.
func (a *AzureAdapter) TransformResponse(body []byte) ([]byte, error) {
	return body, nil
}

// TransformStreamLine returns the line unchanged; Azure streams are already in
// OpenAI SSE format.
func (a *AzureAdapter) TransformStreamLine(line []byte) []byte {
	return line
}

// StreamUsage returns a zero UsageInfo. Azure streams the OpenAI wire format,
// so usage is extracted by the streamUsageExtractor in the proxy handler rather
// than by this adapter.
func (a *AzureAdapter) StreamUsage() UsageInfo {
	return UsageInfo{}
}
