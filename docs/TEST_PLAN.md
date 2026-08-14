# Test Plan

Tests are proportional to risk and focus on contract enforcement.

- Unit: report search/read boundaries, calculator AST allowlist, action parsing, labels, state persistence/recovery, hashes, sealing, scorer archive validation.
- Integration: mock API/local backends, multi-step action flow, malformed JSON recovery, retries, max-step invalid output, partial-run resume, deterministic scoring.
- Isolation: public-data field scan, runtime-bundle allowlist, Compose config inspection, non-overlapping networks/mounts, no Docker socket, scorer `network_mode: none`, and no exposed ports.
- Fairness: shared dataset/model/config hashes, no subset or scorer callback, final mode without detailed feedback, and deterministic handling of missing/invalid predictions.

Docker smoke tests verify the actual images and effective container settings when Docker is available. They are not duplicated into elaborate meta-tests once the required invariants are directly demonstrated.

