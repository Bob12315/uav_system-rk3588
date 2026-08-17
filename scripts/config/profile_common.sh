#!/usr/bin/env bash

profile_require_send_commands_off() {
  local app_config="$1"
  python - "${app_config}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
in_executor = False
executor_indent = None
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line_without_comment = raw_line.split("#", 1)[0].rstrip()
    if not line_without_comment.strip():
        continue
    indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
    stripped = line_without_comment.strip()
    if stripped == "executor:":
        in_executor = True
        executor_indent = indent
        continue
    if in_executor and indent <= (executor_indent or 0):
        in_executor = False
    if in_executor and stripped.startswith("send_commands:"):
        value = stripped.split(":", 1)[1].strip()
        if value == "false":
            raise SystemExit(0)
        raise SystemExit("Refusing profile operation: config/app.yaml executor.send_commands must be false")

raise SystemExit("Refusing profile operation: config/app.yaml executor.send_commands was not found")
PY
}

profile_apply() {
  local repo_root="$1"
  local profile_dir="$2"

  python "${repo_root}/scripts/config/render_profile.py" \
    --repo-root "${repo_root}" --profile "${profile_dir}/profile.yaml" --write

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

  echo "Profiles are reviewed delta files; automatic full-config snapshots are disabled." >&2
  return 1

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
