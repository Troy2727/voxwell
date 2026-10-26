"""Ready-made voices. Each is a written description that voice design turns into a voice, so the
gallery ships no recordings of real people: every voice is generated on this machine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    category: str
    description: str
    sample: str


PRESETS = [
    Preset("calm-narrator", "Calm Narrator", "Narration",
           "A calm, warm male voice with a deep tone, speaking slowly and clearly, very close to the microphone.",
           "It was late in the evening when the first letter arrived, and nothing would be the same again."),
    Preset("bright-storyteller", "Bright Storyteller", "Narration",
           "A bright, expressive female voice with a gentle smile, moderate pace, clear studio recording.",
           "Once upon a time, in a village by the sea, there lived a girl who could talk to the wind."),
    Preset("documentary", "Documentary", "Narration",
           "A mature male voice, authoritative and measured, slightly slow, rich and resonant, clean recording.",
           "Every year, millions of birds cross this desert, guided by the stars and the shape of the land."),
    Preset("audiobook-soft", "Soft Reader", "Narration",
           "A soft, quiet female voice, slow and soothing, very clear and intimate recording.",
           "She closed the book, turned off the lamp, and listened to the rain on the window."),
    Preset("upbeat-host", "Upbeat Host", "Media",
           "An energetic young male voice, fast and upbeat, enthusiastic and friendly, clear recording.",
           "Welcome back to the show! Today we have something really exciting to share with you."),
    Preset("news-anchor", "News Anchor", "Media",
           "A confident female voice, neutral and professional, moderate pace, crisp studio quality.",
           "Good evening. Here are tonight's top stories from around the world."),
    Preset("podcast-friend", "Podcast Friend", "Media",
           "A relaxed, casual male voice, conversational and warm, moderate pace, natural recording.",
           "So I was thinking about this the other day, and honestly, it changed how I see the whole thing."),
    Preset("ad-voice", "Ad Voice", "Media",
           "A smooth, polished female voice, persuasive and upbeat, slightly fast, very clear recording.",
           "Fresh, simple and ready in minutes. Try it today and taste the difference."),
    Preset("wise-elder", "Wise Elder", "Characters",
           "An old man with a slightly raspy, low voice, speaking slowly and thoughtfully.",
           "Patience, young one. The river does not rush, and yet it always reaches the sea."),
    Preset("young-hero", "Young Hero", "Characters",
           "A young female voice, determined and brave, slightly fast, clear and strong.",
           "We cannot wait any longer. If no one else will go, then I will."),
    Preset("gentle-guide", "Gentle Guide", "Assistants",
           "A friendly female voice, gentle and patient, moderate pace, very clear recording.",
           "Take a deep breath. When you're ready, press the button and we'll begin together."),
    Preset("clear-assistant", "Clear Assistant", "Assistants",
           "A neutral male voice, clear and precise, moderate pace, close microphone, no background noise.",
           "Your meeting starts in ten minutes. Would you like me to read the agenda?"),
]

BY_ID = {p.id: p for p in PRESETS}
