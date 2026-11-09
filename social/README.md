# Social Hub

Social Hub is available to active, verified LPU student accounts. It uses the
project's existing MongoDB collections and Cloudinary upload configuration.

## Deployment

The Docker image runs Django's production deployment checks, applies Django
migrations, then serves HTTP and WebSockets through Daphne. Production startup
requires a strong `SECRET_KEY`, `DEBUG=False`, a specific `ALLOWED_HOSTS` list,
and valid HTTPS settings. Configure `CSRF_TRUSTED_ORIGINS` for the public site.
The deployment check fails startup if Django reports any deployment warning.
See `.env.example` for the complete variable list; provide real values through
the hosting provider's secret manager, never in the image or repository.

The MongoDB health endpoint is `/core/health/`. Before first use, take a
database backup and run `python manage.py init_mongo_indexes` as a one-off
deployment step. Index creation now reports failures and is not exposed as a
public HTTP endpoint.

Set `REDIS_URL` to a reachable Redis service. Django Channels uses Redis to
deliver live chat and call notifications between application workers. Deploy
the ASGI app through Daphne and allow WebSocket upgrades at the hosting proxy.
If TLS terminates at a trusted proxy, set `TRUST_X_FORWARDED_PROTO=True` only
when the proxy sets and overwrites `X-Forwarded-Proto`.

The project currently uses SQLite for Django sessions and admin data. Use a
persistent disk and a single app instance if retaining SQLite. For multiple
instances or production traffic, migrate this Django database to a shared
database before scaling; all instances must share the same session store.
MongoDB contains the application data and should use a production replica set,
TLS, authentication, and network allow-listing.

Run `python manage.py collectstatic --noinput` when building the deployment
image. Configure a health check against `/core/health/` and test the public
site's HTTPS and WebSocket upgrade paths before opening traffic.

Set `GIPHY_API_KEY` in the application environment to enable GIF search in chat.
Without that key, text and image/video sharing still work, and the GIF picker
shows a configuration message.

Video calls use the configured `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and
`LIVEKIT_API_SECRET`. Set those values to enable one-to-one and group video
calls. Call participants must grant camera and microphone access in their
browsers.

Student tagging suggests verified matches by registration-number prefix and
shows each match's name, registration number, profile photo, department, and
year. Email addresses are not exposed in suggestions.

Posts can be shared directly to a selected verified student's DM. This creates
or reuses the private conversation, sends a post preview, and opens that chat;
the recipient can follow the preview to the original post.

Cloudinary is needed for uploaded profile photos and Social Hub media; direct
HTTPS media links do not replace safe storage for user uploads. LiveKit is
required for video calls. GIPHY and Gemini are optional integrations.
