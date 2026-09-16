#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
terraform_dir="$repo_root/terraform"
output_dir="$repo_root/.generated/ansible"
output_file="$output_dir/hosts.json"

mkdir -p "$output_dir"
temporary_file=$(mktemp "$output_dir/hosts.json.XXXXXX")
trap 'rm -f "$temporary_file"' EXIT HUP INT TERM

terraform -chdir="$terraform_dir" output -json ansible_inventory |
  jq --sort-keys -e '
    if type != "object" or length == 0 then
      error("Terraform ansible_inventory output is empty")
    elif any(to_entries[]; (.value.ansible_host // "") == "") then
      error("Every inventory host requires ansible_host")
    elif any(to_entries[]; (.value.ansible_user // "") == "") then
      error("Every inventory host requires ansible_user")
    elif any(to_entries[]; (.value.ansible_groups | (type != "array" or length == 0))) then
      error("Every inventory host requires at least one ansible_group")
    else
      . as $machines
      | ([ $machines[].ansible_groups[] ] | unique) as $groups
      | {
          "all": {
            "vars": {
              "ansible_python_interpreter": "/usr/bin/python3"
            },
            "children": (
              reduce $groups[] as $group ({};
                .[$group] = {
                  "hosts": (
                    reduce ($machines | to_entries[]) as $machine ({};
                      if ($machine.value.ansible_groups | index($group)) then
                        .[$machine.key] = {
                          "ansible_host": $machine.value.ansible_host,
                          "ansible_port": $machine.value.ansible_port,
                          "ansible_user": $machine.value.ansible_user,
                          "homelab_virtiofs_mappings": ($machine.value.virtiofs_mappings // []),
                          "homelab_virtiofs_mounts": (
                            ($machine.value.virtiofs_mappings // [])
                            | map({
                                "tag": .,
                                "path": ("/srv/homelab/" + sub("^homelab-"; ""))
                              })
                          )
                        }
                      else
                        .
                      end
                    )
                  )
                }
              )
            )
          }
        }
    end
  ' >"$temporary_file"

chmod 0600 "$temporary_file"
mv "$temporary_file" "$output_file"
trap - EXIT HUP INT TERM

printf 'Generated %s\n' "$output_file"
