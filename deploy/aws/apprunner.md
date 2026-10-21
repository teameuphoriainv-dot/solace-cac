# Hosting Solace on AWS App Runner

This is how the hosted demo runs: **one App Runner service named `solace-cac` in
`us-east-1`**, one always-on container (1 vCPU, 2 GB), HTTPS handled by AWS, the Anthropic
key read from AWS Secrets Manager once at startup, and a $3 daily AI budget. Every visitor
gets a private practice hospital (`demo-xxxxxx`).

| Piece | Name |
|---|---|
| App Runner service | `solace-cac` (us-east-1) |
| Service address | <https://vdb83cp227.us-east-1.awsapprunner.com> |
| ECR repository | `solace-cac` |
| Access role (pulls the image) | `solace-cac-apprunner-ecr` |
| Instance role (what the container may do) | `solace-cac-apprunner-instance` |
| Auto scaling configuration | `solace-cac-single` (min 1, max 1) |
| Keys secret (read only for the Anthropic key) | `solace/api-keys` |

Everything Solace creates here has a name starting with `solace-cac`. **Do not touch** the
older `solace-api` ECR repository, the Lambda function, Amplify, CloudFront or DynamoDB.
None of the commands below read or change them, and `solace/api-keys` is only read.

Run the commands yourself, one block at a time, from the repo root on your own computer.
Nothing in this repo runs them for you.

## 0. Read this first

- **App Runner is closed to new customers.** The App Runner developer guide (checked
  2026-10-18) says: "AWS App Runner is no longer open to new customers. Existing customers
  can continue to use the service as normal." The account that runs `solace-cac` already
  has it. A different, new account may be refused at step 6; AWS points to Amazon ECS
  Express Mode instead
  (https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html).
- **The image must be `linux/amd64` (x86_64).** App Runner has no Arm (Graviton) option
  (https://github.com/aws/apprunner-roadmap/issues/98 is still open). An image built on an
  Apple Silicon Mac is `arm64` by default and will not start, so every build below uses
  `docker buildx --platform linux/amd64 --provenance=false` and checks the result.
- **Exactly one instance.** Patients, sandboxes, sign-ins and the day's AI spend live in
  the container's memory, so `solace-cac-single` pins the service to min = max = 1. A new
  deployment or an instance replacement clears that memory; the five example patients
  come back by themselves.
- **Idle CPU.** App Runner throttles an instance's CPU while it is not handling a request.
  The clinician summaries made right after a check-in run in a background thread, so they
  can finish more slowly when nobody is using the site. The patient's result page and the
  nurse dashboard poll the server, which keeps it busy during a demo.
- **Also set a spend limit in the Anthropic Console.** The $3 budget lives in memory and
  starts again at zero when the container restarts.

## 1. Settings for this shell

```bash
export AWS_REGION=us-east-1
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export REPO=solace-cac
export TAG=v1                                   # use a new tag for every build
export IMAGE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:$TAG"
export WORK=/tmp/solace-cac-deploy             # scratch folder for the JSON files below
mkdir -p "$WORK"
```

## 2. ECR repository and the image

Create the repository once:

```bash
aws ecr create-repository --region "$AWS_REGION" --repository-name "$REPO" \
  --image-scanning-configuration scanOnPush=true
```

Log in, build for `linux/amd64`, check the architecture, then push. `--provenance=false`
keeps the push a plain single-platform image.

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
# If the models-v1 release is not published yet, add: --build-arg FETCH_MODELS=0
# (backend/models must then hold the pinned files: scripts/fetch_models.sh --verify).
docker buildx build --platform linux/amd64 --provenance=false -t "$IMAGE" --load .
docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE"   # must print linux/amd64
docker push "$IMAGE"
```

On an Apple Silicon Mac the build runs under emulation and is slow. `docker buildx ls` must
list `linux/amd64` for the active builder; with colima, start it with amd64 emulation
(for example `colima start --vm-type vz --vz-rosetta`).

## 3. The Anthropic key secret

The service reads `solace/api-keys`. Check that it exists, note its ARN and KMS key, and
list its key names (this prints names only, never values):

```bash
aws secretsmanager get-secret-value --region "$AWS_REGION" --secret-id solace/api-keys \
  --query SecretString --output text \
  | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)))'
export KEYS_SECRET_ARN="$(aws secretsmanager describe-secret --region "$AWS_REGION" \
  --secret-id solace/api-keys --query ARN --output text)"
export KEYS_KMS_KEY="$(aws secretsmanager describe-secret --region "$AWS_REGION" \
  --secret-id solace/api-keys --query KmsKeyId --output text)"
```

The list must include `ANTHROPIC_API_KEY` (or `anthropic_api_key`). With
`SOLACE_KEYS_SECRET=solace/api-keys` set, Solace takes **only** that one key from the
secret, even though the secret also holds other providers' keys, because the daily budget
covers Claude only. Speech-to-text and voice stay on their no-key versions.

If the secret ever lacks an Anthropic key, do not edit a secret another app may read. Make
a new one and use its name in place of `solace/api-keys` in steps 4 and 6:

```bash
read -rs ANTHROPIC_KEY   # paste the key, then press Enter (nothing is shown)
printf '{"ANTHROPIC_API_KEY": "%s"}' "$ANTHROPIC_KEY" > "$WORK/keys.json"
aws secretsmanager create-secret --region "$AWS_REGION" --name solace-cac/api-keys \
  --secret-string "file://$WORK/keys.json"
rm "$WORK/keys.json"; unset ANTHROPIC_KEY
```

### No sign-in signing secret

The service sets no `RuntimeEnvironmentSecrets`. Without `SOLACE_JWT_SECRET`, the app makes
a random signing key for clinician sign-ins when the process starts (lib/jwt_auth.py), and
it never leaves that process.

- **Why this works:** there is exactly one instance, so the process that signs a sign-in
  token is the same one that checks it.
- **What it costs:** every deployment, restart or instance replacement makes a new key, so
  anyone signed in as a demo clinician is signed out and signs in again (Dr. Chen, PIN
  224466). Nothing else is lost by this, because the patients and sandboxes were in that
  same process's memory and are gone after a restart anyway.
- **What it saves:** no second secret to create, rotate or grant, and one less permission
  on the instance role.
- **If you ever run more than one instance**, each would have its own key and sign-ins
  would fail on the other one. Do not do that: the in-memory data would split the same way.

## 4. IAM roles

**Access role** `solace-cac-apprunner-ecr` (lets App Runner pull the image), scoped to the
`solace-cac` repository only:

```bash
cat > "$WORK/ecr-trust.json" <<'JSON'
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
  "Principal": {"Service": "build.apprunner.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
JSON
cat > "$WORK/ecr-policy.json" <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
  {"Effect": "Allow",
   "Action": ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage",
              "ecr:DescribeImages", "ecr:GetDownloadUrlForLayer"],
   "Resource": "arn:aws:ecr:$AWS_REGION:$ACCOUNT_ID:repository/$REPO"}]}
JSON
aws iam create-role --role-name solace-cac-apprunner-ecr \
  --assume-role-policy-document "file://$WORK/ecr-trust.json"
aws iam put-role-policy --role-name solace-cac-apprunner-ecr \
  --policy-name solace-cac-ecr-pull --policy-document "file://$WORK/ecr-policy.json"
export ACCESS_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/solace-cac-apprunner-ecr"
```

**Instance role** `solace-cac-apprunner-instance` (what the running container may do):
read the keys secret, nothing else.

```bash
cat > "$WORK/instance-trust.json" <<'JSON'
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
  "Principal": {"Service": "tasks.apprunner.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
JSON
cat > "$WORK/instance-policy.json" <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": "$KEYS_SECRET_ARN"}]}
JSON
aws iam create-role --role-name solace-cac-apprunner-instance \
  --assume-role-policy-document "file://$WORK/instance-trust.json"
aws iam put-role-policy --role-name solace-cac-apprunner-instance \
  --policy-name solace-cac-read-keys --policy-document "file://$WORK/instance-policy.json"
export INSTANCE_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/solace-cac-apprunner-instance"
```

If step 3 printed a `KmsKeyId` (a customer managed key, not `None`), also allow decrypting
with that one key, only through Secrets Manager:

```bash
if [ "$KEYS_KMS_KEY" != "None" ]; then
  KMS_KEY_ARN="$(aws kms describe-key --region "$AWS_REGION" --key-id "$KEYS_KMS_KEY" \
    --query KeyMetadata.Arn --output text)"
  cat > "$WORK/instance-kms.json" <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "kms:Decrypt", "Resource": "$KMS_KEY_ARN",
   "Condition": {"StringEquals": {"kms:ViaService": "secretsmanager.$AWS_REGION.amazonaws.com"}}}]}
JSON
  aws iam put-role-policy --role-name solace-cac-apprunner-instance \
    --policy-name solace-cac-decrypt-keys --policy-document "file://$WORK/instance-kms.json"
fi
```

New roles can take a few seconds to be usable. Wait about 10 seconds before step 6.

## 5. One instance, always

```bash
export SCALING_ARN="$(aws apprunner create-auto-scaling-configuration --region "$AWS_REGION" \
  --auto-scaling-configuration-name solace-cac-single --min-size 1 --max-size 1 \
  --max-concurrency 100 \
  --query AutoScalingConfiguration.AutoScalingConfigurationArn --output text)"
```

## 6. Create the service

`SOLACE_MODE=local` keeps all data in memory and makes no AWS calls except the one secret
read at startup. `PORT` is reserved by App Runner and is set from the `Port` value. The
image already sets `SOLACE_SEED_BACKGROUND=1`, so `/health` answers about a second after
the process starts while the demo clinicians, the example patients and the bedside model
are made in the background (`/health` shows their progress under `seeding`).

```bash
cat > "$WORK/source.json" <<JSON
{
  "AuthenticationConfiguration": {"AccessRoleArn": "$ACCESS_ROLE_ARN"},
  "AutoDeploymentsEnabled": false,
  "ImageRepository": {
    "ImageIdentifier": "$IMAGE",
    "ImageRepositoryType": "ECR",
    "ImageConfiguration": {
      "Port": "7860",
      "RuntimeEnvironmentVariables": {
        "SOLACE_MODE": "local",
        "SOLACE_KEYS_SECRET": "solace/api-keys",
        "AI_DAILY_BUDGET_USD": "3"
      }
    }
  }
}
JSON
export SERVICE_ARN="$(aws apprunner create-service --region "$AWS_REGION" \
  --service-name solace-cac \
  --source-configuration "file://$WORK/source.json" \
  --instance-configuration "{\"Cpu\": \"1 vCPU\", \"Memory\": \"2 GB\", \"InstanceRoleArn\": \"$INSTANCE_ROLE_ARN\"}" \
  --health-check-configuration '{"Protocol": "HTTP", "Path": "/health", "Interval": 20, "Timeout": 10, "HealthyThreshold": 1, "UnhealthyThreshold": 10}' \
  --auto-scaling-configuration-arn "$SCALING_ARN" \
  --query Service.ServiceArn --output text)"
```

The health check asks `/health` every 20 seconds, allows 10 seconds for an answer, and
replaces the instance only after 10 failures in a row (about 3 minutes), so one slow moment
never restarts the demo and wipes its memory.

`SOLACE_KEYS_SECRET` is a name here, so the app reads it in the container's region
(us-east-1). If the secret were in another region, its full ARN would go there instead;
the app then reads the region from the ARN.

Wait until it is running (about 5 minutes), then get its address:

```bash
until [ "$(aws apprunner describe-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN" \
  --query Service.Status --output text)" != "OPERATION_IN_PROGRESS" ]; do sleep 15; done
aws apprunner describe-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN" \
  --query Service.Status --output text                                # must print RUNNING
export SERVICE_URL="https://$(aws apprunner describe-service --region "$AWS_REGION" \
  --service-arn "$SERVICE_ARN" --query Service.ServiceUrl --output text)"
echo "$SERVICE_URL"
```

In a new shell, find the service again with:

```bash
export SERVICE_ARN="$(aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceName=='solace-cac'].ServiceArn | [0]" --output text)"
```

## 7. Point link previews at the real address

Add `SOLACE_PUBLIC_URL` so the page's share image links are absolute, then redeploy:

```bash
python3 - "$WORK/source.json" "$SERVICE_URL" <<'PY'
import json, sys
path, url = sys.argv[1], sys.argv[2]
src = json.load(open(path))
src["ImageRepository"]["ImageConfiguration"]["RuntimeEnvironmentVariables"]["SOLACE_PUBLIC_URL"] = url
json.dump(src, open(path, "w"), indent=2)
PY
aws apprunner update-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN" \
  --source-configuration "file://$WORK/source.json" --query Service.Status --output text
```

## 8. Check it

```bash
curl -s "$SERVICE_URL/health" | python3 -m json.tool
curl -s -D - -o /dev/null "$SERVICE_URL/" | grep -i -E 'content-security-policy|x-frame-options|x-content-type-options'
```

Look for `"status": "ok"`, `"mode": "local"`, `capabilities.llm` true (the key was read),
`ai_budget.budget_usd` 3.0 with `ai_budget.hour_cap_usd` 1.05, and `seeding.state` "done"
with `seeding.model` "ready" once startup work has finished (about a minute). If `llm` is
false, the logs say why without printing the key:

```bash
aws logs tail "/aws/apprunner/solace-cac/$(basename "$SERVICE_ARN")/application" \
  --region "$AWS_REGION" --since 30m | grep -i "secrets manager"
```

Then open `$SERVICE_URL`, check in as a patient at `/demo`, sign in at `/demo/clinician` as
Dr. Chen with PIN 224466, and open `/showcase` (both panes must load).

## Redeploying a new build

Build and push the new image under a **new tag**, then point the service at it.
`update-service` starts the deployment by itself:

```bash
export TAG=v2                                   # the next unused tag
export IMAGE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:$TAG"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker buildx build --platform linux/amd64 --provenance=false -t "$IMAGE" --load .
docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE"   # linux/amd64
docker push "$IMAGE"
aws apprunner describe-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN" \
  --query Service.SourceConfiguration --output json > "$WORK/source.json"
python3 - "$WORK/source.json" "$IMAGE" <<'PY'
import json, sys
path, image = sys.argv[1], sys.argv[2]
src = json.load(open(path))
src["ImageRepository"]["ImageIdentifier"] = image
json.dump(src, open(path, "w"), indent=2)
PY
aws apprunner update-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN" \
  --source-configuration "file://$WORK/source.json" --query Service.Status --output text
```

`describe-service` hands back the service's current settings (environment variables and
the access role included), so only the image changes.

`aws apprunner start-deployment` does not change the image setting: it pulls the tag the
service already points at again. Use it after pushing a rebuilt image under that **same**
tag, or to restart the service so it reads a changed Anthropic key from Secrets Manager:

```bash
aws apprunner start-deployment --region "$AWS_REGION" --service-arn "$SERVICE_ARN"
```

Either way the deployment replaces the one instance, which clears its memory (see step 0).

## Abuse limits on the hosted demo

These need no setting; each one can be changed with the environment variable named.

- **Who a visitor is.** The AWS proxy appends the real client address as the **last**
  `X-Forwarded-For` entry, and only that entry is trusted (`SOLACE_TRUSTED_PROXY_HOPS`,
  default 1). Anything a visitor writes into the header themselves comes before it and is
  ignored, so changing it does not reset any limit.
- **Private practice hospitals.** One client address may create 5 new sandboxes an hour
  (`SANDBOX_CREATES_PER_CLIENT_HOUR`) and keep 10 alive at once
  (`SANDBOX_LIVE_PER_CLIENT`); at most 300 exist in all (`SANDBOX_MAX`). Asking
  `/api/<id>/capabilities` never creates one. Past any of these limits, the visitor's id
  is quietly served from the shared `demo` hospital instead, and stays that way for that
  id: check-in, sign-in and the live queue all work, so a judge never sees an error. The
  log line `served from the shared demo hospital` and `sandboxes.shared_aliases` in
  `/health` show when this happens.
- **AI spend.** Besides the $3 daily stop (`AI_DAILY_BUDGET_USD`), at most 35% of it is
  spent in any one clock hour (`AI_HOURLY_BUDGET_FRACTION`) and at most 40 Claude calls
  start in any 60 seconds (`AI_CALLS_PER_MINUTE`), whoever is asking. A burst can pause
  AI for the rest of that hour, not the whole day. Each visitor also gets 120 Claude calls
  an hour (`AI_CALLS_PER_VISITOR_HOUR`), counting the background clinician summaries made
  after each check-in. Past any limit, features show their no-AI versions.
- **Security headers.** Every response carries a Content-Security-Policy (`default-src
  'self'`, Google Fonts allowed, `frame-ancestors 'self'`), `X-Frame-Options: SAMEORIGIN`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and a
  Permissions-Policy that allows the camera and microphone for this site only. `/showcase`
  frames the app's own pages, which these allow. HTTPS is handled by the AWS proxy.

## Taking it down after judging

Only the `solace-cac` resources made above:

```bash
aws apprunner delete-service --region "$AWS_REGION" --service-arn "$SERVICE_ARN"
aws apprunner delete-auto-scaling-configuration --region "$AWS_REGION" \
  --auto-scaling-configuration-arn "$SCALING_ARN"
aws ecr delete-repository --region "$AWS_REGION" --repository-name solace-cac --force
aws iam delete-role-policy --role-name solace-cac-apprunner-instance --policy-name solace-cac-read-keys
aws iam delete-role-policy --role-name solace-cac-apprunner-instance --policy-name solace-cac-decrypt-keys  # only if made
aws iam delete-role --role-name solace-cac-apprunner-instance
aws iam delete-role-policy --role-name solace-cac-apprunner-ecr --policy-name solace-cac-ecr-pull
aws iam delete-role --role-name solace-cac-apprunner-ecr
```

Leave `solace/api-keys` alone: the older app may still read it.

## Known limits

- Data lives in memory: a restart, a deployment or an instance replacement clears every
  test patient, every sign-in and the day's AI spend count.
- Visitors behind one shared address (a school or office network) share the sandbox
  allowance of that address; once it is used up, the rest share the `demo` hospital.
- The per-visitor AI limit keys on the address and the browser, so it can be shared or
  split the same way. The hourly share, the per-minute ceiling, the $3 daily stop and the
  Anthropic Console limit hold no matter who is asking.
