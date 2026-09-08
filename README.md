# Route Tracker — Streamlit Edition

Web version of the Bell Fuels route efficiency tracker. Users upload the daily
unified workbook (`Bell_Unified_<date>.xlsx`, produced by
`scripts/build_unified.py` and emailed each day) and get: Quick View with
shift timeline, Daily Route Performance, Driver comparison, and a read-only
Payroll & HOS grid.

**This repo contains code only. No delivery, customer, or payroll data may
ever be committed** — see Security below.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the printed URL, then drop the emailed `Bell_Unified_….xlsx` into the
sidebar upload box.

## Daily use

1. Open the app URL.
2. Upload the unified file from today's email (sidebar).
3. Everything loads for that session. Closing the tab clears it — you upload
   again next visit. Nothing is stored on the server.

Data corrections (payroll times, settings like shift split or benchmarks) are
made **in Excel on the unified file** before it's emailed — never in this app.

## Deploy to Streamlit Community Cloud

1. Push this folder to a **private** GitHub repo (see Security checklist first).
2. Go to https://share.streamlit.io → "Create app" → connect GitHub → pick the
   private repo, branch `main`, main file `app.py` → Deploy.
3. **Restrict viewers** (required): App → Settings → Sharing → set
   "Who can view this app" to *Only specific people* → add each coworker's
   email. Viewers sign in with a Google/GitHub account matching that email.
4. Test: open the app URL in a private/incognito window with a non-invited
   account — it must be blocked.

## Making a change

There is **one** GitHub repo (`BellFuels/OpsDashboard`) and **two local clones**
of it:

| Clone | Line endings |
|---|---|
| `Desktop\OpsDashboard` | CRLF |
| `The_Oracle_USB\streamlit_app` | LF |

They share a remote but do not update together, so either can fall behind.
Streamlit Community Cloud watches `main`, so **pushing to `main` is the deploy** —
there is no separate publish step.

1. **Pull first**, in whichever clone you are about to edit:

   ```bash
   git pull --ff-only origin main
   ```

2. **Edit and test locally.** A change under `lib/` needs a server restart — a
   browser reload only re-runs `app.py`, not the cached imports.
3. **Run the data check** from the Security checklist below. Output must be empty.
4. **Commit and push.** This triggers the redeploy:

   ```bash
   git push origin main
   ```

5. **Watch the build** at https://share.streamlit.io → your app → "Manage app".
   Usually a minute or two; longer if `requirements.txt` changed. The deployed
   app has no `ORACLE_DEV_FILE`, so you land on the upload gate and need that
   day's `Bell_Unified_<date>.xlsx` to see anything.
6. **Pull in the other clone** so it does not drift:

   ```bash
   git pull --ff-only origin main
   ```

Never hand-copy files between the two clones. That leaves the second one dirty
and stale — uncommitted edits sitting on an older commit — even when the file
contents happen to match.

## Security checklist

- ✅ **Private repo.** Create with `gh repo create <name> --private` and verify
  Settings → General shows "Private".
- ✅ **No data in git.** `.gitignore` blocks `*.xls*`, `*.csv`, `*.pdf`,
  `*.json`, and the `inbox/`, `unified/`, `processed/` folders. Before every
  push run:

  ```bash
  git ls-files | grep -iE '\.(xlsx?|xlsm|csv|pdf|json)$' | grep -v '^\.devcontainer/'
  ```

  Output must be empty. (The `.devcontainer/` filter excludes
  `devcontainer.json`, which is tracked on purpose — it is Codespaces
  scaffolding, not data. Without that filter the check always reports a false
  positive.)
- ✅ **Upload-per-session only.** Data enters via the upload box, is parsed
  from memory (`BytesIO`), and lives in `st.session_state` for that session
  only. The app never writes files, never uses `st.cache_data` for data
  (that cache is shared across sessions on Streamlit Cloud), and logs no rows.
- ✅ **Viewer allowlist on** (step 3 above). The app URL alone must not grant
  access.
- ✅ Session end (tab closed / idle timeout) drops the data from server memory.

## What's in the repo

| Path | Purpose |
|---|---|
| `app.py` | Streamlit app — sidebar upload gate + five tabs |
| `lib/parsing.py` | Reads the unified workbook from memory; schema validation |
| `lib/calc.py` | Roll-ups, averages, deviations, gal/hr, payroll grid (ported from the browser app) |
| `lib/timeline.py` | Plotly shift-timeline figure |
| `scripts/build_unified.py` | The daily file **builder** — runs locally at Bell Fuels (via Claude Cowork), never on the cloud. Kept here so producer and consumer stay versioned together. |

## Known differences from the desktop (HTML) app

- Shift timeline is read-only: DVIR is shown as fixed 15-minute blocks; no
  custom time blocks (those relied on browser-local storage).
- Nothing persists between sessions — by design (see Security).
- The report table shows all columns (no collapsible groups); per-driver
  totals live in an expander.
- The deviation-threshold slider is session-only, seeded from the file's Meta
  sheet.
