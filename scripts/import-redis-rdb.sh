#!/usr/bin/env bash
# Importa dados Redis no volume local usado pelo projeto.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Uso: $0 CAMINHO/para/arquivo.rdb-ou-comandos.redis" >&2
  exit 2
fi

source_file=$1
if [[ ! -f "$source_file" ]]; then
  echo "Arquivo de importação não encontrado: $source_file" >&2
  exit 2
fi

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="$project_dir/docker-compose.yml"
data_dir="$project_dir/data"
target_rdb="$data_dir/dump.rdb"
temporary_rdb="$data_dir/.dump.rdb.importing"

if [[ "$source_file" != *.rdb ]]; then
  echo "Iniciando o Redis..."
  docker compose -f "$compose_file" up -d redis
  echo "Importando comandos Redis..."
  docker compose -f "$compose_file" exec -T redis redis-cli --pipe < "$source_file"
  echo "Importação concluída sem apagar dados existentes."
  exit 0
fi

mkdir -p "$data_dir"
cp -- "$source_file" "$temporary_rdb"

echo "Parando o Redis..."
docker compose -f "$compose_file" stop redis

if [[ -f "$target_rdb" ]]; then
  backup_rdb="$data_dir/dump.rdb.backup.$(date +%Y%m%d%H%M%S)"
  cp -- "$target_rdb" "$backup_rdb"
  echo "Backup do banco atual criado em: $backup_rdb"
fi

mv -- "$temporary_rdb" "$target_rdb"
echo "Banco importado em: $target_rdb"

echo "Iniciando o Redis..."
docker compose -f "$compose_file" up -d redis
