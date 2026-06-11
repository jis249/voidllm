package db

import (
	"context"
	"errors"
	"testing"

	"github.com/voidmind-io/voidllm/internal/config"
)

// TestCreateModel_WithFallbackModelID verifies that a model can be created
// with a FallbackModelID and that the stored value is retrievable.
func TestCreateModel_WithFallbackModelID(t *testing.T) {
	t.Parallel()

	d := openMigratedDB(t)

	ctx := context.Background()

	// Create the fallback target first.
	target := mustCreateModel(t, d, "fallback-target")

	// Create the source model with FallbackModelID pointing to target.
	source, err := d.CreateModel(ctx, CreateModelParams{
		Name:            "source-with-fallback",
		Provider:        "openai",
		BaseURL:         "https://api.openai.com/v1",
		Source:          "api",
		FallbackModelID: &target.ID,
	})
	if err != nil {
		t.Fatalf("CreateModel with FallbackModelID: %v", err)
	}

	if source.FallbackModelID == nil {
		t.Fatal("source.FallbackModelID is nil, want non-nil")
	}
	if *source.FallbackModelID != target.ID {
		t.Errorf("source.FallbackModelID = %q, want %q", *source.FallbackModelID, target.ID)
	}

	// Fetch the source model and re-verify.
	fetched, err := d.GetModel(ctx, source.ID)
	if err != nil {
		t.Fatalf("GetModel: %v", err)
	}
	if fetched.FallbackModelID == nil {
		t.Fatal("fetched.FallbackModelID is nil after fetch, want non-nil")
	}
	if *fetched.FallbackModelID != target.ID {
		t.Errorf("fetched.FallbackModelID = %q, want %q", *fetched.FallbackModelID, target.ID)
	}
}

// TestUpdateModel_SetFallbackToNil verifies that updating FallbackModelID to an
// empty string clears the column to NULL.
func TestUpdateModel_SetFallbackToNil(t *testing.T) {
	t.Parallel()

	d := openMigratedDB(t)
	ctx := context.Background()

	target := mustCreateModel(t, d, "upd-fallback-target")
	source, err := d.CreateModel(ctx, CreateModelParams{
		Name:            "upd-source-with-fallback",
		Provider:        "openai",
		BaseURL:         "https://api.openai.com/v1",
		Source:          "api",
		FallbackModelID: &target.ID,
	})
	if err != nil {
		t.Fatalf("CreateModel with FallbackModelID: %v", err)
	}
	if source.FallbackModelID == nil {
		t.Fatal("precondition: FallbackModelID must be set before clearing")
	}

	// Clear the fallback by passing a pointer to an empty string.
	empty := ""
	updated, err := d.UpdateModel(ctx, source.ID, UpdateModelParams{
		FallbackModelID: &empty,
	})
	if err != nil {
		t.Fatalf("UpdateModel (clear fallback): %v", err)
	}

	if updated.FallbackModelID != nil {
		t.Errorf("updated.FallbackModelID = %q, want nil (NULL)", *updated.FallbackModelID)
	}

	// Confirm via a fresh GetModel call.
	fetched, err := d.GetModel(ctx, source.ID)
	if err != nil {
		t.Fatalf("GetModel after clear: %v", err)
	}
	if fetched.FallbackModelID != nil {
		t.Errorf("fetched.FallbackModelID = %q after clear, want nil (NULL)", *fetched.FallbackModelID)
	}
}

// TestGetModelIDByName verifies that GetModelIDByName returns the correct ID
// for an existing model and ErrNotFound for a missing one.
func TestGetModelIDByName(t *testing.T) {
	t.Parallel()

	d := openMigratedDB(t)
	ctx := context.Background()

	m := mustCreateModel(t, d, "named-lookup-model")

	t.Run("existing model returns ID", func(t *testing.T) {
		t.Parallel()

		got, err := d.GetModelIDByName(ctx, "named-lookup-model")
		if err != nil {
			t.Fatalf("GetModelIDByName: %v", err)
		}
		if got != m.ID {
			t.Errorf("GetModelIDByName = %q, want %q", got, m.ID)
		}
	})

	t.Run("nonexistent model returns ErrNotFound", func(t *testing.T) {
		t.Parallel()

		_, err := d.GetModelIDByName(ctx, "does-not-exist")
		if !errors.Is(err, ErrNotFound) {
			t.Errorf("GetModelIDByName(nonexistent) error = %v, want ErrNotFound", err)
		}
	})
}

func TestSyncYAMLModels_DeletesStaleYAMLModels(t *testing.T) {
	t.Parallel()

	d := openMigratedDB(t)
	ctx := context.Background()
	encKey := []byte("0123456789abcdef0123456789abcdef")

	stale, err := d.CreateModel(ctx, CreateModelParams{
		Name:     "stale-yaml-model",
		Provider: "ollama",
		BaseURL:  "http://localhost:11434/v1",
		Source:   "yaml",
	})
	if err != nil {
		t.Fatalf("CreateModel(stale yaml): %v", err)
	}
	apiModel := mustCreateModel(t, d, "api-owned-model")

	err = d.SyncYAMLModels(ctx, []config.ModelConfig{
		{
			Name:     "current-yaml-model",
			Provider: "ollama",
			BaseURL:  "http://localhost:11434/v1",
			Aliases:  []string{"default"},
		},
	}, encKey)
	if err != nil {
		t.Fatalf("SyncYAMLModels: %v", err)
	}

	if _, err := d.GetModel(ctx, stale.ID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("stale yaml model lookup error = %v, want ErrNotFound", err)
	}
	if _, err := d.GetModel(ctx, apiModel.ID); err != nil {
		t.Fatalf("api model should be preserved: %v", err)
	}
	if _, err := d.GetModelByName(ctx, "current-yaml-model"); err != nil {
		t.Fatalf("current yaml model should exist: %v", err)
	}
}
