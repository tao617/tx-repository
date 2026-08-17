from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "run_agent_with_env.sh"


def test_launcher_supports_iterative_and_nested_configs_with_path_confinement():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "run|baseline|iterative-rag" in text
    assert '"$command_name" != "iterative-rag"' in text
    assert 'config_path="$(realpath -e -- "$repo_root/configs/$config_name")"' in text
    assert '"$repo_root/configs/"*' in text
    assert '--config "/app/configs/$config_name"' in text
    assert "configuration path cannot contain dot segments" in text
    assert 'planned_run_identity_json="${FINDVER_RUN_IDENTITY_JSON:-}"' in text
    assert 'planned_expected_model_id="${FINDVER_EXPECTED_MODEL_ID:-}"' in text
    assert "MODEL_NAME does not match the planned effective model ID" in text
    assert 'runtime_command+=(--run-identity-json "$run_identity_json")' in text
