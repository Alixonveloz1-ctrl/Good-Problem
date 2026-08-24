#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
#  ¿Qué falló?  ·  ./logs.sh
# ═══════════════════════════════════════════════════════════════════════
#
#  Existe para no tener que escribir a mano sesenta caracteres de gcloud
#  desde un teléfono. Se escribe ./logs.sh y ya.
#
# ═══════════════════════════════════════════════════════════════════════

set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; BLUE=$'\033[34m'; RESET=$'\033[0m'

SERVICIO="aaus"
REGION="us-central1"
CUANTOS="${1:-25}"

PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
[[ -n "$PROJECT_ID" && "$PROJECT_ID" != "(unset)" ]] || {
  echo "Cloud Shell no tiene proyecto seleccionado." >&2; exit 1; }

echo
echo "${BOLD}${BLUE}══ Los últimos fallos de tu app ${RESET}"
echo "${DIM}   proyecto ${PROJECT_ID} · las ${CUANTOS} líneas más recientes${RESET}"
echo

# Solo lo que importa: errores y trazas. El resto del registro es ruido de
# arranque y peticiones normales, y en una pantalla de teléfono el ruido
# esconde justo lo que se venía a buscar.
SALIDA="$(gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICIO} AND (severity>=ERROR OR textPayload:\"Traceback\" OR textPayload:\"fallo_no_previsto\")" \
  --project="$PROJECT_ID" --limit="$CUANTOS" --freshness=2h \
  --format='value(timestamp, textPayload)' 2>&1)"

if [[ -z "$SALIDA" ]]; then
  echo "  ${DIM}Sin errores en las últimas 2 horas.${RESET}"
  echo
  echo "  ${DIM}Si acabas de ver un fallo en la pantalla, prueba con más líneas:${RESET}"
  echo "  ${BOLD}./logs.sh 60${RESET}"
else
  echo "$SALIDA" | sed 's/^/  /'
fi

echo
echo "${DIM}Manda una captura de esto a Claude.${RESET}"
echo
