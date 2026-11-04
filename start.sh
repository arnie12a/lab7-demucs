
#!/usr/bin/env bash
set -euo pipefail

PROJECT="arka-lab5-2026"
CLUSTER="demucs-cluster"
ZONE="us-central1-a"
NODE_POOL="default-pool"

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "===================================="
echo " Starting Lab 7 Demucs Application"
echo "===================================="

cd "$ROOT"

# ------------------------------------
# 1. Verify required files
# ------------------------------------

echo "[1/8] Checking deployment files..."

for file in \
  rest/rest-deployment.yaml \
  rest/rest-service.yaml \
  rest/rest-ingress.yaml
do
  if [ ! -f "$file" ]; then
    echo "Missing required file: $file"
    exit 1
  fi
done

if [ ! -f ".env" ]; then
  echo "Missing .env file with RustFS credentials"
  exit 1
fi

# ------------------------------------
# 2. Configure Google Cloud
# ------------------------------------

echo "[2/8] Configuring Google Cloud..."

gcloud config set project "$PROJECT"

# ------------------------------------
# 3. Create cluster if missing
# ------------------------------------

echo "[3/8] Checking GKE cluster..."

if ! gcloud container clusters describe "$CLUSTER" \
    --zone "$ZONE" \
    --project "$PROJECT" >/dev/null 2>&1; then

  echo "Creating GKE cluster..."

  gcloud container clusters create "$CLUSTER" \
    --zone "$ZONE" \
    --num-nodes 1 \
    --machine-type e2-standard-4 \
    --disk-size 50 \
    --project "$PROJECT"
fi

gcloud container clusters get-credentials "$CLUSTER" \
  --zone "$ZONE" \
  --project "$PROJECT"

kubectl wait --for=condition=Ready nodes \
  --all --timeout=600s

# ------------------------------------
# 4. Restore Redis
# ------------------------------------

echo "[4/8] Restoring Redis..."

if ! kubectl get deployment redis \
    -n default >/dev/null 2>&1; then

  echo "Redis deployment missing."
  echo "Restore Redis using your original"
  echo "Redis manifest or Helm installation."
  exit 1
fi

kubectl rollout status deployment/redis \
  --timeout=300s

# ------------------------------------
# 5. Restore RustFS
# ------------------------------------

echo "[5/8] Checking RustFS..."

if ! kubectl get namespace rustfs \
    >/dev/null 2>&1; then
  kubectl create namespace rustfs
fi

if ! kubectl get deployment rustfs -n rustfs \
    >/dev/null 2>&1; then

  echo "RustFS deployment missing."
  echo "Restore RustFS using your tested"
  echo "Helm chart and values file."
  exit 1
fi

kubectl rollout status deployment/rustfs \
  -n rustfs --timeout=300s

# ------------------------------------
# 6. Restore worker credentials
# ------------------------------------

echo "[6/8] Restoring credentials..."

set -a
source "$ROOT/.env"
set +a

: "${S3_ACCESS_KEY:?Missing S3_ACCESS_KEY}"
: "${S3_SECRET_KEY:?Missing S3_SECRET_KEY}"

kubectl create secret generic \
  worker-rustfs-credentials \
  --namespace default \
  --from-literal=S3_ACCESS_KEY="$S3_ACCESS_KEY" \
  --from-literal=S3_SECRET_KEY="$S3_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ------------------------------------
# 7. Restore worker and REST
# ------------------------------------

echo "[7/8] Restoring application..."

WORKER_MANIFEST="$ROOT/worker/worker-deployment.yaml"

if [ ! -f "$WORKER_MANIFEST" ]; then
  echo "Worker deployment YAML not found."
  echo "Update WORKER_MANIFEST to its actual path."
  exit 1
fi

kubectl apply -f "$WORKER_MANIFEST"

kubectl apply -f rest/rest-deployment.yaml
kubectl apply -f rest/rest-service.yaml

kubectl rollout status deployment/demucs-worker \
  --timeout=600s

kubectl rollout status deployment/demucs-rest \
  --timeout=300s

# ------------------------------------
# 8. Restore external Ingress
# ------------------------------------

echo "[8/8] Restoring Ingress..."

kubectl apply -f rest/rest-ingress.yaml

echo ""
echo "Current application status:"
kubectl get pods -A
kubectl get svc -A
kubectl get ingress -A

echo ""
echo "Startup configuration applied."
echo "Wait for the external Ingress IP"
echo "and verify HTTP health before testing."

