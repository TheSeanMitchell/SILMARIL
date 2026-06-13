# SCHEDULING.md — Never miss a market open again

GitHub Actions cron is *best-effort*: under platform load it slips 15–60
minutes or skips whole windows (it skipped the June 11 open). Paid plans do
NOT fix this — cron priority isn't a purchasable feature. The fix is to stop
relying on GitHub's scheduler entirely: an external free cron service calls
the `workflow_dispatch` API on a precise clock. GitHub treats it exactly like
you pressing "Run workflow." Your existing in-repo cron lines stay as backup;
the `concurrency: silmaril-broker` group already prevents double-runs if both
fire.

## Part 1 — Create the token (5 minutes, once)

1. GitHub → click your avatar → **Settings** → **Developer settings**
   → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name: `silmaril-scheduler`. Expiration: 90 days (set a calendar reminder)
   or longer if you accept the tradeoff.
3. **Repository access:** "Only select repositories" → choose **SILMARIL**.
4. **Permissions → Repository permissions → Actions: Read and write.**
   Leave everything else at "No access."
5. Generate, and **copy the token now** (shown once). It looks like
   `github_pat_...`

This token can trigger workflows on this one repo and nothing else — minimal
blast radius if it ever leaks.

## Part 2 — Set up the external cron (10 minutes, once)

Using **cron-job.org** (free, supports POST + custom headers + body):

1. Create a free account at cron-job.org → **Create cronjob**.
2. **URL:**
   `https://api.github.com/repos/TheSeanMitchell/SILMARIL/actions/workflows/daily.yml/dispatches`
3. **Schedule** (set timezone to **UTC** in the job settings):
   every **15 minutes**, hours **13–20**, days **Mon–Fri**.
   (Mirrors the in-repo cron; 13:30 UTC = 9:30 AM ET market open.)
4. Open the **Advanced** tab:
   - Request method: **POST**
   - **Headers** (three of them):
     - `Authorization: Bearer github_pat_YOUR_TOKEN_HERE`
     - `Accept: application/vnd.github+json`
     - `X-GitHub-Api-Version: 2022-11-28`
   - **Request body:** `{"ref":"main"}`
5. Enable **failure notifications** (email on non-2xx responses) so a dead
   token or API change emails you instead of failing silently.
6. Save, then hit **Test run**. Success = HTTP **204 No Content**, and within
   ~10 seconds a new "Daily" run appears in your repo's **Actions** tab.

## Part 3 — Optional second job for the Senate

Same setup, new cronjob: URL ends `/actions/workflows/senate.yml/dispatches`,
schedule **Sundays 06:05 UTC**, same headers and body. Elections never skip.

## Verifying & maintaining

- Watch the Actions tab Monday at 13:30–13:31 UTC: the run should start within
  a minute of the tick — that punctuality is the whole point.
- The sentinel stays as the last line of defense: if BOTH schedulers somehow
  fail during market hours, the briefing goes red with MISSED-RUN.
- When the token expires, generate a new one (Part 1) and paste it into the
  cron-job.org header. Two minutes.
- If you ever rename `daily.yml` or the default branch, update the URL/body.

## Why not alternatives?

UptimeRobot can't send custom POST bodies on free tier; Cloudflare Workers /
Google Cloud Scheduler work fine but need more setup. cron-job.org is the
shortest path. Any service that can POST with custom headers on a schedule
works identically — the GitHub API call is the only thing that matters.
