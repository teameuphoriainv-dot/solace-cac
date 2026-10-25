# Deploying Solace

Solace deploys as **one Docker container**: FastAPI serves the API and the built React app
on a single port (7860, or whatever `PORT` is set to). The `Dockerfile` at the repo root
does everything: it builds the frontend, downloads and checks the trained model, and starts
the server.

**The hosted demo runs on AWS App Runner** (Option D below), at
<https://r2i8nkjrmh.us-east-1.awsapprunner.com>: one always-on container running in no-key mode
(rules and the trained model, no AI calls). Options A to C are other ways to host the same image.

Good to know before you pick a host:

- **Memory.** Loading the trained model alone peaked at about 420 MB in our measurement, and
  the running container used about 300 MB after a few check-ins and a bedside re-check.
  Give the container at least 1 GB of memory, and 2 GB to be comfortable. The image is about
  1.3 GB.
- **Data is kept in memory.** Restarting the container clears every test patient. The five
  built-in patients come back automatically. Each visitor gets a private practice hospital
  (an id like `demo-k3x9q2`) that is cleared after two idle hours.
- **No key is required.** Without `ANTHROPIC_API_KEY` every feature still works or explains
  in plain words what is off. With a key, AI features switch on, up to the daily budget.

## Settings

Set these on the host. Put API keys in the host's **secret** settings, never in the code.

| Name | Kind | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | secret | Turns on the Claude features (comfort text, notes, reasoning, card reading). |
| `AI_DAILY_BUDGET_USD` | variable | Stops calling Claude for the rest of the day (UTC) once this many dollars are spent. The hosted demo uses `3` (also the default). |
| `AI_CALLS_PER_VISITOR_HOUR` | variable | How many Claude calls one visitor (address and browser) can cause per hour, counting the background clinician summaries made after each check-in. Default `120`. |
| `AI_HOURLY_BUDGET_FRACTION`, `AI_CALLS_PER_MINUTE` | variable | Limits for everyone together, so one burst cannot switch AI off for the whole day: at most this share of the daily budget in one clock hour (default `0.35`) and at most this many Claude calls in any 60 seconds (default `40`). |
| `SOLACE_TRUSTED_PROXY_HOPS` | variable | How many proxies in front of the server add an `X-Forwarded-For` entry. Default `1`, right for App Runner, whose proxy appends the real client address as the last entry. Use `0` when nothing sits in front of the server. On another host, check how its proxy fills the header before relying on the per-visitor limits. |
| `SANDBOX_CREATES_PER_CLIENT_HOUR`, `SANDBOX_LIVE_PER_CLIENT` | variable | One client address may create this many private demo hospitals an hour (default `5`) and keep this many alive (default `10`). Past either limit, or when all `SANDBOX_MAX` (300) are in use, the visitor is served the shared `demo` hospital instead of an error. |
| `OPENAI_API_KEY` | secret, optional | Server-side speech to text (Whisper). Most browsers dictate without it. |
| `ELEVENLABS_API_KEY` | secret, optional | Spoken audio of the guidance. The free browser read-aloud works without it. |
| `SOLACE_JWT_SECRET` | secret, recommended | The key that signs nurse sign-ins. Any long random text (for example the output of `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). Without it a new key is made at every start, so nurses sign in again after a restart. |
| `SMS_PROVIDER`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM_NUMBER` | secret, optional | Real text messages, only with `SMS_PROVIDER=twilio` and all three Twilio settings. Without them the app shows the exact text it would send. |

Also set a monthly spend limit for your key in the Anthropic Console. The app's budget lives
in memory and restarts with the container, so the Console limit is the hard backstop.

`.env.example` in the repo root lists every setting with a comment.

## Option A: Hugging Face Spaces

**Cost, checked 2026-10-18:** Hugging Face's docs now say Docker Spaces "require a paid plan
to create: PRO for personal accounts" ($9 a month). The CPU Basic hardware itself (2 vCPUs,
16 GB of memory) is free. Judging runs through November and winners are announced in
December, so plan for two or three months.

1. **Publish the model release first** (see the checklist). The Space build downloads the
   model from the GitHub release with `scripts/fetch_models.sh` and checks every file's
   sha256. If you cannot publish the release, use `--with-models` in step 4 instead.
2. **Create the Space** at <https://huggingface.co/new-space>: pick a name (for example
   `solace-cac`), license MIT, SDK **Docker**, template **Blank**, hardware **CPU basic**,
   visibility **Public**.
3. **Add settings** in the Space's **Settings** tab, under **Variables and secrets**:
   - **New secret:** `ANTHROPIC_API_KEY` (and any optional keys you use).
   - **New secret:** `SOLACE_JWT_SECRET`, any long random text.
   - **New variable:** `AI_DAILY_BUDGET_USD` = `3`.
   Variables are visible to anyone; secrets are not. Spaces also pass variables to the
   Docker build, so a variable named `FETCH_MODELS` set to `0` skips the model download.
4. **Prepare the Space copy of the code** on your computer, outside the repo folder:

   ```bash
   deploy/huggingface/prepare_space.sh ~/solace-space
   ```

   This copies the code without secrets, `node_modules`, the virtual environment or the
   model files, and uses `deploy/huggingface/README.md` as the Space's README (Spaces read
   their settings from it). Open `~/solace-space/README.md` and fill in the repo link.

   Only if the GitHub release is not available: add `--with-models` to copy the model files
   too. Files that large need Hugging Face's large-file support: install git-xet
   (<https://huggingface.co/docs/hub/xet/using-xet-storage>) and run
   `git lfs track "backend/models/*.txt" "backend/models/*.pkl"` after `git init` below.

5. **Push it.** Create a Hugging Face access token with write permission at
   <https://huggingface.co/settings/tokens> and use it as the password when git asks.

   ```bash
   cd ~/solace-space
   git init -b main
   git add -A
   git commit -m "Deploy Solace"
   git remote add space https://huggingface.co/spaces/<your-hf-name>/solace-cac
   git push --force space main
   ```

   The force push replaces the starter README that Hugging Face made.
6. **Watch the build** in the Space's **Logs** tab. The first build takes several minutes.
   Look for `fetch_models: installed the triage model` and then the Uvicorn startup line.
7. **Check it.** The app's own address is `https://<your-hf-name>-solace-cac.hf.space`.
   Share that one with judges, not the huggingface.co page around it.
   - `/health` should say `"status": "ok"`.
   - `/api/demo/capabilities` should say `"loaded": true` under `triage_model`, and
     `"llm": true` if you set the key.
   - `/` should show the Solace front page. Check in once from your phone.
   - From your computer: `python3 scripts/seed_demo.py --url https://<your-hf-name>-solace-cac.hf.space`
8. **Keep it awake.** Free hardware goes to sleep when nobody visits for a while, and the
   next visitor waits for it to start again. Open the link yourselves the morning judging
   starts and every few days after.
9. **Updating:** make a fresh folder and repeat steps 4 and 5. **Turning AI off:** delete the
   `ANTHROPIC_API_KEY` secret and restart the Space from **Settings**.

## Option B: Render

**Cost, checked 2026-10-18:** Render's Free and Starter web services have 512 MB of memory,
which is not enough to load the model reliably. Pick **Standard** (2 GB, $25 a month at the
time of writing) or larger. Free services also stop after 15 minutes without visitors and
take about a minute to wake up.

1. Push the repo to GitHub and publish the model release (Render builds from GitHub, where
   the model files are not stored).
2. In the Render dashboard choose **New**, then **Web Service**, and connect the repo.
   Render detects the `Dockerfile`; keep the language as **Docker**.
3. Choose the instance type (see above).
4. Under **Environment**, add `ANTHROPIC_API_KEY`, `AI_DAILY_BUDGET_USD` and `SOLACE_JWT_SECRET`. Render also passes
   these to the Docker build as build arguments, so `FETCH_MODELS=0` works here too.
5. Under **Advanced**, set **Health Check Path** to `/health`.
6. Create the service and watch the deploy log. Render sets `PORT` (10000 by default) and the
   container listens on it automatically.
7. Run the same checks as step 7 above with your `onrender.com` address.

If you only have a 512 MB instance, you can still run Solace without the trained model: set
`FETCH_MODELS=0`. Triage then uses the deterministic rules only, and
`/api/demo/capabilities` reports `"mode": "rules_only"`.

## Option C: any computer with Docker

```bash
docker build -t solace-cac .                               # downloads the model release
docker build --build-arg FETCH_MODELS=0 -t solace-cac .    # or: use the files already in backend/models
docker run --rm -p 7860:7860 solace-cac                    # then open http://localhost:7860
docker run --rm -p 7860:7860 -e ANTHROPIC_API_KEY=sk-ant-... -e AI_DAILY_BUDGET_USD=3 solace-cac
```

Any host that runs a Docker image with at least 1 GB of memory works the same way (for
example Google Cloud Run or Fly.io): expose port 7860 or set `PORT`.

## Option D: AWS App Runner (the hosted demo)

`deploy/aws/apprunner.md` has the exact AWS CLI steps for one always-on container named
`solace-cac` (1 vCPU, 2 GB, exactly one instance), with the Anthropic key read from AWS
Secrets Manager at startup through `SOLACE_KEYS_SECRET` and a $3 daily AI budget. Read its
first section before starting: App Runner is closed to new AWS customers, and it runs only
`linux/amd64` images.

## The model release

The trained model files are not in git. `scripts/fetch_models.sh` downloads them from the
GitHub release `models-v1` of `teameuphoriainv-dot/solace-cac` and checks the tarball and
every file against pinned sha256 values. To publish it, upload the exact tarball the pins
were made from (`solace-models-v1.tar.gz`, sha256
`bb76713729aac4edb576a501c695f1b965d33a27fc4abc8959b166bcbe19036f`):

```bash
gh release create models-v1 solace-models-v1.tar.gz --repo teameuphoriainv-dot/solace-cac \
  --title "Trained triage model v1" \
  --notes "5-fold LightGBM, artifacts.pkl and conformal.pkl. Use scripts/fetch_models.sh, which checks every file's sha256."
```

The release must be public, or the Docker build cannot download it. If that tarball is lost,
rebuild it from `backend/models`; the files inside keep their pins, but the tarball gets a
new sha256, so put that in `TARBALL_SHA256` in `scripts/fetch_models.sh`:

```bash
cd backend/models && COPYFILE_DISABLE=1 tar --format ustar --uid 0 --gid 0 --uname root \
  --gname root -czf ../../solace-models-v1.tar.gz artifacts.pkl conformal.pkl \
  lgbm_fold0.txt lgbm_fold1.txt lgbm_fold2.txt lgbm_fold3.txt lgbm_fold4.txt
```

If the model is retrained or `scripts/calibrate_conformal.py` is re-run, every file changes:
update all the pins (`shasum -a 256 backend/models/*`) and publish a new release tag instead
of replacing `models-v1`.

## Troubleshooting

- **The build stops at `fetch_models: download failed`.** The release `models-v1` does not
  exist yet, or the repo is private. Publish it, or build with the files in place
  (`--with-models` on Spaces, `FETCH_MODELS=0` locally).
- **`tarball sha256 is ..., expected ...`.** The file on the release is not the one the pins
  were made from. Upload the original `solace-models-v1.tar.gz` again. Only change the pins
  in `scripts/fetch_models.sh` if you retrained the model on purpose.
- **`/api/demo/capabilities` says `"loaded": false`.** The model files are not in the image,
  so triage is running on the rules alone. Rebuild with the model.
- **The container keeps restarting.** Usually out of memory. Use an instance with 2 GB.
- **AI features say they are off even with a key.** Check the key is set as a secret with the
  exact name `ANTHROPIC_API_KEY`, then restart. If it worked earlier today, the daily budget
  may be used up; it resets at midnight UTC.
