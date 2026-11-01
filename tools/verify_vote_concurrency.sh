#!/usr/bin/env bash
#
# tools/verify_vote_concurrency.sh — ENSAYO DE CONCURRENCIA DEL VOTO.
#
# Comprueba sobre PostgreSQL REAL que la misma persona no puede emitir dos
# papeletas en la misma consulta, ni con peticiones simultáneas, ni con
# reintentos, ni cuando una transacción falla a medias.
#
# Por qué no basta SQLite: SQLite serializa las escrituras con un candado
# de fichero, así que la carrera que de verdad existe en producción
# —PostgreSQL, varios procesos, varias instancias— no se puede reproducir
# ahí. Una prueba de concurrencia en SQLite daría verde sin probar nada.
#
# Los votantes se emiten desde PROCESOS distintos, no hilos, y arrancan
# todos a la vez contra una barrera común: así la carrera es real y no
# depende del GIL ni del orden en que un bucle lance las peticiones.
#
# No toca ninguna base existente: crea su propia instancia temporal de
# PostgreSQL y la destruye al terminar.
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
PORT="${PREFY_CONC_PORT:-5557}"
PGDIR="$(mktemp -d -t prefy_conc_XXXXXX)"
DBNAME="prefy_conc"
VENV="$ROOT/.venv-test/bin/python"

cleanup() {
  pg_ctl -D "$PGDIR/data" stop -m immediate >/dev/null 2>&1 || true
  rm -rf "$PGDIR"
}
trap cleanup EXIT

[[ -x "$VENV" ]] || { echo "ERROR: falta $VENV (ver docs §1)." >&2; exit 2; }
command -v initdb >/dev/null || { echo "ERROR: falta initdb (PostgreSQL)." >&2; exit 3; }

# Llaves obligatorias: sin ellas bash se come los bytes del «…» como parte
# del nombre de la variable y aborta con "unbound variable".
echo "Levantando PostgreSQL temporal en el puerto ${PORT}…"
initdb -D "$PGDIR/data" -U prefy --auth=trust >/dev/null 2>&1
# max_connections holgado: el ensayo abre una conexión por proceso votante.
pg_ctl -D "$PGDIR/data" \
       -o "-p $PORT -k $PGDIR -c listen_addresses='' -c max_connections=200" \
       -l "$PGDIR/pg.log" start >/dev/null 2>&1
for _ in $(seq 1 40); do
  psql -h "$PGDIR" -p "$PORT" -U prefy -d postgres -XAt -c 'SELECT 1' >/dev/null 2>&1 && break
  sleep 0.25
done
createdb -h "$PGDIR" -p "$PORT" -U prefy "$DBNAME"

export DATABASE_URL="postgresql+psycopg2://prefy@/$DBNAME?host=$PGDIR&port=$PORT"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT"
export JWT_SECRET=conc-local
export ADMIN_SECRET=conc-local
export PGHOST="$PGDIR"
export PGPORT="$PORT"
export PGUSER=prefy
export PGDATABASE="$DBNAME"

"$VENV" -m unittest -v test_vote_concurrency_pg 2>&1 \
  | grep -vE '^\[Scheduler|^\[SECURITY|^\[vote-uniqueness\] [0-9]'
RC=${PIPESTATUS[0]}
exit $RC
