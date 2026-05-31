# Frontend

React + Vite web app for the 문진톡톡 MVP.

## Screens

- `/staff`: staff reception
- `/patient/:sessionId`: patient tablet intake
- `/doctor/queue`: doctor queue
- `/doctor/:sessionId`: doctor onepaper
- `/guide/:sessionId`: patient guide

## Setup

```powershell
npm install
Copy-Item .env.example .env.local
```

`VITE_API_BASE_URL` controls backend mode:

```text
VITE_API_BASE_URL=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
```

Leave it empty for UI-only mock mode.

## Development

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

## Build

```powershell
npm run build
```

The production bundle is generated in `dist/`. Do not commit `dist/`.

## Notes

- Microphone access requires HTTPS or localhost.
- Amplify deployments must expose the app as a single-page app, so direct routes should rewrite to `/index.html`.
