#!/usr/bin/env bash
# Provisioning, start to finish, runnable from Cloud Shell in the Google Cloud
# app on iOS. No computer, and no service account key anywhere (PRD 40, 41).
#
#   bash infra/setup.sh my-project-id owner@gmail.com us-central1
#
# Re-running is safe: every step is idempotent.

set -euo pipefail

PROJECT_ID="${1:?Uso: setup.sh PROJECT_ID OWNER_EMAIL [REGION]}"
OWNER_EMAIL="${2:?Falta el email del propietario}"
REGION="${3:-us-central1}"
SERVICE="aaus"
REPO="aaus"
BUCKET="${PROJECT_ID}-aaus"
RUN_SA="aaus-run@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_SA="aaus-tasks@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"

echo "==> APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  texttospeech.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  iap.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com

echo "==> Artifact Registry"
gcloud artifacts repositories create "${REPO}" \
  --repository-format=docker --location="${REGION}" \
  --description="AI Artist Universe Studio" 2>/dev/null || true

echo "==> Firestore (Native mode)"
gcloud firestore databases create --location="${REGION}" 2>/dev/null || true

echo "==> Cloud Storage"
gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" \
  --uniform-bucket-level-access 2>/dev/null || true

echo "==> Runtime service account"
gcloud iam service-accounts create aaus-run \
  --display-name="AI Artist Universe Studio runtime" 2>/dev/null || true

# Exactly the roles the app needs, and nothing else.
for ROLE in \
  roles/aiplatform.user \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/serviceusage.serviceUsageConsumer \
  roles/secretmanager.secretAccessor \
  roles/cloudtasks.enqueuer \
  roles/run.invoker \
  roles/logging.logWriter
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUN_SA}" --role="${ROLE}" --condition=None >/dev/null
done

# Signed URLs are produced through the IAM signBlob API, which is what removes
# the need for a key file.
gcloud iam service-accounts add-iam-policy-binding "${RUN_SA}" \
  --member="serviceAccount:${RUN_SA}" \
  --role=roles/iam.serviceAccountTokenCreator >/dev/null

echo "==> Cloud Tasks queue"
gcloud iam service-accounts create aaus-tasks \
  --display-name="AI Artist Universe Studio queue" 2>/dev/null || true
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${TASKS_SA}" --role=roles/run.invoker --condition=None >/dev/null
# Con IAP delante, la cola tambien tiene que poder atravesarlo: si no, cada
# trabajo encolado recibe un 401 y nunca llega a ejecutarse.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${TASKS_SA}" \
  --role=roles/iap.httpsResourceAccessor --condition=None >/dev/null
gcloud tasks queues create aaus-generation --location="${REGION}" 2>/dev/null || true
# Video generation is slow and expensive: one at a time, and never a silent
# retry storm that would bill twice.
gcloud tasks queues update aaus-generation --location="${REGION}" \
  --max-concurrent-dispatches=4 --max-attempts=1 >/dev/null

echo "==> Budget alert"
BILLING=$(gcloud beta billing projects describe "${PROJECT_ID}" \
  --format='value(billingAccountName)' 2>/dev/null || true)
if [[ -n "${BILLING}" ]]; then
  gcloud beta billing budgets create \
    --billing-account="${BILLING##*/}" \
    --display-name="AAUS ${PROJECT_ID}" \
    --budget-amount=300USD \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 2>/dev/null || \
    echo "    (ya existe o falta permiso; creala a mano en la consola)"
fi

echo "==> Cloud Build permissions"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CB_SA}" --role="${ROLE}" --condition=None >/dev/null
done

echo "==> Owner access"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="user:${OWNER_EMAIL}" --role=roles/run.invoker --condition=None >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="user:${OWNER_EMAIL}" --role=roles/iap.httpsResourceAccessor --condition=None >/dev/null

cat <<EOF

Listo. Queda por hacer, una sola vez y desde el movil:

  1. Conectar el repositorio de GitHub en Cloud Build (Google gestiona la
     conexion con su app de GitHub) y crear un disparador sobre main que use
     cloudbuild.yaml, con estas sustituciones:
         _OWNER_EMAIL=${OWNER_EMAIL}
         _REGION=${REGION}
         _BUCKET=${BUCKET}

  2. Activar Identity Aware Proxy sobre el servicio de Cloud Run '${SERVICE}'
     una vez desplegado. IAP es lo que deja entrar desde Safari sin construir
     login dentro de la app.

  3. Copiar el Client ID de OAuth que IAP crea al activarse y anadirlo al
     disparador como _IAP_AUDIENCE, y volver a lanzar el despliegue. Sin ese
     dato la cola de trabajos recibe un 401 en cada intento y las generaciones
     no arrancan.

  4. Revisar el budget alert en la consola de facturacion. La aplicacion no
     controla el gasto: se mira aqui.

Para un despliegue puntual sin GitHub:
     gcloud run deploy ${SERVICE} --source . --region ${REGION} \\
       --service-account ${RUN_SA} --no-allow-unauthenticated

No se ha creado ninguna clave JSON de cuenta de servicio. Si existe alguna de
un flujo anterior, borrala desde IAM.
EOF
