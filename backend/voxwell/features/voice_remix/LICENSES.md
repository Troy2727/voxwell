# Models used by voice_remix

Voice remix adds no model. It combines two that Voxwell already runs:

| Model | Used for | License record |
|---|---|---|
| Parler-TTS Mini v1 | Speaking the script in the described voice | `../voice_design/LICENSES.md` (Apache-2.0 code and weights) |
| Chatterbox S3Gen and S3 tokenizer (`s3gen.safetensors`) | Re-voicing that take with a blend of the original and described voices | `../tools/LICENSES.md` (MIT code and weights) |

The output keeps Chatterbox's Perth watermark, as the Tools voice conversion does.
