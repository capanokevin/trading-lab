#!/usr/bin/env bash
set -euo pipefail

target_dir="${1:-secrets/revolut_x}"
private_key_path="${target_dir}/private.pem"
public_key_path="${target_dir}/public.pem"

mkdir -p "${target_dir}"

if [[ -e "${private_key_path}" || -e "${public_key_path}" ]]; then
  echo "Key files already exist in ${target_dir}. Move or delete them before generating new ones." >&2
  exit 1
fi

openssl genpkey -algorithm ed25519 -out "${private_key_path}"
openssl pkey -in "${private_key_path}" -pubout -out "${public_key_path}"
chmod 600 "${private_key_path}"

echo "Private key: ${private_key_path}"
echo "Public key:  ${public_key_path}"
echo "Upload ${public_key_path} in the Revolut X web app before creating the API key."

