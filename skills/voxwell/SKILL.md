---
name: voxwell
description: Voice work on this computer with the local Voxwell app, through its `voxwell` CLI. Use for text-to-speech (speak, narrate, voiceover, read aloud), transcribing audio or video (subtitles, SRT), isolating a voice from music or noise (remove vocals, karaoke, clean up a recording), cloning or designing a voice, making music or songs, converting a recording to another voice, dubbing a video into another language, or translating text or speech into another language and speaking it.
---

# Voxwell

Voxwell runs every model locally; the `voxwell` CLI drives the running Voxwell server.

1. **Find the command.** `voxwell` if it is on PATH, otherwise `uv run --directory <voxwell>/backend voxwell`. Installing this skill from Voxwell's Integrations page fills in the exact command for this computer.
2. **Check the server.** `voxwell status`. When it reports that Voxwell is not running, start `voxwell serve` as a background process (it keeps running; the first model load takes a while), then check again.
3. **Run the command with `--json`.** `voxwell --help` lists the commands and `voxwell <command> --help` their options; read them instead of guessing flags. With `--json` each command prints one JSON object: output file paths are absolute, and a failure prints `{"error": "..."}` with exit code 1.
4. **Report the files.** Give the user the output paths. Done when every file the user asked for exists.

## Facts --help does not state

- Voices are referenced by saved name (any case) or id; `voxwell voices` lists them. `speak` without `--voice` uses the built-in voice; `dub` without `--voice` clones the original speaker.
- `sound` makes sound effects from a text description (1 to 30 seconds; reuse the printed `seed` to repeat a result). It needs a free Hugging Face token with the Stable Audio Open terms accepted, set on the Voxwell Sound page or as `HF_TOKEN`; if the command says the model is gated, tell the user to do that rather than retrying. Expect minutes per clip on CPU.
- `music` makes a song from a style description plus lyrics (`--lyrics` or `--lyrics-file`, sections marked `[Verse]`, `[Chorus]`), or an instrumental with `--instrumental`; lyrics are required otherwise. The music engine installs once (about 12 GB) from the Music page or with `voxwell music --install`; if the command says it is not installed, ask the user before installing. A 30-second song takes a couple of minutes on CPU, longer for long songs.
- Collections are folders of saved voices (`voxwell collection list|show|create|rename|delete|add|remove`); they only organize voices, so deleting a collection never deletes a voice. Collection names are unique in any case.
- Languages are ISO 639-1 codes. Speech, cloning and dubbing cover about 20 common languages (Japanese is not one of them) and reject others with an error. Transcription detects the language when `--language` is left out.
- `chat` sends one message to a voice agent saved in the app (its instructions, tools and voice are set on the Voice agents page) and prints the reply; it does not remember earlier calls. Talking to an agent by voice is only in the app.
- `translate` speaks the translation of text (`--from`, default en) or of the speech in `--file` (its language is detected). Its target languages are the speech languages above. Live translation, speaking and hearing turn by turn, is only in the app.
- Commands take local file paths and write next to the input (`isolate`) or into the current folder, unless `-o` says otherwise.
- `effects` post-processes an existing recording (`--reverb`, `--distance`, `--noise`, `--pan`, each a number; 0 leaves it off). A non-zero `--pan` makes the WAV stereo and reverb adds a tail, so the file gets slightly longer. The same settings are available as optional `effects` on the app's voice cloning and Stories requests.
- `pronounce add WORD RESPELLING` teaches every voice a word (`Nguyen` -> `win`); matches are whole-word and case-insensitive unless `--case-sensitive` or `--partial` says otherwise, and it applies to all speech, per `--language`. Write the respelling as plain text the model reads aloud; check it with `speak`.
- `isolate` accepts up to 10 minutes of audio; `speak` up to 4096 characters per call, so split longer texts and speak each part.
- `transcribe --speakers` (and `dub --speakers`) label who speaks: "Speaker 1:" in TXT and SRT, `<v Speaker 1>` in VTT; `--num-speakers N` fixes the count when it is known. Off by default. It downloads two small models on first use. When labelling fails the transcript is still returned, with a note saying why. A dub with `--speakers` clones each speaker's own voice unless `--voice` names a saved voice, which then speaks every line.
- `align AUDIO SCRIPT.txt` times a script you already have against its recording and writes SRT (default) or VTT; use it instead of `transcribe` when the exact wording is known. It reports how many script words matched the audio; when none did, the times are only estimates, so check the script and `--language`. `--max-chars` and `--max-seconds` shape the subtitles.
- `edit` cleans up transcript text (a file, or `-` for stdin) with a local AI model: `--preset filler|punctuation|formal|concise`, or `--instruction "..."`. It edits chunk by chunk and keeps the original wording of any chunk the model garbles, so review the result; it prints the text, or saves it with `-o`.
- Speed is CPU-bound without a GPU: a minute of audio takes tens of seconds to isolate or transcribe, and a dub several minutes. Long commands block until finished; let them run.
- Each model downloads on its first use, so the first call of a command is the slowest.
