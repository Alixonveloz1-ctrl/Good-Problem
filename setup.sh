#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
#  AI ARTIST UNIVERSE STUDIO · instalación completa en Google Cloud
# ═══════════════════════════════════════════════════════════════════════
#
#  Este script hace TODO el montaje por ti. Tú no escribes ninguna clave,
#  ningún nombre largo, ninguna URL.
#
#  CÓMO SE USA
#    Dentro de Cloud Shell (la terminal negra de Google Cloud), desde la
#    carpeta del proyecto:
#
#       ./setup.sh
#
#  SE PUEDE EJECUTAR LAS VECES QUE HAGA FALTA
#    No duplica nada y no pierde nada de lo ya instalado.
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'

titulo()  { echo; echo "${BOLD}${BLUE}══ $* ${RESET}"; }
paso()    { echo; echo "${BOLD}▸ $*${RESET}"; }
detalle() { echo "  ${DIM}$*${RESET}"; }
ok()      { echo "  ${GREEN}✓ $*${RESET}"; }
aviso()   { echo "  ${YELLOW}! $*${RESET}"; }
error()   { echo "  ${RED}✗ $*${RESET}" >&2; }

morir() {
  echo; error "$1"; echo
  echo "  Manda una captura de esta pantalla a Claude. No hace falta que copies nada."
  exit 1
}

# Con `set -e` un fallo corta el script sin imprimir nada y parece que
# terminó bien. Desde un celular eso es imposible de diagnosticar.
trap 'CODIGO=$?; echo; error "Se detuvo solo en la línea ${LINENO} (código ${CODIGO})."; echo; echo "  Manda una captura de esta pantalla a Claude."; exit "$CODIGO"' ERR

SERVICIO="aaus"
REGION="us-central1"
COLA="aaus-generation"

# Los ayudantes de Python viven en archivos y no incrustados aquí: mezclar
# Python dentro de bash es donde se cuelan los errores de comillas, y en un
# archivo además se pueden probar por separado.
AYUDA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/infra/setup"

# ══════════════════════════════════════════════════════════════════════
#  1 · Quién eres y dónde vamos a montar esto
# ══════════════════════════════════════════════════════════════════════
titulo "Comprobando dónde estamos"

command -v gcloud >/dev/null || morir "Esto hay que ejecutarlo dentro de Cloud Shell."

PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
CORREO="$(gcloud config get-value account 2>/dev/null || true)"

[[ -n "$PROJECT_ID" && "$PROJECT_ID" != "(unset)" ]] || morir \
  "Cloud Shell no tiene ningún proyecto seleccionado. Ábrelo desde el proyecto donde quieras instalar."
[[ -n "$CORREO" && "$CORREO" != "(unset)" ]] || morir "No hay ninguna cuenta de Google activa."

NUMERO="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
# Con varias cuentas de Google en el navegador, un enlace sin esto abre la
# cuenta equivocada y no encuentra el proyecto.
CUENTA="authuser=${CORREO}"
BUCKET="${PROJECT_ID}-aaus"
SA_APP="aaus-run@${PROJECT_ID}.iam.gserviceaccount.com"
SA_COLA="aaus-tasks@${PROJECT_ID}.iam.gserviceaccount.com"
SA_BUILD="${NUMERO}-compute@developer.gserviceaccount.com"

echo
echo "  ${BOLD}Proyecto:${RESET}  ${PROJECT_ID}"
echo "  ${BOLD}Tu cuenta:${RESET} ${CORREO}"
echo "  ${BOLD}Región:${RESET}    ${REGION}"
echo
read -r -p "  ¿Es correcto? [S/n] " RESPUESTA
[[ -z "$RESPUESTA" || "$RESPUESTA" =~ ^[SsYy]$ ]] || morir \
  "Cambia el proyecto con: gcloud config set project OTRO-ID"

if ! gcloud beta billing projects describe "$PROJECT_ID" \
     --format='value(billingEnabled)' 2>/dev/null | grep -q True; then
  echo
  aviso "Este proyecto no tiene facturación activada."
  detalle "Sin tarjeta, Google no deja usar Veo ni Lyria (aunque tengas los \$300 de crédito)."
  detalle "Actívala aquí y vuelve a ejecutar el script:"
  echo "  https://console.cloud.google.com/billing/linkedaccount?project=${PROJECT_ID}&${CUENTA}"
  exit 1
fi
ok "Facturación activada"

# ══════════════════════════════════════════════════════════════════════
#  2 · Encender los servicios de Google que hacen falta
# ══════════════════════════════════════════════════════════════════════
titulo "Encendiendo servicios"
paso "Esto tarda un par de minutos la primera vez"

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com texttospeech.googleapis.com firestore.googleapis.com \
  storage.googleapis.com cloudtasks.googleapis.com secretmanager.googleapis.com \
  iamcredentials.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  firebase.googleapis.com identitytoolkit.googleapis.com apikeys.googleapis.com \
  --project="$PROJECT_ID" >/dev/null
ok "Servicios encendidos"

# ══════════════════════════════════════════════════════════════════════
#  3 · Dónde se guardan los datos y los vídeos
# ══════════════════════════════════════════════════════════════════════
titulo "Almacenamiento"

paso "Base de datos"
if gcloud firestore databases describe --project="$PROJECT_ID" >/dev/null 2>&1; then
  ok "Ya existía"
else
  gcloud firestore databases create --location="$REGION" --project="$PROJECT_ID" >/dev/null
  ok "Creada"
fi

paso "Sitio para los vídeos, imágenes y canciones"
if gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  ok "Ya existía: gs://${BUCKET}"
else
  gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
    --uniform-bucket-level-access --project="$PROJECT_ID" >/dev/null
  ok "Creado: gs://${BUCKET}"
fi

# ══════════════════════════════════════════════════════════════════════
#  4 · Identidades y permisos
# ══════════════════════════════════════════════════════════════════════
titulo "Permisos"
detalle "Ninguna clave se descarga ni se guarda: son identidades de Google."

crear_cuenta() {
  local nombre="$1" titulo_sa="$2"
  if gcloud iam service-accounts describe "${nombre}@${PROJECT_ID}.iam.gserviceaccount.com" \
       --project="$PROJECT_ID" >/dev/null 2>&1; then
    ok "${titulo_sa}: ya existía"
  else
    gcloud iam service-accounts create "$nombre" --display-name="$titulo_sa" \
      --project="$PROJECT_ID" >/dev/null
    ok "${titulo_sa}: creada"
  fi
}

dar_rol() {
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="$1" --role="$2" --condition=None >/dev/null 2>&1 || true
}

paso "La identidad con la que corre la aplicación"
crear_cuenta "aaus-run" "AI Artist Universe Studio"
for ROL in roles/aiplatform.user roles/datastore.user roles/storage.objectAdmin \
           roles/serviceusage.serviceUsageConsumer roles/secretmanager.secretAccessor \
           roles/cloudtasks.enqueuer roles/run.invoker roles/logging.logWriter; do
  dar_rol "serviceAccount:${SA_APP}" "$ROL"
done
# Para firmar los enlaces de descarga sin ningún archivo de clave.
gcloud iam service-accounts add-iam-policy-binding "$SA_APP" \
  --member="serviceAccount:${SA_APP}" \
  --role=roles/iam.serviceAccountTokenCreator --project="$PROJECT_ID" >/dev/null 2>&1 || true
ok "Permisos de la aplicación"

paso "La identidad de la cola de trabajos"
detalle "Es lo que hace que un vídeo siga generándose aunque cierres Safari."
crear_cuenta "aaus-tasks" "Cola de generación"
dar_rol "serviceAccount:${SA_COLA}" "roles/run.invoker"
ok "Permisos de la cola"

paso "Permisos para publicar actualizaciones"
for ROL in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser \
           roles/cloudbuild.builds.builder; do
  dar_rol "serviceAccount:${SA_BUILD}" "$ROL"
done
ok "Listo"

paso "Tu acceso"
detalle "Quién entra en la app lo decide la propia app, no la red: tiene que"
detalle "poder dibujar la pantalla de entrada antes de saber quién eres."
dar_rol "user:${CORREO}" "roles/run.admin"
ok "${CORREO}"

# ══════════════════════════════════════════════════════════════════════
#  5 · La cola de trabajos
# ══════════════════════════════════════════════════════════════════════
titulo "Cola de generación"
if gcloud tasks queues describe "$COLA" --location="$REGION" --project="$PROJECT_ID" \
     >/dev/null 2>&1; then
  ok "Ya existía"
else
  gcloud tasks queues create "$COLA" --location="$REGION" --project="$PROJECT_ID" >/dev/null
  ok "Creada"
fi
# Sin reintentos automáticos: un vídeo que falla no se vuelve a cobrar solo.
gcloud tasks queues update "$COLA" --location="$REGION" --project="$PROJECT_ID" \
  --max-concurrent-dispatches=4 --max-attempts=1 >/dev/null
ok "Configurada: 4 a la vez, sin reintentos automáticos"

# ══════════════════════════════════════════════════════════════════════
#  6 · Publicar la aplicación
# ══════════════════════════════════════════════════════════════════════
titulo "Publicando la aplicación"
paso "Esto tarda entre 5 y 10 minutos. No cierres Cloud Shell."
detalle "Construye la app y la sube. La primera vez es la más lenta."

# La llave con la que se firman las sesiones. Se genera aquí y no se escribe a
# mano en ninguna parte. Si ya existe de una instalación anterior se conserva:
# cambiarla cerraría la sesión abierta en el iPhone sin motivo.
LEER_VAR() {
  gcloud run services describe "$SERVICIO" --region "$REGION" --project "$PROJECT_ID" \
    --format="value(spec.template.spec.containers[0].env.filter(\"name:$1\").extract(value))" \
    2>/dev/null | tr -d '[]' || true
}

SECRETO="$(LEER_VAR AAUS_SESSION_SECRET)"
[[ -n "$SECRETO" ]] || SECRETO="$(openssl rand -hex 32)"

# La app es pública en Cloud Run y tiene que serlo: para pintar la pantalla de
# entrada hay que poder cargarla antes de saber quién eres. La puerta la pone la
# propia app, con tu cuenta de Google, y también cubre /media/ y la cola.
# Las variables van en un archivo y no con --set-env-vars: gcloud solo respeta
# el último --set-env-vars que se le pase, y el JSON de Firebase lleva comas y
# comillas que rompen el formato de la línea de comandos.
ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT

PROJECT_ID="$PROJECT_ID" REGION="$REGION" BUCKET="$BUCKET" CORREO="$CORREO" \
SECRETO="$SECRETO" python3 - "$ENV_FILE" <<'PYENV'
import json, os, sys

variables = {
    "AAUS_PROJECT_ID":    os.environ["PROJECT_ID"],
    "AAUS_LOCATION":      os.environ["REGION"],
    "AAUS_BUCKET":        os.environ["BUCKET"],
    "AAUS_OWNER_EMAIL":   os.environ["CORREO"],
    "AAUS_SESSION_SECRET": os.environ["SECRETO"],
    "AAUS_DRY_RUN":       "false",
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    for clave, valor in variables.items():
        f.write("%s: %s\n" % (clave, json.dumps(valor)))
PYENV

gcloud run deploy "$SERVICIO" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SA_APP" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 3600 --concurrency 20 --max-instances 4 \
  --env-vars-file "$ENV_FILE" \
  --quiet >/dev/null

URL="$(gcloud run services describe "$SERVICIO" --region "$REGION" \
       --project "$PROJECT_ID" --format='value(status.url)')"
[[ -n "$URL" ]] || morir "El despliegue terminó pero no devolvió ninguna dirección."
ok "Publicada en ${URL}"

paso "Conectando la cola con la aplicación"
detalle "La cola necesita la dirección, que no existía hasta ahora."
gcloud run services update "$SERVICIO" --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars "AAUS_TASKS_QUEUE=${COLA},AAUS_TASKS_TARGET_URL=${URL},AAUS_TASKS_SERVICE_ACCOUNT=${SA_COLA}" \
  --quiet >/dev/null
ok "Conectada"

# ══════════════════════════════════════════════════════════════════════
#  7 · El login, montado solo
# ══════════════════════════════════════════════════════════════════════
titulo "Entrar con tu cuenta de Google"
detalle "Firebase se monta encima del mismo proyecto. No es otra cuenta."

# Si quedó IAP encendido de un intento anterior, se apaga: con él delante, la
# pantalla de entrada no llega ni a cargar.
if gcloud beta run services describe "$SERVICIO" --region "$REGION" \
     --project "$PROJECT_ID" --format='value(metadata.annotations)' 2>/dev/null \
   | grep -q 'iap-enabled.*[Tt]rue'; then
  gcloud beta run services update "$SERVICIO" --region "$REGION" \
    --project "$PROJECT_ID" --no-iap --quiet >/dev/null 2>&1 || true
  ok "Quitado el candado viejo"
fi

TOKEN="$(gcloud auth print-access-token)"
TMP_FB="$(mktemp)"

firebase_activo() {
  local codigo
  codigo="$(curl -sS -o "$TMP_FB" -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}" 2>/dev/null || echo 000)"
  [[ "$codigo" == "200" ]]
}

paso "Activando Firebase sobre el proyecto"
if firebase_activo; then
  ok "Ya estaba activo"
else
  CODIGO_FB="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}:addFirebase" \
    -d '{}' 2>/dev/null || echo 000)"
  if [[ "$CODIGO_FB" != "200" ]]; then
    error "Google rechazó activar Firebase (HTTP ${CODIGO_FB}). Respondió:"
    head -6 "$TMP_FB" | sed 's/^/      /'
    morir "Sin Firebase no hay forma de entrar en la app."
  fi
  # Se espera a que la activación sea CIERTA. Dar el visto bueno sin comprobar
  # deja todo lo de después chocando contra un 404 que no dice nada.
  detalle "esperando a que Google lo confirme…"
  ACTIVO="no"
  for intento in $(seq 1 18); do
    sleep 10
    if firebase_activo; then ACTIVO="si"; break; fi
    (( intento % 6 == 0 )) && detalle "sigue en ello… ($((intento / 6)) min)"
  done
  [[ "$ACTIVO" == "si" ]] || morir "Firebase no terminó de activarse. Vuelve a ejecutar el script."
  ok "Activado"
fi

# --- La configuración que el navegador necesita -------------------------
#
# Son tres datos y ninguno es secreto: están pensados para ir escritos en la
# página, igual que en cualquier sitio con "Entrar con Google". Quien decide
# quién entra es el correo del dueño y la firma de la cookie.
#
# Primero por la aplicación web de Firebase. Si Google no la termina a tiempo
# —se queda colgada a menudo— hay un segundo camino que no depende de ella.
paso "Consiguiendo la configuración del login"

leer_app_id() {
  curl -sS -H "Authorization: Bearer ${TOKEN}" \
    "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}/webApps" 2>/dev/null \
    | python3 "${AYUDA}/primer_app_id.py" 2>/dev/null || echo ""
}

APP_ID="$(leer_app_id)"
if [[ -z "$APP_ID" ]]; then
  detalle "creando la aplicación web…"
  curl -sS -X POST -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}/webApps" \
    -d '{"displayName":"Universe Studio"}' >/dev/null 2>&1 || true
  for intento in 1 2 3 4; do
    sleep 15
    APP_ID="$(leer_app_id)"
    [[ -n "$APP_ID" ]] && break
    detalle "aún creándose… ($intento de 4; si no llega, hay otro camino)"
  done
fi

CONFIG=""
if [[ -n "$APP_ID" ]]; then
  CONFIG="$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
    "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}/webApps/${APP_ID}/config" \
    2>/dev/null | python3 "${AYUDA}/limpiar_config.py" 2>/dev/null || echo "")"
fi

if [[ -z "$CONFIG" ]]; then
  # El otro camino. El login sólo necesita apiKey, authDomain y projectId; el
  # appId lo piden Analytics e Installations, que esta app no lleva. Esperar
  # por la aplicación web sería esperar por un dato que no hace falta.
  detalle "la aplicación web no estuvo lista; armándola por el otro camino…"
  NOMBRE_CLAVE="$(gcloud services api-keys list --project="$PROJECT_ID" --format=json 2>/dev/null \
    | python3 "${AYUDA}/elegir_clave.py" 2>/dev/null || echo "")"

  if [[ -z "$NOMBRE_CLAVE" ]]; then
    NOMBRE_CLAVE="$(gcloud services api-keys create --display-name="Universe Studio web" \
      --project="$PROJECT_ID" --format=json 2>/dev/null \
      | python3 "${AYUDA}/nombre_clave_nueva.py" 2>/dev/null || echo "")"
  fi

  CLAVE=""
  [[ -n "$NOMBRE_CLAVE" ]] && CLAVE="$(gcloud services api-keys get-key-string "$NOMBRE_CLAVE" \
    --project="$PROJECT_ID" --format='value(keyString)' 2>/dev/null || echo "")"

  [[ -n "$CLAVE" ]] || morir "No pude conseguir la clave del navegador. Manda esta captura."

  CONFIG="$(python3 "${AYUDA}/armar_config.py" "$CLAVE" "$PROJECT_ID")"
fi
ok "Conseguida (no tuviste que copiar nada)"

# --- Dominios autorizados ----------------------------------------------
#
# Sin esto el login falla y el error de Google no dice por qué. Cloud Run le da
# a un servicio más de una dirección válida y basta abrir la que no esté en la
# lista para que falle, así que se autorizan las dos.
paso "Autorizando la dirección de tu app"
CONFIG_AUTH="https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/config"

curl -sS -o "$TMP_FB" -H "Authorization: Bearer ${TOKEN}" "$CONFIG_AUTH" >/dev/null 2>&1 || true
NUEVA="$(python3 "${AYUDA}/dominios.py" "$TMP_FB" "${URL#https://}" \
         "${SERVICIO}-${NUMERO}.${REGION}.run.app" 2>/dev/null || echo "")"

if [[ -z "$NUEVA" ]]; then
  ok "Ya estaba autorizada"
else
  CODIGO_DOM="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X PATCH \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "${CONFIG_AUTH}?updateMask=authorizedDomains" -d "$NUEVA" 2>/dev/null || echo 000)"
  if [[ "$CODIGO_DOM" == "200" ]]; then
    ok "Autorizada"
  else
    aviso "Google no dejó autorizarla sola (HTTP ${CODIGO_DOM}). Te lo digo al final."
  fi
fi

# --- El botón de "Entrar con Google" ------------------------------------
#
# Se intenta encender por API. Google no documenta que se pueda sin dar un
# cliente de OAuth propio, así que puede que no funcione; si no funciona es un
# solo interruptor en la consola y se dice al final. Intentarlo no cuesta nada
# y si sale, no queda ni un paso a mano.
paso "Encendiendo el botón de Entrar con Google"
PROVEEDOR="https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/defaultSupportedIdpConfigs"
GOOGLE_LISTO="no"

CODIGO_P="$(curl -sS -o "$TMP_FB" -w '%{http_code}' \
  -H "Authorization: Bearer ${TOKEN}" "${PROVEEDOR}/google.com" 2>/dev/null || echo 000)"
if [[ "$CODIGO_P" == "200" ]] && grep -q '"enabled": *true' "$TMP_FB"; then
  GOOGLE_LISTO="si"
  ok "Ya estaba encendido"
else
  CODIGO_P="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "${PROVEEDOR}?idpId=google.com" -d '{"enabled":true}' 2>/dev/null || echo 000)"
  if [[ "$CODIGO_P" == "200" ]]; then
    GOOGLE_LISTO="si"
    ok "Encendido"
  else
    aviso "Este hay que encenderlo a mano. Es un interruptor; te digo dónde al final."
  fi
fi

# --- Dejársela a la app -------------------------------------------------
paso "Guardando la configuración en la app"
# El separador se cambia a @ porque el JSON lleva comas, y una coma dentro del
# valor haría que gcloud lo partiera en variables inventadas.
gcloud run services update "$SERVICIO" --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars "^@^AAUS_FIREBASE_CONFIG=${CONFIG}" --quiet >/dev/null
ok "Guardada"

# ══════════════════════════════════════════════════════════════════════
#  8 · Resumen
# ══════════════════════════════════════════════════════════════════════
titulo "Listo"

paso "Comprobando que la app sirve su configuración"
SIRVIENDO="no"
for intento in 1 2 3 4 5 6; do
  sleep 8
  if curl -sS --max-time 20 "${URL}/api/auth/config" 2>/dev/null | grep -q '"apiKey"'; then
    SIRVIENDO="si"; break
  fi
  detalle "todavía arrancando la versión nueva… ($intento de 6)"
done
[[ "$SIRVIENDO" == "si" ]] && ok "La sirve" || aviso "Aún no responde. Espera un minuto y abre la app."

cat <<RESUMEN

  ${BOLD}Tu app:${RESET}      ${URL}
  ${BOLD}Proyecto:${RESET}    ${PROJECT_ID}
  ${BOLD}Tu acceso:${RESET}   ${CORREO}

RESUMEN

if [[ "$GOOGLE_LISTO" == "no" ]]; then
  cat <<PENDIENTE
  ${YELLOW}${BOLD}FALTA UN INTERRUPTOR.${RESET} Es lo único que Google no deja encender solo.

  ${BOLD}1.${RESET} Abre:  https://console.firebase.google.com/project/${PROJECT_ID}/authentication/providers?authuser=${CORREO}
  ${BOLD}2.${RESET} Toca:  ${BOLD}Comenzar${RESET}  →  ${BOLD}Google${RESET}  →  ${BOLD}Habilitar${RESET}  →  ${BOLD}Guardar${RESET}
  ${BOLD}3.${RESET} Abre tu app y entra:  ${URL}

  ${DIM}No tienes que copiar ni escribir nada. Solo tocar.${RESET}

PENDIENTE
else
  CONTINUA="$(gcloud builds triggers list --project="$PROJECT_ID" --region="$REGION" \
              --format='value(name)' 2>/dev/null | head -1 || true)"

  cat <<TERMINADO
  ${GREEN}${BOLD}Ya está todo. No queda ningún paso.${RESET}

  ${BOLD}Instálala en el iPhone:${RESET}
     1. Abre ${URL} en ${BOLD}Safari${RESET}
     2. Toca ${BOLD}Entrar con Google${RESET} y elige ${CORREO}
     3. Compartir → Añadir a pantalla de inicio

TERMINADO

  if [[ -z "$CONTINUA" ]]; then
    cat <<CONTINUA_PENDIENTE
  ${BOLD}Queda una cosa: que se actualice sola${RESET}   ${DIM}(recomendado, 1 minuto)${RESET}
     Sin esto, cada cambio te obliga a volver aquí y ejecutar el script otra vez.

     Abre:  https://console.cloud.google.com/run/detail/${REGION}/${SERVICIO}/revisions?project=${PROJECT_ID}&${CUENTA}
     Toca:  Configurar implementación continua
            →  Conectar tu cuenta de GitHub (te pedirá autorizar)
            →  Repositorio: Good-Problem   ·   Rama: main
            →  Tipo de compilación: Dockerfile
            →  Guardar

CONTINUA_PENDIENTE
  else
    ok "La publicación automática desde GitHub ya está conectada"
    echo
  fi
fi

echo "${BOLD}${GREEN}  Bienvenido a AI Artist Universe Studio.${RESET}"
echo
