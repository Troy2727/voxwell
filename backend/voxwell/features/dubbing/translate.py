"""Text translation with facebook/m2m100_418M (MIT code and weights), loaded lazily."""

from voxwell.features.dubbing.ffmpeg import DubbingError

# Languages supported by M2M100 (ISO 639-1 codes as used by its tokenizer).
LANGUAGES = frozenset(
    "af am ar ast az ba be bg bn br bs ca ceb cs cy da de el en es et fa ff fi fr fy ga gd gl gu "
    "ha he hi hr ht hu hy id ig ilo is it ja jv ka kk km kn ko lb lg ln lo lt lv mg mk ml mn mr "
    "ms my ne nl no ns oc or pa pl ps pt ro ru sd si sk sl sq sr ss su sv sw ta th tl tn tr uk "
    "ur uz vi wo xh yi yo zh zu".split()
)
MODEL_ID = "facebook/m2m100_418M"
_cache: dict = {}


def _load():
    if not _cache:
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

        device = "cuda" if torch.cuda.is_available() else (
            "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
        )
        _cache["tok"] = M2M100Tokenizer.from_pretrained(MODEL_ID)
        _cache["model"] = M2M100ForConditionalGeneration.from_pretrained(MODEL_ID).to(device).eval()
        _cache["device"] = device
    return _cache["tok"], _cache["model"], _cache["device"]


def translate(texts: list[str], source: str, target: str) -> list[str]:
    """Translate each text from `source` to `target` (ISO 639-1)."""
    if source == target:
        return list(texts)
    for code in (source, target):
        if code not in LANGUAGES:
            raise DubbingError(f"Translation does not support language '{code}'.")
    import torch

    tok, model, device = _load()
    tok.src_lang = source
    out: list[str] = []
    for text in texts:
        batch = tok(text, return_tensors="pt").to(device)
        with torch.no_grad():
            ids = model.generate(**batch, forced_bos_token_id=tok.get_lang_id(target), max_new_tokens=256)
        out.append(tok.batch_decode(ids, skip_special_tokens=True)[0])
    return out
