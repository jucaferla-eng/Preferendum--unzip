#!/usr/bin/env bash
#
# tools/backup_db.sh — respaldo de la base de datos de Preferendum.
#
# Produce un respaldo en formato CUSTOM de PostgreSQL (-Fc), comprimido y
# restaurable de forma selectiva, acompañado de:
#   · un fichero .sha256 con la suma de comprobación
#   · un manifiesto .json con el recuento de filas de las tablas críticas
#
# El manifiesto es lo que convierte el respaldo en verificable: sin él,
# "el pg_dump terminó sin error" es lo único que se sabe, y eso no prueba
# que el contenido esté completo. Con él, la restauración se puede
# comparar fila a fila contra el origen (ver tools/verify_backup_restore.sh).
#
# NUNCA imprime la URL de conexión ni ninguna credencial: solo el host y la
# base, que es lo necesario para saber sobre qué se actuó.
#
# Uso:
#   DATABASE_URL=postgresql://... tools/backup_db.sh [directorio_destino]
#
# Requiere pg_dump y psql de la MISMA versión mayor que el servidor, o
# superior. pg_dump se niega a respaldar un servidor más nuevo que él.
#
set -euo pipefail

DEST="${1:-./backups}"
URL="${DATABASE_URL:-}"

if [[ -z "$URL" ]]; then
  echo "ERROR: falta DATABASE_URL." >&2
  exit 2
fi

# SQLAlchemy usa postgresql+psycopg2://; las herramientas de PostgreSQL no
# entienden ese sufijo de driver.
URL="${URL/postgresql+psycopg2:\/\//postgresql://}"
URL="${URL/postgres:\/\//postgresql://}"

if [[ "$URL" != postgresql://* ]]; then
  echo "ERROR: este respaldo solo cubre PostgreSQL (DATABASE_URL no lo es)." >&2
  echo "       Para SQLite basta copiar el fichero .db con la app detenida." >&2
  exit 2
fi

for bin in pg_dump psql sha256sum shasum; do :; done
command -v pg_dump >/dev/null || { echo "ERROR: falta pg_dump." >&2; exit 3; }
command -v psql    >/dev/null || { echo "ERROR: falta psql." >&2; exit 3; }

# Suma de comprobación: sha256sum en Linux, shasum -a 256 en macOS.
if command -v sha256sum >/dev/null; then
  SHA() { sha256sum "$1" | awk '{print $1}'; }
else
  SHA() { shasum -a 256 "$1" | awk '{print $1}'; }
fi

mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$DEST/preferendum-$STAMP"
DUMP="$BASE.dump"
MANIFEST="$BASE.manifest.json"

# Identificación sin secretos: host y nombre de base, nunca usuario ni clave.
DESCRIBE="$(psql "$URL" -XAt -c \
  "SELECT current_database() || ' @ ' || coalesce(inet_server_addr()::text,'local')" 2>/dev/null || echo 'desconocido')"
echo "[respaldo] origen: $DESCRIBE"
echo "[respaldo] destino: $DUMP"

# ── Tablas críticas ──────────────────────────────────────────────────────
# Son las que deciden si una restauración sirve o no: identidad, papeletas,
# consultas, dinero y anclajes. Si el manifiesto de la restauración no
# coincide con el del origen en ESTAS, la restauración no es válida, por
# muy "exitosa" que haya salido el comando.
# Nombres verificados contra los modelos y las migraciones reales, no de
# memoria: la tabla de impresiones es `ad_impression_logs` (plural) y el
# código de verificación del voto vive en `debate_votes.verify_code`, no en
# una tabla aparte.
CRITICAL=(
  users
  debates
  debate_votes
  debate_has_voted
  vote_identity_locks
  national_id_vote_log
  ad_campaigns
  ad_impression_logs
  ledger_accounts
  ledger_transactions
  ledger_entries
  ledger_balances
  credit_accounts
  commune_market_data
)

echo "[respaldo] contando filas de las tablas críticas…"
ROWS="{"
FIRST=1
for t in "${CRITICAL[@]}"; do
  # Cada tabla en su propio SAVEPOINT implícito: una tabla ausente no debe
  # abortar el recuento de las demás (en PostgreSQL un error aborta la
  # transacción completa).
  n="$(psql "$URL" -XAt -c "SELECT count(*) FROM $t" 2>/dev/null || echo 'null')"
  [[ -z "$n" ]] && n='null'
  [[ $FIRST -eq 1 ]] && FIRST=0 || ROWS="$ROWS,"
  ROWS="$ROWS\"$t\":$n"
  printf '  %-26s %s\n' "$t" "$n"
done
ROWS="$ROWS}"

echo "[respaldo] ejecutando pg_dump…"
T0=$(date +%s)
pg_dump "$URL" --format=custom --compress=9 --no-owner --no-privileges \
        --file="$DUMP"
T1=$(date +%s)

SIZE=$(wc -c < "$DUMP" | tr -d ' ')
SUM="$(SHA "$DUMP")"
echo "$SUM  $(basename "$DUMP")" > "$BASE.sha256"

PGVER="$(psql "$URL" -XAt -c 'SHOW server_version' 2>/dev/null || echo 'desconocida')"

cat > "$MANIFEST" <<JSON
{
  "created_utc":      "$STAMP",
  "source":           "$DESCRIBE",
  "server_version":   "$PGVER",
  "dump_file":        "$(basename "$DUMP")",
  "dump_bytes":       $SIZE,
  "dump_sha256":      "$SUM",
  "dump_seconds":     $((T1 - T0)),
  "critical_rows":    $ROWS
}
JSON

echo "[respaldo] listo en $((T1 - T0))s · $SIZE bytes · sha256 $SUM"
echo "[respaldo] manifiesto: $MANIFEST"
echo
echo "Un respaldo NO está verificado hasta que se restaura. Para probarlo:"
echo "  tools/verify_backup_restore.sh   # ciclo completo contra PostgreSQL real"
