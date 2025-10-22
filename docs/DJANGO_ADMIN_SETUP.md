# Django Admin Setup Guide

This guide covers essential Django admin configuration required for the Maple Key Music Academy application to function properly.

## Required Setup After Database Migration

After running `python manage.py migrate` for the first time, you must configure the following in Django admin:

### 1. Create Superuser (if not already done)

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 2. Configure Django Site (Required for OAuth)

**Why:** The application uses `SITE_ID = 2` in settings.py for Django Allauth. You must create this site in the database.

**Steps:**

1. Log into Django admin: `http://localhost:8000/admin/` (or your production URL)

2. Navigate to **Sites** section (under SITES)

3. Click **Add Site**

4. Create a site with ID=2:
   - **Domain name:**
     - Development: `localhost:8000`
     - Production: `api.maplekeymusic.com`
   - **Display name:** `Maple Key Music Academy`
   - Click **Save**

**Important:** The Site ID must be 2 to match the `SITE_ID` setting in `settings.py`.

### 3. Configure Google OAuth Social Application

**Why:** The application uses Google OAuth for authentication. You must configure the OAuth credentials in Django admin.

**Prerequisites:**
- Have Google OAuth credentials (Client ID and Client Secret) from Google Cloud Console
- Ensure these credentials are also set in your environment variables

**Steps:**

1. In Django admin, navigate to **Social applications** (under SOCIAL ACCOUNTS)

2. Click **Add social application**

3. Fill in the form:
   - **Provider:** Select `Google`
   - **Name:** `Google OAuth` (or any descriptive name)
   - **Client id:** Your Google OAuth Client ID
   - **Secret key:** Your Google OAuth Client Secret
   - **Sites:** Select the site you created (ID=2)
   - Click **Save**

**Development vs Production:**
- If using the same Google OAuth app for both environments, add both redirect URIs in Google Cloud Console:
  - `http://localhost:8000/api/auth/google/callback/`
  - `https://api.maplekeymusic.com/api/auth/google/callback/`

### 4. Verify Configuration

After setup, verify everything works:

1. **Test OAuth Flow:**
   - Visit your frontend: `http://localhost:5173/login` (dev) or `https://maplekeymusic.com/login` (prod)
   - Click "Continue with Google"
   - Should redirect to Google, then back to your application

2. **Check for Errors:**
   - If you see "Google OAuth app not configured" error, check step 3
   - If you see site-related errors, check step 2

## Troubleshooting

### Error: "Google OAuth app not configured"
**Cause:** No SocialApp for Google provider exists in database
**Solution:** Complete step 3 above

### Error: Site matching query does not exist
**Cause:** Site with ID=2 doesn't exist in database
**Solution:** Complete step 2 above

### Error: Redirect URI mismatch
**Cause:** The redirect URI in your Google OAuth app doesn't match the callback URL
**Solution:** In Google Cloud Console, add the correct redirect URI:
- Dev: `http://localhost:8000/api/auth/google/callback/`
- Prod: `https://api.maplekeymusic.com/api/auth/google/callback/`

### Error: Email not authorized
**Cause:** User's email is not in the `ALLOWED_EMAILS` environment variable
**Solution:** Add the email to `ALLOWED_EMAILS` in your `.env` file (comma-separated)

## Production Deployment Notes

When deploying to production for the first time:

1. SSH into your production server
2. Run migrations: `docker exec maple-key-backend python manage.py migrate`
3. Create superuser: `docker exec -it maple-key-backend python manage.py createsuperuser`
4. Access admin via: `https://api.maplekeymusic.com/admin/`
5. Complete steps 2 and 3 above with production values

## Database Backup Recommendation

After completing this setup, consider backing up your database to preserve these configurations:

```bash
# Development
docker exec maple_key_db pg_dump -U maple_key_user maple_key_dev > backup_after_setup.sql

# Production
docker exec postgres pg_dump -U [your_prod_user] [your_prod_db] > backup_after_setup.sql
```

This backup will include your Site and SocialApp configurations, making it easier to restore if needed.
