# Voting Booth

FastAPI-based school election app for voting on Head Boy and Head Girl, backed by SQLite and prepared for deployment on Render with a persistent disk.

## Local Run

1. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Initialize the database and generate voter names with numeric voting codes:

   ```bash
   python init_db.py
   ```

3. Start the app:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Open `http://127.0.0.1:8000`.

## Admin Access

Admin login URL:

```text
http://127.0.0.1:8000/admin/login
```

Default local credentials:

```text
Username: admin
Password: AdminBooth2026!
Secret key: booth-admin-export-key
```

Admin capabilities:

- Manage Head Boy and Head Girl candidates
- Add voters manually
- Import voters from CSV
- Reset voter codes
- Remove non-voting voter records
- Review voter status and voting timestamp
- Export election results CSV
- Export voter CSV including current codes

CSV voter import format:

```csv
name,code
Student One,1234
Student Two,5678
```

## Render Deployment

This project is configured for:

- Render native Python web service
- SQLite on a persistent disk
- Environment-variable managed secrets

Files involved:

- [render.yaml](/Users/sunny/Documents/projects/voting-booth/render.yaml)
- [bootstrap_render.py](/Users/sunny/Documents/projects/voting-booth/bootstrap_render.py)
- [app/config.py](/Users/sunny/Documents/projects/voting-booth/app/config.py)

### Deploy Steps

1. Push this repo to GitHub.
2. In Render, create a new Blueprint instance from the repository.
3. Render will detect [render.yaml](/Users/sunny/Documents/projects/voting-booth/render.yaml) and create the web service plus persistent disk configuration.
4. In Render, set values for:

   ```text
   ADMIN_PASSWORD
   ADMIN_SECRET_KEY
   ```

5. Deploy the service.

### What Happens on First Deploy

- Render mounts the persistent disk at `/var/data`
- The app creates missing tables and applies non-destructive schema updates
- It does not auto-seed candidates or voters on deployment
- Election data should be loaded intentionally through the admin panel or a manual one-time initialization step

### Recommended Render Settings

- Keep the persistent disk mount path as `/var/data`
- Keep the SQLite database on the disk at `/var/data/voting_booth.db`
- Do not commit local `voting_booth.db` or `voter_creds.txt`
- Use strong custom values for `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, and keep the generated `SESSION_SECRET_KEY`
- The only production storage path that matters is the SQLite database path

### After Deploy

1. Open `/admin/login`
2. Sign in with the Render environment credentials
3. Add candidates and import voters from the admin panel
4. Export the generated voter codes from the admin panel once the import is complete

### Important Safety Note

- Do not run `init_db.py` against production. It deletes and recreates the SQLite database by design.
- Render deployments now start with `uvicorn` only and do not run any auto-seeding step.
- The only remaining destructive reset path is the explicit `init_db.py` script, which should be treated as a development/local setup tool.

### Production Storage Summary

- Production persistence depends on the Render disk mounted at `/var/data`
- Production database path should be `/var/data/voting_booth.db`
- `CREDENTIALS_PATH` is only a local/dev convenience and is not required for normal production operation

### Notes

- This deployment path does not require Docker.
- SQLite persistence depends on the Render disk, not the service filesystem.
- Redeploys should preserve the database as long as the same persistent disk remains attached.
