#!/usr/bin/env bash

profile_require_send_commands_off() {
  local app_config="$1"
  python - "${app_config}" <<'PY'
from pathlib import Path
import sys

import yaml

data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
if data.get("executor", {}).get("send_commands") is not False:
    raise SystemExit("Refusing profile operation: config/app.yaml executor.send_commands must be false")
PY
}

profile_apply() {
  local repo_root="$1"
  local profile_dir="$2"

  cp "${profile_dir}/telemetry.yaml" "${repo_root}/config/telemetry.yaml"
  cp "${profile_dir}/yolo.yaml" "${repo_root}/config/yolo.yaml"

  if [[ -d "${profile_dir}/action_missions" ]]; then
    mkdir -p "${repo_root}/config/action_missions"
    while IFS= read -r -d '' source_path; do
      cp "${source_path}" "${repo_root}/config/action_missions/"
    done < <(find "${profile_dir}/action_missions" -maxdepth 1 -name '*.json' -type f -print0)
  fi

  if [[ -d "${profile_dir}/missions" ]]; then
    while IFS= read -r -d '' source_path; do
      local relative_path="${source_path#${profile_dir}/}"
      local target_path="${repo_root}/${relative_path}"
      mkdir -p "$(dirname "${target_path}")"
      cp "${source_path}" "${target_path}"
    done < <(find "${profile_dir}/missions" -path '*/config.yaml' -type f -print0)
  fi
}

profile_save() {
  local repo_root="$1"
  local profile_dir="$2"

  mkdir -p "${profile_dir}"
  cp "${repo_root}/config/telemetry.yaml" "${profile_dir}/telemetry.yaml"
  cp "${repo_root}/config/yolo.yaml" "${profile_dir}/yolo.yaml"

  rm -rf "${profile_dir}/action_missions"
  mkdir -p "${profile_dir}/action_missions"
  while IFS= read -r -d '' source_path; do
    cp "${source_path}" "${profile_dir}/action_missions/"
  done < <(find "${repo_root}/config/action_missions" -maxdepth 1 -name '*.json' -type f -print0)

  rm -rf "${profile_dir}/missions"
  while IFS= read -r -d '' source_path; do
    local relative_path="${source_path#${repo_root}/}"
    local target_path="${profile_dir}/${relative_path}"
    mkdir -p "$(dirname "${target_path}")"
    cp "${source_path}" "${target_path}"
  done < <(find "${repo_root}/missions" -path '*/config.yaml' -type f -print0)
}

profile_print_saved_files() {
  local repo_root="$1"
  local profile_dir="$2"

  find "${profile_dir}" -type f \
    \( -name '*.yaml' -o -name '*.json' \) \
    -printf "  %P\n" | sort
  echo
  echo "Review changes with:"
  echo "  git diff -- ${profile_dir#${repo_root}/}"
}
