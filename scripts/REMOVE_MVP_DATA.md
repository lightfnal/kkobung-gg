# Remove historical MVP data

After deploying the feature-removal code, run this once from the repository root in the Render Shell:

```sh
python scripts/remove_mvp_data.py
```

The script clears only columns whose names contain `mvp` in the database and removes MVP keys from legacy JSON files. It then saves a backup containing the cleaned data under the configured data directory's `backups/` folder. Match rows, player rows, wins, losses, and ratings are retained.
