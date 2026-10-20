#!/usr/bin/env bash
# Keep flags identical across cold and same-workspace warm invocations.
set -euo pipefail
if (( $# < 3 )); then
  echo "Usage: $0 LABEL {build|test} TARGET [BAZEL_OPTION ...]" >&2
  exit 2
fi
label=$1
command=$2
shift 2
[[ "$label" =~ ^[a-z0-9-]+$ ]] || exit 2
[[ "$command" == build || "$command" == test ]] || exit 2
profile_dir=${PROFILE_DIR:-ci-profiles}
mkdir -p "$profile_dir"
printf '%q ' bazel "$command" "$@" > "$profile_dir/$label.command.txt"
printf '\n' >> "$profile_dir/$label.command.txt"
python3 "$(dirname "${BASH_SOURCE[0]}")/time_command.py" \
  "$profile_dir/$label.time.json" \
  bazel "$command" \
    --profile="$profile_dir/$label.profile.gz" \
    --build_event_json_file="$profile_dir/$label.bep.jsonl" \
    --noslim_profile \
    --experimental_profile_include_target_label \
    --experimental_profile_include_primary_output \
    --experimental_profile_additional_tasks=fetch \
    --experimental_profile_additional_tasks=repository_fetch \
    --experimental_profile_additional_tasks=bzlmod \
    "$@" 2>&1 | tee "$profile_dir/$label.console.log"
