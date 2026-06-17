package config

import (
	"bufio"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// envVarRe matches ${VAR} and ${VAR:-fallback} patterns in configuration files.
// group 1: variable name, group 2: optional fallback value after :-
var envVarRe = regexp.MustCompile(`\$\{([^}:]+)(?::-(.*?))?\}`)

// interpolateEnv replaces all ${VAR} and ${VAR:-fallback} references in data
// with the corresponding environment variable values. If the variable is unset
// or empty and a fallback is provided, the fallback is used. If no fallback is
// provided and the variable is unset, the reference is replaced with an empty string.
// loadLocalEnvFile reads KEY=VALUE pairs from .env.local beside the config
// file. Values already present in the process environment are left unchanged.
func loadLocalEnvFile(configPath string) {
	if configPath == "" {
		return
	}
	envPath := filepath.Join(filepath.Dir(configPath), ".env.local")
	f, err := os.Open(envPath)
	if err != nil {
		return
	}
	defer f.Close() //nolint:errcheck // read-only local env file

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		name, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		name = strings.TrimSpace(name)
		value = strings.TrimSpace(value)
		if name == "" {
			continue
		}
		if os.Getenv(name) == "" {
			_ = os.Setenv(name, value)
		}
	}
}

func interpolateEnv(data []byte) []byte {
	return envVarRe.ReplaceAllFunc(data, func(match []byte) []byte {
		parts := envVarRe.FindSubmatch(match)
		// parts[1] is the variable name, parts[2] is the optional fallback.
		name := string(parts[1])
		fallback := string(parts[2])

		if val := os.Getenv(name); val != "" {
			return []byte(val)
		}
		return []byte(fallback)
	})
}
