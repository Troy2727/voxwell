# UI components: licenses

The files in this folder are copied into Voxwell (not installed as packages), as both projects intend. Both are MIT, like Voxwell.

| Files | Source | License |
|---|---|---|
| `alert`, `alert-dialog`, `badge`, `button`, `card`, `checkbox`, `command`, `dialog`, `dropdown-menu`, `input`, `label`, `popover`, `progress`, `select`, `separator`, `sheet`, `sidebar`, `skeleton`, `slider`, `sonner`, `tabs`, `textarea`, `tooltip` (and `../../hooks/use-mobile.ts`) | [shadcn/ui](https://github.com/shadcn-ui/ui), added with `npx shadcn add` | MIT, Copyright (c) 2023 shadcn |
| `audio-player`, `live-waveform`, `mic-selector`, `scrub-bar`, `transcript-viewer`, `voice-picker`, `waveform` (and `../../hooks/use-transcript-viewer.ts`) | [ElevenLabs UI](https://github.com/elevenlabs/ui) | MIT, Copyright (c) 2025 Eleven Labs Inc. |

Changes made in Voxwell (marked `Voxwell:` in the code):

- Imports point at this folder instead of the upstream registry paths; `audio-player` uses the `radix-ui` package like the shadcn files.
- `voice-picker` takes Voxwell's own voice shape instead of the ElevenLabs SDK type, and shows a brand-colored disc instead of the three.js `Orb`, so neither the cloud SDK nor WebGL is needed.
- `use-transcript-viewer` defines the character-alignment type locally instead of importing it from the ElevenLabs SDK.
- `waveform`: `AudioScrubber` passes its `height` to the canvas (upstream always drew it 128px tall).
- `sonner` reads the theme from `@/lib/theme` instead of `next-themes`.

No ElevenLabs service is called: these are UI components only, and all audio comes from the local Voxwell backend.

## The MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
