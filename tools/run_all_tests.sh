#!/usr/bin/env bash
# Ejecuta TODA la suite de Preferendum en un entorno aislado y reproducible.
#
# Solo lectura respecto de producción: usa una base SQLite temporal y
# secretos de prueba. Nunca toca la base real ni hace red hacia Render.
#
#   tools/run_all_tests.sh            # todo
#   tools/run_all_tests.sh --python   # solo Python
#   tools/run_all_tests.sh --js       # solo JS
#
# Código de salida: 0 si todo pasa; 1 si alguna suite falla.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
VENV="${VENV:-$REPO/.venv-test}"
DB="$(mktemp -d)/prefy_test.db"
ONLY="${1:-}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[setup] creando entorno en $VENV (solo la primera vez)…"
  python3 -m venv "$VENV" || { echo "[setup] FALLÓ python3 -m venv"; exit 1; }
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r requirements-dev.txt || {
    echo "[setup] FALLÓ la instalación de requirements-dev.txt"; exit 1; }
  # web3 puede subir pydantic a 2.x por dependencia transitiva: se re-fija.
  "$VENV/bin/pip" install -q "pydantic==1.10.13"
  echo "[setup] listo."
fi

# PYTHONNOUSERSITE es imprescindible: sin él, el site-packages del usuario
# puede tener prioridad sobre el del entorno y reaparece el pydantic 2.x.
export PYTHONNOUSERSITE=1
export PYTHONPATH="$REPO"
export DATABASE_URL="sqlite:///$DB"
export ADMIN_SECRET="solo-pruebas-locales"
export JWT_SECRET="solo-pruebas-locales"
unset ADMIN_SECRET_CANARY RESEND_API_KEY GMAIL_APP_PASSWORD 2>/dev/null || true

PY_SUITES=(
  test_eligibility test_socioeconomic test_socioeconomic_wiring
  test_socioeconomic_estimator_remediation test_ledger test_ledger_wiring
  test_matching_wiring test_matching_diagnostics test_global_occupation_resolution
  test_i18n_hardening test_i18n_remediation test_jc_demo_account
  test_production_readiness_fixes test_integration_http test_e2e_commercial test_flujos_completos test_campanas_portal test_portales_y_verificacion test_representacion_empresarial
)
JS_SUITES=(
  test_prefy.mjs test_prefy_motion.mjs test_prefy_voice.mjs
  test_prefy_portal_wiring.mjs test_lang_resolver.mjs test_app_native_i18n.mjs
  test_cross_system_language_consistency.mjs test_voter_portal_i18n.mjs
  test_prefy_complete_coverage.mjs
)

RC=0; TOT=0; GREEN=0; FAILED=()

if [ "$ONLY" != "--js" ]; then
  printf '\n──────── SUITES PYTHON ────────\n'
  for t in "${PY_SUITES[@]}"; do
    OUT=$("$VENV/bin/python" -m unittest "$t" 2>&1)
    RAN=$(printf '%s' "$OUT" | grep -oE '^Ran [0-9]+' | grep -oE '[0-9]+' | head -1); RAN=${RAN:-0}
    TOT=$((TOT + RAN))
    if printf '%s' "$OUT" | grep -q '^OK'; then
      GREEN=$((GREEN + RAN)); printf '  %-46s %5s  OK\n' "$t" "$RAN"
    else
      RC=1; FAILED+=("$t")
      DET=$(printf '%s' "$OUT" | grep -E '^(FAILED|ImportError|ModuleNotFoundError)' | head -1 | cut -c1-54)
      printf '  %-46s %5s  %s\n' "$t" "$RAN" "$DET"
    fi
  done
fi

if [ "$ONLY" != "--python" ]; then
  printf '\n──────── SUITES JS ────────\n'
  if command -v node >/dev/null 2>&1; then
    for f in "${JS_SUITES[@]}"; do
      [ -f "$f" ] || continue
      OUT=$(node "$f" 2>&1); JRC=$?
      LAST=$(printf '%s' "$OUT" | tail -1 | cut -c1-54)
      [ $JRC -ne 0 ] && { RC=1; FAILED+=("$f"); }
      printf '  %-46s rc=%s  %s\n' "$f" "$JRC" "$LAST"
    done
  else
    echo "  node no disponible — suites JS omitidas"
  fi
fi

printf '\n──────── RESUMEN ────────\n'
printf '  pruebas Python ejecutadas : %s\n' "$TOT"
printf '  en suites verdes          : %s\n' "$GREEN"
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '  suites con fallo          : %s\n' "${FAILED[*]}"
else
  printf '  suites con fallo          : ninguna\n'
fi
rm -rf "$(dirname "$DB")"
exit $RC
