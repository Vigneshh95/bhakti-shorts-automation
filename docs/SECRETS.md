# Keys and sign-ins: where they live, what uses them, how to renew them

No key or sign-in is ever stored in this repository (it is public). On the laptop they are in files
that git ignores (the YouTube ones together in `sign_in_files`, see its README.txt); in the cloud they are GitHub secrets (repository > Settings > Secrets and variables
> Actions). The **Health check** pipeline tests all of them every morning at 02:00 IST and emails you
(a red run) with what to do when one stops working. A test (`tests/test_no_secrets.py`) fails if a
key ever gets into a tracked file.

| What | Laptop | GitHub secret | Used by | Expires? | How to renew |
|---|---|---|---|---|---|
| YouTube sign-in, BrahmaNadagam | `sign_in_files/1_BrahmaNadagam_YouTube_sign_in.json` | `YT_TOKEN_JSON` | Short - Murugan / Mahaperiyava / Krishna, Story - Grown-ups | No (app "In production" since 2026-10-13); dies if you change your Google password or remove the app's access | `youtube_sign_in.bat`, then paste the file into the secret |
| YouTube sign-in, kids' channel | `sign_in_files/2_Kids_channel_YouTube_sign_in.json` | `YT_TOKEN_KIDS_JSON` | Short - Kids channel, Story - Kids | Same as above (the first one, made before publishing, expires ~2026-10-20) | `story_kids_sign_in.bat`, choose the kids' channel, paste the file into the secret |
| Google app (OAuth client) | `sign_in_files/3_Google_app_client_secret.json` | `YT_CLIENT_SECRET_JSON` | every upload | No | Google Cloud Console > Murugan-Uploader > Clients |
| Gemini key, Shorts | `.env` GEMINI_API_KEY | `GEMINI_API_KEY` | all Shorts | No | aistudio.google.com > API keys |
| Gemini key, stories | `.env` GEMINI_API_KEY_STORIES | `GEMINI_API_KEY_STORIES` | stories (writing, voices, checks) | No | aistudio.google.com (the second project) |
| Hugging Face token | `.env` HF_TOKEN | `HF_TOKEN` | Mahaperiyava voice | No | huggingface.co/settings/tokens (read) |
| Kaggle token | `~/.kaggle/access_token` | `KAGGLE_ACCESS_TOKEN` | talking faces, pictures | No | kaggle.com/settings > API > Create new token |
| Private files token | (not needed) | `ASSETS_TOKEN` | every pipeline (pictures, history) | If you set an expiry date: the health check warns 14 days before | github.com/settings/tokens, access to the private files repository only |

## If a key may have leaked

1. Make a new one at the provider (links above) and revoke the old one there.
2. Put the new one in `.env` on the laptop and in the GitHub secret.
3. Run the Health check by hand (Actions > Health check > Run workflow) to confirm.

Never paste a key or token into a chat, an issue, a commit or a screenshot.
