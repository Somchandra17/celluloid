# Deploy the same repository on Vercel

The studio is a static application. Importing the repository does not require
the original hosting service, ChatGPT sign-in, an API key, a database or an office
suite on the server. No hosting account IDs are part of the portable release.

## Import and deploy

1. Push the clean release source to your GitHub repository.
2. In Vercel, choose **Add New → Project**, import that repository, and keep the
   project root at the repository root.
3. The included `vercel.json` selects **Other** as the framework, runs `npm ci`
   and `npm run build`, and publishes `dist`. Use a supported Node 22+ build
   environment; Node 24 LTS is a good current choice.
4. Deploy. No environment variables are needed for the browser studio.
5. Under **Project → Settings → Domains**, add the domain or subdomain you want
   for Celluloid and follow Vercel's DNS instructions for your DNS provider.

The build is Node-only. It validates local asset/import references and produces
the downloadable source toolkit. Python, FFmpeg and LibreOffice are not needed
for a Vercel build. Only `dist` is served; Python source is included inside the
intentional source download rather than exposed as an API.

The configuration follows Vercel's documented
[static configuration](https://vercel.com/docs/project-configuration/vercel-json),
[build settings](https://vercel.com/docs/builds/configure-a-build), and
[Node versions](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions).
There is no catchall rewrite: missing JavaScript, fonts and other assets produce
real 404s instead of silently returning the home page.

## What works over your domain

Uploaded browser-supported videos, live webcam preview, recording, JSON import
and export, and animated ODS creation all run on the visitor's device. The site
has no analytics or remote font dependency. Video files are not uploaded to
Vercel. HTTPS plus camera permission are required for webcam capture.

The web studio is not a full office editor. Its preview is a Canvas grid. Real
desktop Calc playback requires the visitor's installed local companion or CLI.

## Pairing a hosted page with local Calc

After installing LibreOffice and Python UNO:

```sh
/usr/bin/python3 native/bridge.py --launch-lo \
  --allow-origin https://your-celluloid-domain.example
```

Replace the example with your exact page origin, with no trailing slash. Pair
the hosted studio with the temporary token printed by the companion. Browser
mixed-content/local-network policy can still prevent HTTPS-to-loopback HTTP
access, even when CORS permits it.

The dependable alternative serves the exact same studio locally:

```sh
/usr/bin/python3 native/bridge.py --launch-lo --web-root dist
```

Open the printed loopback URL and pair there. This uses one origin for the web
page and companion. Do not expose the UNO socket or companion to the Internet.

## Optional FFmpeg service

The Python service under `backend/` is optional and is not a Vercel Function.
Run it locally or on infrastructure intended for bounded video-decoding jobs.
Select its URL in Advanced conversion. That choice sends the selected file to
the service; the user-facing interface states this explicitly.

Configure `CELLULOID_ORIGINS` for the exact web origins that can use it. The
included service is a local prototype without public-user authentication or
quotas. Public multi-user hosting requires those controls and isolated workers.
See [backend setup](../backend/README.md).
