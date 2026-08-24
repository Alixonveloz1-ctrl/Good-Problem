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

# ══════════════════════════════════════════════════════════════════════
#  0 · Traerse la última versión, sin que nadie escriba "git pull"
# ══════════════════════════════════════════════════════════════════════
#
# Escribir a mano en un teléfono es el cuello de botella de todo esto, así que
# el script se actualiza solo. Se hace ANTES de nada y se vuelve a arrancar
# entero: bash lee el archivo a medida que lo ejecuta, y cambiarlo por debajo
# mientras corre lo parte por la mitad de una forma imposible de diagnosticar.
#
# AAUS_YA_ACTUALIZADO corta el bucle: la segunda vuelta ya no vuelve a mirar.
if [[ -z "${AAUS_YA_ACTUALIZADO:-}" ]] && git rev-parse --git-dir >/dev/null 2>&1; then
  echo "${BOLD}${BLUE}══ Buscando cambios ${RESET}"
  RAMA="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  if git fetch --quiet origin "$RAMA" 2>/dev/null; then
    ANTES="$(git rev-parse HEAD)"
    DESPUES="$(git rev-parse "origin/${RAMA}" 2>/dev/null || echo "$ANTES")"
    if [[ "$ANTES" != "$DESPUES" ]]; then
      # No se fuerza nada: un avance directo no puede perder trabajo de nadie,
      # y cualquier otra cosa (cambios a medias, historias que divergen) es
      # decisión de una persona y no de un instalador.
      if MOTIVO="$(git merge --ff-only "origin/${RAMA}" 2>&1)"; then
        echo "  ${GREEN}✓ Actualizado. Arrancando la versión nueva…${RESET}"
        echo
        export AAUS_YA_ACTUALIZADO=1
        exec bash "${BASH_SOURCE[0]}" "$@"
      else
        echo "  ${YELLOW}! No pude actualizar; sigo con lo que hay. Git dijo:${RESET}"
        printf '%s\n' "$MOTIVO" | head -3 | sed 's/^/    /'
      fi
    else
      echo "  ${GREEN}✓ Ya tienes lo último${RESET}"
    fi
  else
    echo "  ${YELLOW}! No pude comprobarlo; sigo con lo que hay.${RESET}"
  fi
fi

# Los ayudantes de Python viven en archivos y no incrustados aquí: mezclar
# Python dentro de bash es donde se cuelan los errores de comillas, y en un
# archivo además se pueden probar por separado.
AYUDA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/infra/setup"

# Si faltan, lo de Firebase se cae mucho mas adelante y con un mensaje que no
# tiene nada que ver ("no pude conseguir la clave del navegador"). Mejor aqui.
for AYUDANTE in primer_app_id limpiar_config elegir_clave nombre_clave_nueva \
                armar_config dominios; do
  [[ -f "${AYUDA}/${AYUDANTE}.py" ]] || {
    echo "Falta ${AYUDA}/${AYUDANTE}.py. Vuelve a ejecutar ./setup.sh" >&2
    exit 1
  }
done

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
  cloudresourcemanager.googleapis.com serviceusage.googleapis.com \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com texttospeech.googleapis.com firestore.googleapis.com \
  storage.googleapis.com cloudtasks.googleapis.com secretmanager.googleapis.com \
  iamcredentials.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  firebase.googleapis.com identitytoolkit.googleapis.com apikeys.googleapis.com \
  --project="$PROJECT_ID" >/dev/null
ok "Servicios encendidos"
detalle "esperando 25 s a que Google propague los permisos…"
sleep 25

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
#  6 · El login, montado solo
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
DOMINIO_LISTO="si"
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
  # Se reintenta. Un 403 justo despues de encender una API casi nunca es
  # "no tienes permiso": es que el permiso todavia no existe. Rendirse al
  # primer intento manda a buscar un problema que no esta.
  CODIGO_FB="000"
  for intento in 1 2 3 4; do
    CODIGO_FB="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
      "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}:addFirebase" \
      -d '{}' 2>/dev/null || echo 000)"
    [[ "$CODIGO_FB" == "200" ]] && break
    # 409 es que ya estaba: no es un fallo.
    [[ "$CODIGO_FB" == "409" ]] && break
    detalle "Google aun no deja (HTTP ${CODIGO_FB}); reintento $intento de 4…"
    sleep 20
  done

  # Lo que respondio Google se guarda ANTES de volver a comprobar: esa
  # comprobacion escribe encima del mismo archivo y se llevaria por delante la
  # unica pista de por que fallo.
  MOTIVO="$(head -6 "$TMP_FB" 2>/dev/null || true)"

  if [[ "$CODIGO_FB" != "200" && "$CODIGO_FB" != "409" ]] && ! firebase_activo; then
    echo
    error "Google no deja activar Firebase desde aquí (HTTP ${CODIGO_FB}):"
    printf '%s\n' "$MOTIVO" | sed 's/^/      /'
    cat <<AMANO

  ${BOLD}Actívalo tú en dos toques y vuelve a ejecutar el script:${RESET}

  ${BOLD}1.${RESET} Abre:  https://console.firebase.google.com/?authuser=${CORREO}
  ${BOLD}2.${RESET} Toca:  ${BOLD}Crear un proyecto${RESET}  →  elige ${BOLD}${PROJECT_ID}${RESET} de la lista
     ${DIM}Es el mismo proyecto, no uno nuevo. Acepta y sigue hasta el final.${RESET}
  ${BOLD}3.${RESET} Vuelve aquí:  ./setup.sh

AMANO
    exit 1
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

# ══════════════════════════════════════════════════════════════════════
#  7 · Publicar la aplicación
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
SECRETO="$SECRETO" CONFIG="$CONFIG" python3 - "$ENV_FILE" <<'PYENV'
import json, os, sys

variables = {
    "AAUS_PROJECT_ID":    os.environ["PROJECT_ID"],
    "AAUS_LOCATION":      os.environ["REGION"],
    "AAUS_BUCKET":        os.environ["BUCKET"],
    "AAUS_OWNER_EMAIL":   os.environ["CORREO"],
    "AAUS_SESSION_SECRET": os.environ["SECRETO"],
    "AAUS_FIREBASE_CONFIG": os.environ["CONFIG"],
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

# --- El botón de "Entrar con Google" ------------------------------------
#
# Se intenta encender por API, y si no se puede se dice. Lo que NO se hace es
# confundir "está apagado" con "no pude preguntarlo": esta API contesta 403 a
# quien no puede administrarla, y leer ese 403 como "apagado" manda a encender
# un interruptor que ya estaba encendido. Ya pasó una vez.
paso "El botón de Entrar con Google"
PROVEEDOR="https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/defaultSupportedIdpConfigs"
GOOGLE_LISTO="no"       # si | no | nose

CODIGO_P="$(curl -sS -o "$TMP_FB" -w '%{http_code}' \
  -H "Authorization: Bearer ${TOKEN}" "${PROVEEDOR}/google.com" 2>/dev/null || echo 000)"

case "$CODIGO_P" in
  200)
    if grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$TMP_FB"; then
      GOOGLE_LISTO="si"; ok "Ya estaba encendido"
    else
      CODIGO_P="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X POST \
        -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
        "${PROVEEDOR}?idpId=google.com" -d '{"enabled":true}' 2>/dev/null || echo 000)"
      if [[ "$CODIGO_P" == "200" ]]; then GOOGLE_LISTO="si"; ok "Encendido"
      else GOOGLE_LISTO="no"; aviso "Hay que encenderlo a mano; te digo dónde al final."; fi
    fi ;;
  404)
    # No existe todavía: se intenta crear.
    CODIGO_P="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
      "${PROVEEDOR}?idpId=google.com" -d '{"enabled":true}' 2>/dev/null || echo 000)"
    if [[ "$CODIGO_P" == "200" ]]; then GOOGLE_LISTO="si"; ok "Encendido"
    else GOOGLE_LISTO="no"; aviso "Hay que encenderlo a mano; te digo dónde al final."; fi ;;
  *)
    GOOGLE_LISTO="nose"
    detalle "Google no deja consultarlo desde aquí (HTTP ${CODIGO_P}); no es un fallo." ;;
esac

# --- Dominios autorizados ----------------------------------------------
#
# Sin esto el login falla con "unauthorized-domain" y el error no dice por qué.
# Cloud Run le da a un servicio más de una dirección válida y basta abrir la que
# no esté en la lista para que falle, así que se autorizan las dos.
paso "La dirección de tu app en la lista de Firebase"
DOMINIO_LISTO="si"
CONFIG_AUTH="https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/config"

CODIGO_LEER="$(curl -sS -o "$TMP_FB" -w '%{http_code}' \
  -H "Authorization: Bearer ${TOKEN}" "$CONFIG_AUTH" 2>/dev/null || echo 000)"

if [[ "$CODIGO_LEER" != "200" ]]; then
  DOMINIO_LISTO="nose"
  detalle "Google no deja consultarlo desde aquí (HTTP ${CODIGO_LEER}); no es un fallo."
else
  NUEVA="$(python3 "${AYUDA}/dominios.py" "$TMP_FB" "${URL#https://}" \
           "${SERVICIO}-${NUMERO}.${REGION}.run.app" 2>/dev/null || echo "")"
  if [[ -z "$NUEVA" ]]; then
    ok "Ya estaba en la lista"
  else
    CODIGO_DOM="$(curl -sS -o "$TMP_FB" -w '%{http_code}' -X PATCH \
      -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
      "${CONFIG_AUTH}?updateMask=authorizedDomains" -d "$NUEVA" 2>/dev/null || echo 000)"
    if [[ "$CODIGO_DOM" == "200" ]]; then ok "Añadida"
    else DOMINIO_LISTO="no"; aviso "No la pude añadir (HTTP ${CODIGO_DOM}); te digo dónde al final."; fi
  fi
fi

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

# Nada de mandar a arreglar lo que no se pudo comprobar. Cuando la respuesta es
# "no sé", la unica prueba que vale es abrir la app: si entra, estaba bien.
if [[ "$GOOGLE_LISTO" == "no" || "$DOMINIO_LISTO" == "no" ]]; then
  echo "  ${YELLOW}${BOLD}FALTA ESTO:${RESET}"
  echo
  if [[ "$GOOGLE_LISTO" == "no" ]]; then
    cat <<PENDIENTE_G
  ${BOLD}·${RESET} Encender el botón de Entrar con Google:
     https://console.firebase.google.com/project/${PROJECT_ID}/authentication/providers?authuser=${CORREO}
     Toca:  ${BOLD}Comenzar${RESET} → ${BOLD}Google${RESET} → ${BOLD}Habilitar${RESET} → ${BOLD}Guardar${RESET}

PENDIENTE_G
  fi
  if [[ "$DOMINIO_LISTO" == "no" ]]; then
    cat <<PENDIENTE_D
  ${BOLD}·${RESET} Añadir tu dirección a la lista de Firebase:
     https://console.firebase.google.com/project/${PROJECT_ID}/authentication/settings?authuser=${CORREO}
     En ${BOLD}Dominios autorizados${RESET} → ${BOLD}Agregar dominio${RESET} → pega:
     ${BOLD}${URL#https://}${RESET}

PENDIENTE_D
  fi
  echo "  Después abre tu app:  ${BOLD}${URL}${RESET}"
  echo
else
  CONTINUA="$(gcloud builds triggers list --project="$PROJECT_ID" --region="$REGION" \
              --format='value(name)' 2>/dev/null | head -1 || true)"

  cat <<TERMINADO
  ${GREEN}${BOLD}Todo listo por aquí.${RESET}

  ${BOLD}Instálala en el iPhone:${RESET}
     1. Abre ${URL} en ${BOLD}Safari${RESET}
     2. Toca ${BOLD}Entrar con Google${RESET} y elige ${CORREO}
     3. Compartir → Añadir a pantalla de inicio

TERMINADO

  if [[ "$GOOGLE_LISTO" == "nose" || "$DOMINIO_LISTO" == "nose" ]]; then
    cat <<NOSE
  ${DIM}Dos ajustes del login no se pueden consultar desde aquí, así que no sé
  decirte si están. Abre la app y entra: si entras, estaban bien. Si te dice
  algo de "dominio no autorizado", añádela aquí:
     https://console.firebase.google.com/project/${PROJECT_ID}/authentication/settings?authuser=${CORREO}
     Dominios autorizados → Agregar dominio → ${URL#https://}${RESET}

NOSE
  fi

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
