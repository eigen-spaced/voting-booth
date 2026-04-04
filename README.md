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
- First-boot automatic data bootstrap
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
- `bootstrap_render.py` runs before the app starts
- If no election data exists yet, it seeds:
  - 6 default candidates
  - 10 default voters
  - `/var/data/voter_creds.txt`
- If data already exists, bootstrap does nothing and preserves the current election state

### Recommended Render Settings

- Keep the persistent disk mount path as `/var/data`
- Do not commit local `voting_booth.db` or `voter_creds.txt`
- Use strong custom values for `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, and keep the generated `SESSION_SECRET_KEY`

### After Deploy

1. Open `/admin/login`
2. Sign in with the Render environment credentials
3. Confirm candidates and voters look correct
4. Retrieve `voter_creds.txt` from the persistent disk if you need the seeded voter codes
5. Replace the seeded voters with a CSV import if the real voter list differs

### Notes

- This deployment path does not require Docker.
- SQLite persistence depends on the Render disk, not the service filesystem.
- Redeploys should preserve the database as long as the same persistent disk remains attached.
