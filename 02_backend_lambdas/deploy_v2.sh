#!/usr/bin/env bash
#
# YouFeelings v2 — parallel deployment
# ====================================
# Creates a SECOND, independent pipeline alongside the existing one.
# Ashab's functions, prefixes and triggers are never touched.
#
#   existing (untouched)        new (yours)
#   --------------------        -----------
#   Uploads/                    uploads-v2/
#   parsed/                     parsed-v2/
#   recommendations/            recommendations-v2/
#   models/                     models-v2/
#   takeout-parser              yf-v2-takeout-parser
#   youfeelings-fusion-...      yf-v2-fusion-recommender
#   upload-url-lambda           yf-v2-upload-url
#   recommendation-lambda       yf-v2-get-recommendations
#
# Separate prefixes are REQUIRED: S3 rejects overlapping event notifications
# for the same event type + prefix + suffix, so two parsers cannot both watch
# Uploads/*.zip.
#
# Run in CloudShell (needs your console identity, not the SageMaker role).
# Upload the 4 .py files into ~/yf-v2/ first.

set -euo pipefail

BUCKET="netfeeling"
REGION="us-east-1"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
SRC="${HOME}/yf-v2"
BUILD="${HOME}/yf-v2-build"

echo "Account: $ACCOUNT   Bucket: $BUCKET   Region: $REGION"
echo

# ---------------------------------------------------------------------------
# Reuse the IAM roles the existing functions already use (read-only lookup --
# this does not modify them). If that fails, set ROLE_* manually below.
# ---------------------------------------------------------------------------
get_role () {
  aws lambda get-function-configuration --function-name "$1" \
      --query 'Role' --output text 2>/dev/null || true
}

ROLE_PARSER=$(get_role takeout-parser)
ROLE_FUSION=$(get_role youfeelings-fusion-recommender)
ROLE_UPLOAD=$(get_role upload-url-lambda)
ROLE_GET=$(get_role recommendation-lambda)

for v in ROLE_PARSER ROLE_FUSION ROLE_UPLOAD ROLE_GET; do
  if [ -z "${!v}" ] || [ "${!v}" = "None" ]; then
    echo "ERROR: could not read $v from the existing function."
    echo "Set it manually at the top of this script and re-run."
    exit 1
  fi
  echo "$v = ${!v}"
done
echo

# The BeautifulSoup layer the existing parser uses (shared, read-only).
LAYER_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:layer:beautifulsoup-layer:1"

# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------
rm -rf "$BUILD" && mkdir -p "$BUILD"
cd "$BUILD"

# parser needs Ashab's parser.py alongside it -- pull it from the deployed
# function so we do not have to maintain a second copy.
echo "Fetching parser.py from the existing takeout-parser ..."
url=$(aws lambda get-function --function-name takeout-parser \
      --query 'Code.Location' --output text)
curl -s -o existing-parser.zip "$url"
mkdir -p parser_pkg && cd parser_pkg
unzip -oq ../existing-parser.zip
rm -f lambda_function.py                       # replaced by ours
cp "$SRC/lambda_takeout_parser.py" lambda_function.py
zip -qr ../yf-v2-takeout-parser.zip .
cd "$BUILD"
echo "  packaged yf-v2-takeout-parser.zip ($(du -h yf-v2-takeout-parser.zip | cut -f1))"

for pair in "lambda_fusion_recommender.py:yf-v2-fusion-recommender" \
            "lambda_upload_url.py:yf-v2-upload-url" \
            "lambda_get_recommendations.py:yf-v2-get-recommendations"; do
  src="${pair%%:*}"; name="${pair##*:}"
  rm -rf tmp && mkdir tmp
  cp "$SRC/$src" tmp/lambda_function.py
  (cd tmp && zip -qr "../$name.zip" .)
  echo "  packaged $name.zip"
done
rm -rf tmp parser_pkg existing-parser.zip

# ---------------------------------------------------------------------------
# Create (or update) the functions
# ---------------------------------------------------------------------------
create_or_update () {
  local name=$1 role=$2 timeout=$3 memory=$4 envvars=$5 layers=${6:-}
  if aws lambda get-function --function-name "$name" >/dev/null 2>&1; then
    echo "updating $name"
    aws lambda update-function-code --function-name "$name" \
        --zip-file "fileb://${BUILD}/${name}.zip" >/dev/null
    aws lambda wait function-updated --function-name "$name"
    aws lambda update-function-configuration --function-name "$name" \
        --timeout "$timeout" --memory-size "$memory" \
        --environment "Variables={$envvars}" \
        ${layers:+--layers "$layers"} >/dev/null
  else
    echo "creating $name"
    aws lambda create-function --function-name "$name" \
        --runtime python3.11 --role "$role" --handler lambda_function.lambda_handler \
        --zip-file "fileb://${BUILD}/${name}.zip" \
        --timeout "$timeout" --memory-size "$memory" \
        --environment "Variables={$envvars}" \
        ${layers:+--layers "$layers"} >/dev/null
  fi
  aws lambda wait function-updated --function-name "$name"
}

create_or_update yf-v2-upload-url "$ROLE_UPLOAD" 30 256 \
  "BUCKET_NAME=$BUCKET,BUCKET_REGION=$REGION,UPLOAD_PREFIX=uploads-v2/,UPLOAD_URL_TTL=900"

create_or_update yf-v2-takeout-parser "$ROLE_PARSER" 900 3008 \
  "OUTPUT_BUCKET=$BUCKET,PARSED_PREFIX=parsed-v2/" "$LAYER_ARN"

create_or_update yf-v2-fusion-recommender "$ROLE_FUSION" 120 1024 \
  "BUCKET_NAME=$BUCKET,MODELS_PREFIX=models-v2/,OUTPUT_PREFIX=recommendations-v2/,PARSED_PREFIX=parsed-v2/"

create_or_update yf-v2-get-recommendations "$ROLE_GET" 30 256 \
  "BUCKET_NAME=$BUCKET,OUTPUT_PREFIX=recommendations-v2/"

echo
echo "Functions ready."
echo
echo "NEXT — two manual steps (deliberately not scripted):"
echo
echo "1. S3 TRIGGERS  (S3 console -> $BUCKET -> Properties -> Event notifications)"
echo "   Ashab's existing notifications stay as they are. ADD two more:"
echo "     a) prefix 'uploads-v2/'  suffix '.zip'"
echo "        -> Lambda  yf-v2-takeout-parser"
echo "     b) prefix 'parsed-v2/'   suffix 'central_output.json'"
echo "        -> Lambda  yf-v2-fusion-recommender"
echo
echo "2. API GATEWAY routes for yf-v2-upload-url and yf-v2-get-recommendations,"
echo "   then point Landing.jsx at the new invoke URLs."
echo
echo "Upload the model artifacts to the v2 prefix:"
echo "   aws s3 cp ~/serving/ s3://$BUCKET/models-v2/ --recursive --include '*.json'"
