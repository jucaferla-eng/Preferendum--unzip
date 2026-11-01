#!/usr/bin/env bash
#
# tools/verify_backup_restore.sh — ENSAYO DE RECUPERACIÓN ANTE DESASTRE.
#
# Esto no comprueba que los scripts "no den error": ejecuta el ciclo
# completo contra PostgreSQL de verdad y comprueba que los datos vuelven.
#
#   1. Levanta una instancia temporal de PostgreSQL (puerto alto, socket
#      propio, nada que ver con ninguna base real).
#   2. Crea el esquema REAL de Preferendum con las mismas funciones que usa
#      la aplicación al arrancar (Base.metadata.create_all + _migrate),
#      no con un CREATE TABLE escrito a mano que podría divergir.
#   3. Siembra datos ficticios representativos: usuarios, consulta, votos
#      con su código de verificación, campaña, impresiones y asientos del
#      ledger.
#   4. Respalda con tools/backup_db.sh.
#   5. SIMULA EL DESASTRE: borra la base entera.
#   6. Restaura con tools/restore_db.sh, que compara contra el manifiesto.
#   7. Comprueba además la INTEGRIDAD, no solo el recuento: que cada voto
#      restaurado siga siendo único por votante y consulta, que los códigos
#      de verificación sigan resolviendo al voto correcto, y que el ledger
#      siga cuadrando.
#   8. Informa el tiempo de cada fase (RTO medido, no estimado).
#
# No toca ninguna base de datos existente, ni local ni remota: crea la suya
# y la destruye al terminar.
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
PORT="${PREFY_VERIFY_PORT:-5553}"
PGDIR="$(mktemp -d -t prefy_dr_XXXXXX)"
DBNAME="prefy_dr"
WORK="$(mktemp -d -t prefy_dr_backups_XXXXXX)"
VENV="$ROOT/.venv-test/bin/python"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAILED=1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
FAILED=0

cleanup() {
  pg_ctl -D "$PGDIR/data" stop -m immediate >/dev/null 2>&1 || true
  rm -rf "$PGDIR" "$WORK"
}
trap cleanup EXIT

[[ -x "$VENV" ]] || { echo "ERROR: falta $VENV (ver docs/EJECUCION_Y_RECUPERACION.md §1)." >&2; exit 2; }

step "0. Instancia temporal de PostgreSQL"
initdb -D "$PGDIR/data" -U prefy --auth=trust >/dev/null 2>&1
pg_ctl -D "$PGDIR/data" -o "-p $PORT -k $PGDIR -c listen_addresses=''" \
       -l "$PGDIR/pg.log" start >/dev/null 2>&1
for _ in $(seq 1 40); do
  psql -h "$PGDIR" -p "$PORT" -U prefy -d postgres -XAt -c 'SELECT 1' >/dev/null 2>&1 && break
  sleep 0.25
done
createdb -h "$PGDIR" -p "$PORT" -U prefy "$DBNAME"
ok "PostgreSQL $(psql -h "$PGDIR" -p "$PORT" -U prefy -d "$DBNAME" -XAt -c 'SHOW server_version') en el puerto $PORT"

PG_URL="postgresql://prefy@/$DBNAME?host=$PGDIR&port=$PORT"
SA_URL="postgresql+psycopg2://prefy@/$DBNAME?host=$PGDIR&port=$PORT"

step "1. Esquema real y datos ficticios"
T_SEED0=$(date +%s)
PYTHONNOUSERSITE=1 PYTHONPATH="$ROOT" DATABASE_URL="$SA_URL" \
  JWT_SECRET=dr-local ADMIN_SECRET=dr-local \
  PREFY_DR_VOTES="${PREFY_DR_VOTES:-25}" \
  "$VENV" "$ROOT/tools/_dr_seed.py" || { echo "ERROR sembrando." >&2; exit 3; }
T_SEED1=$(date +%s)
ok "esquema + semilla en $((T_SEED1 - T_SEED0))s"

# Huella de integridad ANTES del desastre.
HUELLA_ANTES="$(psql "$PG_URL" -XAt -f "$ROOT/tools/_dr_fingerprint.sql")"

step "2. Respaldo"
T_DUMP0=$(date +%s)
DATABASE_URL="$PG_URL" bash "$ROOT/tools/backup_db.sh" "$WORK" | sed 's/^/  /'
T_DUMP1=$(date +%s)
DUMP="$(ls -t "$WORK"/*.dump | head -1)"
ok "respaldo creado en $((T_DUMP1 - T_DUMP0))s: $(basename "$DUMP")"

step "3. DESASTRE: se destruye la base completa"
psql -h "$PGDIR" -p "$PORT" -U prefy -d postgres -XAt \
     -c "DROP DATABASE $DBNAME WITH (FORCE)" >/dev/null
createdb -h "$PGDIR" -p "$PORT" -U prefy "$DBNAME"
RESTANTES="$(psql "$PG_URL" -XAt -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [[ "$RESTANTES" == "0" ]]; then
  ok "base vacía confirmada (0 tablas): el desastre es real, no simulado a medias"
else
  bad "la base aún tiene $RESTANTES tablas; el ensayo no probaría nada"
fi

step "4. Restauración"
T_REST0=$(date +%s)
RESTORE_URL="$PG_URL" bash "$ROOT/tools/restore_db.sh" "$DUMP" | sed 's/^/  /'
T_REST1=$(date +%s)
ok "restauración y comparación de filas en $((T_REST1 - T_REST0))s"

step "5. Integridad después de la restauración"
HUELLA_DESPUES="$(psql "$PG_URL" -XAt -f "$ROOT/tools/_dr_fingerprint.sql")"
if [[ "$HUELLA_ANTES" == "$HUELLA_DESPUES" ]]; then
  ok "huella de integridad idéntica (votos, códigos, ledger y consultas)"
else
  bad "la huella de integridad CAMBIÓ tras la restauración"
  echo "    antes:   $HUELLA_ANTES"
  echo "    después: $HUELLA_DESPUES"
fi

# El recuento puede coincidir y la integridad estar rota, así que se
# comprueban por separado las propiedades que de verdad importan.
# "Una persona, un voto" se comprueba sobre debate_has_voted, NO sobre
# debate_votes.voter_id: esa columna está siempre en NULL a propósito
# (separación identidad/voto), así que agrupar por ella juntaría todas las
# papeletas en un grupo y el resultado no significaría nada.
DUP="$(psql "$PG_URL" -XAt -c "
  SELECT coalesce(sum(c),0) FROM (
    SELECT count(*) - 1 AS c FROM debate_has_voted
    GROUP BY debate_id, user_id HAVING count(*) > 1
  ) d" 2>/dev/null || echo 'ERR')"
if [[ "$DUP" == "0" ]]; then
  ok "ninguna persona con dos registros de voto en la misma consulta"
else
  bad "aparecieron $DUP registros de voto duplicados tras restaurar"
fi

# Cada código del puente identidad→voto debe seguir resolviendo a una
# papeleta real: es lo que permite a un votante verificar el suyo.
HUERFANOS="$(psql "$PG_URL" -XAt -c "
  SELECT count(*) FROM debate_has_voted h
   WHERE h.verify_code IS NOT NULL AND h.verify_code <> ''
     AND NOT EXISTS (SELECT 1 FROM debate_votes v
                      WHERE v.verify_code = h.verify_code)" 2>/dev/null || echo 'ERR')"
if [[ "$HUERFANOS" == "0" ]]; then
  ok "todos los códigos de verificación resuelven a una papeleta real"
else
  bad "$HUERFANOS códigos de verificación quedaron sin papeleta"
fi

# El contador declarado frente al recuento real de papeletas. En una base
# recién sembrada deben coincidir; si divergen tras restaurar, la
# restauración perdió papeletas sin tocar el contador.
DERIVA="$(psql "$PG_URL" -XAt -c "
  SELECT coalesce(sum(abs(coalesce(d.total_votes,0) -
        (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id))), 0)
    FROM debates d" 2>/dev/null || echo 'ERR')"
if [[ "$DERIVA" == "0" ]]; then
  ok "contador declarado = papeletas reales (deriva 0) tras restaurar"
else
  bad "deriva de $DERIVA entre el contador y las papeletas reales"
fi

step "RESUMEN"
FILAS="$(psql "$PG_URL" -XAt -c 'SELECT count(*) FROM debate_votes')"
TAM="$(wc -c < "$DUMP" | tr -d ' ')"
printf '  papeletas            %s\n' "$FILAS"
printf '  tamaño del respaldo  %s bytes\n' "$TAM"
printf '  semilla              %ss\n' "$((T_SEED1 - T_SEED0))"
printf '  respaldo             %ss\n' "$((T_DUMP1 - T_DUMP0))"
printf '  restauración         %ss   <- RTO medido en esta máquina\n' "$((T_REST1 - T_REST0))"
echo
echo "  El RTO vale para ESTE volumen. Para una cifra defendible ante una"
echo "  due diligence, repetir con el volumen esperado en producción:"
echo "    PREFY_DR_VOTES=50000 tools/verify_backup_restore.sh"
echo
if [[ $FAILED -eq 0 ]]; then
  echo "  ENSAYO DE RECUPERACIÓN SUPERADO: el respaldo se restauró y los datos"
  echo "  volvieron íntegros. Medido, no estimado."
  exit 0
else
  echo "  ENSAYO DE RECUPERACIÓN FALLIDO: ver los puntos marcados arriba." >&2
  exit 1
fi
