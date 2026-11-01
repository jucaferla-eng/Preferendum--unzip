#!/usr/bin/env bash
#
# tools/restore_db.sh — restauración de un respaldo de Preferendum.
#
# Restaura un fichero .dump (formato custom) en una base de datos DESTINO y
# vuelve a contar las tablas críticas, comparándolas contra el manifiesto
# del respaldo. La comparación es el objetivo: "pg_restore terminó" no es
# una prueba de recuperación; "las filas críticas coinciden" sí.
#
# PROTECCIÓN DELIBERADA: se niega a escribir sobre una base cuyo nombre
# sugiera producción salvo que se pase --i-understand-this-overwrites.
# Restaurar sobre producción destruye lo que haya allí; no debe poder
# ocurrir por un error de copiar y pegar.
#
# Uso:
#   RESTORE_URL=postgresql://... tools/restore_db.sh <fichero.dump> [--i-understand-this-overwrites]
#
set -euo pipefail

DUMP="${1:-}"
FORCE="${2:-}"
URL="${RESTORE_URL:-}"

if [[ -z "$DUMP" || -z "$URL" ]]; then
  echo "Uso: RESTORE_URL=postgresql://... $0 <fichero.dump> [--i-understand-this-overwrites]" >&2
  exit 2
fi
[[ -f "$DUMP" ]] || { echo "ERROR: no existe $DUMP" >&2; exit 2; }

URL="${URL/postgresql+psycopg2:\/\//postgresql://}"
URL="${URL/postgres:\/\//postgresql://}"
[[ "$URL" == postgresql://* ]] || { echo "ERROR: RESTORE_URL no es PostgreSQL." >&2; exit 2; }

command -v pg_restore >/dev/null || { echo "ERROR: falta pg_restore." >&2; exit 3; }
command -v psql       >/dev/null || { echo "ERROR: falta psql." >&2; exit 3; }

DBNAME="$(psql "$URL" -XAt -c 'SELECT current_database()')"

# ── Salvaguarda contra restaurar encima de producción ─────────────────────
if [[ "$DBNAME" =~ (prod|production|preferendum_live|live) && "$FORCE" != "--i-understand-this-overwrites" ]]; then
  echo "ABORTADO: la base destino se llama '$DBNAME', que parece producción." >&2
  echo "          Restaurar DESTRUIRÍA los datos actuales." >&2
  echo "          Si es realmente lo que quieres, repite con" >&2
  echo "          --i-understand-this-overwrites" >&2
  exit 4
fi

# Verificar la suma de comprobación si el respaldo la trae: un dump
# corrupto debe detectarse ANTES de borrar nada del destino.
SUMFILE="${DUMP%.dump}.sha256"
if [[ -f "$SUMFILE" ]]; then
  if command -v sha256sum >/dev/null; then
    ACTUAL="$(sha256sum "$DUMP" | awk '{print $1}')"
  else
    ACTUAL="$(shasum -a 256 "$DUMP" | awk '{print $1}')"
  fi
  EXPECTED="$(awk '{print $1}' "$SUMFILE")"
  if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    echo "ABORTADO: la suma de comprobación no coincide. El respaldo está corrupto." >&2
    exit 5
  fi
  echo "[restauración] suma de comprobación correcta"
fi

echo "[restauración] destino: $DBNAME"
echo "[restauración] ejecutando pg_restore…"
T0=$(date +%s)
# --clean --if-exists deja el destino en el estado del respaldo en vez de
# fusionar dos esquemas, que es lo que produce "restauraciones" que parecen
# funcionar y tienen filas de dos épocas distintas.
# El código de salida se captura: pg_restore avisa de objetos ya existentes
# con rc=1 sin que la restauración haya fallado.
set +e
pg_restore --dbname="$URL" --clean --if-exists --no-owner --no-privileges \
           --exit-on-error "$DUMP"
RC=$?
set -e
T1=$(date +%s)
if [[ $RC -ne 0 ]]; then
  echo "ERROR: pg_restore devolvió $RC. La restauración NO es válida." >&2
  exit 6
fi
echo "[restauración] pg_restore terminó en $((T1 - T0))s"

# ── Comparación contra el manifiesto ─────────────────────────────────────
MANIFEST="${DUMP%.dump}.manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "AVISO: no hay manifiesto junto al respaldo; no se puede verificar el"
  echo "       contenido. La restauración queda SIN VERIFICAR."
  exit 0
fi

echo "[restauración] comparando filas críticas contra el manifiesto…"
FAIL=0
# Se leen los pares "tabla": n del manifiesto sin depender de jq.
while IFS='=' read -r t esperado; do
  [[ -z "$t" ]] && continue
  actual="$(psql "$URL" -XAt -c "SELECT count(*) FROM $t" 2>/dev/null || echo 'null')"
  [[ -z "$actual" ]] && actual='null'
  if [[ "$actual" == "$esperado" ]]; then
    printf '  OK    %-26s %s\n' "$t" "$actual"
  else
    printf '  FALLO %-26s esperado=%s restaurado=%s\n' "$t" "$esperado" "$actual"
    FAIL=1
  fi
done < <(sed -n 's/.*"critical_rows":[[:space:]]*{\(.*\)}.*/\1/p' "$MANIFEST" \
         | tr ',' '\n' | sed 's/"//g' | sed 's/:/=/' | sed 's/^[[:space:]]*//')

if [[ $FAIL -ne 0 ]]; then
  echo
  echo "RESTAURACIÓN NO VÁLIDA: el contenido no coincide con el respaldo." >&2
  exit 7
fi

echo
echo "RESTAURACIÓN VERIFICADA: todas las tablas críticas coinciden con el respaldo."
