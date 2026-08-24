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

# La llave con la que se firman las sesiones y el código de un solo uso para
# terminar la instalación desde el teléfono. Se generan aquí y no se escriben
# a mano en ninguna parte. Si ya existen de una instalación anterior se
# conservan: cambiarlos cerraría la sesión abierta en el iPhone sin motivo.
LEER_VAR() {
  gcloud run services describe "$SERVICIO" --region "$REGION" --project "$PROJECT_ID" \
    --format="value(spec.template.spec.containers[0].env.filter(\"name:$1\").extract(value))" \
    2>/dev/null | tr -d '[]' || true
}

SECRETO="$(LEER_VAR AAUS_SESSION_SECRET)"
[[ -n "$SECRETO" ]] || SECRETO="$(openssl rand -hex 32)"

CLIENT_ID="$(LEER_VAR AAUS_OAUTH_CLIENT_ID)"
CODIGO="$(LEER_VAR AAUS_SETUP_CODE)"
# Ocho caracteres sin 0/O/1/I/L: hay que leerlos de la pantalla y escribirlos en
# el móvil. openssl da ocho dígitos hexadecimales exactos y tr los reetiqueta.
# Nada de canalizar /dev/urandom a `head`: head cierra la tubería al octavo byte,
# la fuente infinita del otro lado recibe SIGPIPE, y con `pipefail` eso mata el
# script entero justo antes de publicar nada.
[[ -n "$CODIGO" ]] || CODIGO="$(openssl rand -hex 4 | tr '0123456789abcdef' '23456789ABCDEFGH')"

# La app es pública en Cloud Run y tiene que serlo: para pintar la pantalla de
# entrada hay que poder cargarla antes de saber quién eres. La puerta la pone la
# propia app, con tu cuenta de Google, y también cubre /media/ y la cola.
gcloud run deploy "$SERVICIO" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SA_APP" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 3600 --concurrency 20 --max-instances 4 \
  --set-env-vars "AAUS_PROJECT_ID=${PROJECT_ID},AAUS_LOCATION=${REGION},AAUS_BUCKET=${BUCKET},AAUS_OWNER_EMAIL=${CORREO},AAUS_DRY_RUN=false,AAUS_SESSION_SECRET=${SECRETO},AAUS_SETUP_CODE=${CODIGO}${CLIENT_ID:+,AAUS_OAUTH_CLIENT_ID=${CLIENT_ID}}" \
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
#  7 · Si el candado viejo quedó puesto, quitarlo
# ══════════════════════════════════════════════════════════════════════
# IAP se abandonó por dos motivos: en una cuenta personal de Gmail exige crear
# a mano una marca y un cliente de OAuth en la consola —y hasta entonces el
# servicio contesta "Empty Google Account OAuth client ID(s)/secret(s)" y nada
# más—, y sus APIs de administración las apagó Google en marzo de 2026. Si
# quedó encendido de un intento anterior, se apaga: con él delante, la pantalla
# de entrada no llega ni a cargar.
if gcloud beta run services describe "$SERVICIO" --region "$REGION" \
     --project "$PROJECT_ID" --format='value(metadata.annotations)' 2>/dev/null \
   | grep -q 'iap-enabled.*[Tt]rue'; then
  paso "Quitando el candado viejo"
  gcloud beta run services update "$SERVICIO" --region "$REGION" \
    --project "$PROJECT_ID" --no-iap --quiet >/dev/null 2>&1 || true
  ok "Quitado"
fi

# ══════════════════════════════════════════════════════════════════════
#  8 · Resumen
# ══════════════════════════════════════════════════════════════════════
titulo "Listo"

# La propia app dice si le falta el Client ID. Es la única fuente fiable: el
# dato puede haber entrado por la pantalla del teléfono y no por aquí.
paso "Comprobando la aplicación"
ESTADO="$(curl -s --max-time 90 "${URL}/api/auth/config" 2>/dev/null || true)"
if [[ -z "$ESTADO" ]]; then
  aviso "La app aún está arrancando. Espera un minuto y abre ${URL}"
  FALTA_CLIENTE="si"
elif echo "$ESTADO" | grep -q '"needs_setup":true'; then
  FALTA_CLIENTE="si"
else
  FALTA_CLIENTE="no"
  ok "Responde y ya está instalada"
fi

cat <<RESUMEN

  ${BOLD}Tu app:${RESET}      ${URL}
  ${BOLD}Proyecto:${RESET}    ${PROJECT_ID}
  ${BOLD}Tu acceso:${RESET}   ${CORREO}

RESUMEN

if [[ "$FALTA_CLIENTE" == "si" ]]; then
  cat <<PENDIENTE
  ${YELLOW}${BOLD}FALTA UN PASO.${RESET} Google no deja automatizarlo: hay que crear a mano
  el permiso para que puedas entrar con tu cuenta.

  ${BOLD}Tu código:${RESET}   ${BOLD}${GREEN}${CODIGO}${RESET}   ${DIM}(lo pide el punto 5)${RESET}

  ${BOLD}1.${RESET} Abre:  https://console.cloud.google.com/auth/branding?project=${PROJECT_ID}&${CUENTA}
     Nombre de la app:  Universe Studio
     Correo de asistencia y de contacto:  ${CORREO}
     Público:  ${BOLD}Externo${RESET}   →   Crear

  ${BOLD}2.${RESET} Abre:  https://console.cloud.google.com/auth/audience?project=${PROJECT_ID}&${CUENTA}
     Toca:  ${BOLD}Publicar aplicación${RESET}   →   Confirmar
     ${DIM}Sin esto, Google te bloquea a ti mismo al intentar entrar.${RESET}

  ${BOLD}3.${RESET} Abre:  https://console.cloud.google.com/auth/clients?project=${PROJECT_ID}&${CUENTA}
     Toca:  ${BOLD}Crear cliente${RESET}
     Tipo:  ${BOLD}Aplicación web${RESET}
     En ${BOLD}Orígenes autorizados de JavaScript${RESET} → Añadir URI:
        ${BOLD}${URL}${RESET}
     Toca:  Crear

  ${BOLD}4.${RESET} Copia el ${BOLD}ID de cliente${RESET} que aparece.
     ${DIM}Termina en .apps.googleusercontent.com${RESET}

  ${BOLD}5.${RESET} Abre tu app en ${BOLD}Safari${RESET}:  ${URL}
     Pega el ID, escribe el código ${BOLD}${CODIGO}${RESET}, y toca Terminar instalación.
     ${DIM}Ahí sí se puede pegar. La dirección del punto 3 también sale
     en esa pantalla, con un botón para copiarla.${RESET}

PENDIENTE
else
  # ¿Ya está conectada la publicación automática desde GitHub?
  CONTINUA="$(gcloud builds triggers list --project="$PROJECT_ID" --region="$REGION" \
              --format='value(name)' 2>/dev/null | head -1 || true)"

  cat <<TERMINADO
  ${GREEN}${BOLD}La aplicación ya está en marcha.${RESET}

  ${BOLD}Instálala en el iPhone:${RESET}
     1. Abre ${URL} en ${BOLD}Safari${RESET}
     2. Entra con ${CORREO}
     3. Compartir → Añadir a pantalla de inicio

TERMINADO

  if [[ -z "$CONTINUA" ]]; then
    cat <<CONTINUA_PENDIENTE
  ${BOLD}Queda una cosa: que se actualice sola${RESET}   ${DIM}(recomendado, 1 minuto)${RESET}
     Sin esto, cada cambio te obliga a volver aquí y ejecutar el script otra vez.
     Con esto, se publica sola en unos minutos.

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

  cat <<COMPROBAR
  ${DIM}Para comprobar que quedó bien: entra en Ajustes dentro de la app.
  Debe decir "En producción" en verde, y tu proyecto en vez de "local".${RESET}

COMPROBAR
fi

echo "${BOLD}${GREEN}  Bienvenido a AI Artist Universe Studio.${RESET}"
echo
