# Desktop installers

The **Installers** workflow builds Voxwell for Windows, macOS and Linux and keeps the files as run artifacts for 14 days. It publishes nothing. Run it from the Actions tab, or let it run on a pull request that touches the packaging.

To build on your own computer, for that computer's OS: `cd app && npm ci && npm run dist`. The files land in `app/release/`.

## How it works

The installer holds the app, the backend's source and a pinned copy of [uv](https://docs.astral.sh/uv/) (`app/scripts/fetch-uv.cjs`). It doesn't hold Python or the AI packages. On first launch, a setup screen has uv download them into the user's app data folder, about 11 GB on Windows. It can be closed and carries on later, and needs no Git, Python or terminal.

Model weights still download the first time each feature is used. ffmpeg is not included, because many builds are GPL; dubbing and some tools need it installed separately.

Each build is unsigned until its OS's signing values are set in the repository's **Settings > Secrets and variables > Actions**. Never commit any of them.

## Windows signing: Azure Artifact Signing

Individuals must be in the United States or Canada. Create an Artifact Signing account, an identity validation and a certificate profile in Azure, plus an app registration that may sign with them.

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `AZURE_TENANT_ID` | The directory (tenant) ID |
| Secret | `AZURE_CLIENT_ID` | The app registration's client ID |
| Secret | `AZURE_CLIENT_SECRET` | The app registration's secret |
| Variable | `AZURE_SIGNING_ENDPOINT` | The account's region endpoint, such as `https://eus.codesigning.azure.net` |
| Variable | `AZURE_SIGNING_ACCOUNT` | The signing account's name |
| Variable | `AZURE_SIGNING_PROFILE` | The certificate profile's name |
| Variable | `AZURE_SIGNING_PUBLISHER` | The publisher name exactly as it appears on the certificate |

## macOS signing and notarization: Apple Developer Program

Create a **Developer ID Application** certificate, export it as a `.p12`, and create an app-specific password at appleid.apple.com.

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `MAC_CERTIFICATE_P12_BASE64` | The `.p12` file, base64 encoded |
| Secret | `MAC_CERTIFICATE_PASSWORD` | The `.p12` file's password |
| Secret | `APPLE_ID` | The Apple ID's email |
| Secret | `APPLE_APP_SPECIFIC_PASSWORD` | The app-specific password, not the account password |
| Secret | `APPLE_TEAM_ID` | The 10-character team ID |

## Linux

Linux packages aren't signed.
