"""The HTDemucs source-separation network, written for Voxwell to run Meta's published `htdemucs`
weights (see LICENSES.md). Model: "Hybrid Transformers for Music Source Separation", Rouard, Massa
and Défossez, ICASSP 2023.

Inference only, and only the configuration those weights use: stereo 44.1 kHz in, four stems out,
the spectrogram branch predicting complex values directly (no Wiener filtering), 7.8 s windows.
Submodule and parameter names match the checkpoint's keys, so its state dict loads as is.

Two branches run side by side: one convolves over the spectrogram's frequency axis, the other
over the raw waveform. Both shrink to the same time resolution, exchange information through a
cross-attention transformer, and are decoded back; the final stems are the sum of both branches.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

SOURCES = ("drums", "bass", "other", "vocals")
SAMPLE_RATE = 44100
SEGMENT = 343980  # samples per pass: the 7.8 s windows the weights were trained on
NFFT = 4096
HOP = NFFT // 4
WIDTHS = (48, 96, 192, 384)  # channels after each encoder layer
DIM = 512  # transformer width
FREQ_EMB_WEIGHT = 0.2


class LayerScale(nn.Module):
    """Learned per-channel scale on a residual branch."""

    def __init__(self, channels: int, channel_last: bool = False):
        super().__init__()
        self.scale = nn.Parameter(torch.zeros(channels))
        self.channel_last = channel_last

    def forward(self, x):
        return x * self.scale if self.channel_last else x * self.scale[:, None]


class Residual(nn.Module):
    """Two dilated-convolution residual blocks over time, on a channel-compressed (1/8) signal."""

    def __init__(self, channels: int, depth: int = 2, compress: int = 8):
        super().__init__()
        hidden = channels // compress
        self.layers = nn.ModuleList(
            nn.Sequential(
                nn.Conv1d(channels, hidden, 3, dilation=2**d, padding=2**d),
                nn.GroupNorm(1, hidden),
                nn.GELU(),
                nn.Conv1d(hidden, 2 * channels, 1),
                nn.GroupNorm(1, 2 * channels),
                nn.GLU(1),
                LayerScale(channels),
            )
            for d in range(depth)
        )

    def forward(self, x):
        for layer in self.layers:
            x = x + layer(x)
        return x


def _per_frequency(module: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """Apply a (B, C, T) module to every frequency row of a (B, C, F, T) tensor."""
    b, c, f, t = x.shape
    y = module(x.permute(0, 2, 1, 3).reshape(b * f, c, t))
    return y.view(b, f, c, t).permute(0, 2, 1, 3)


class Encode(nn.Module):
    """Downsample by 4 (over frequency, or over time for the waveform branch), then refine."""

    def __init__(self, chin: int, chout: int, freq: bool):
        super().__init__()
        self.freq = freq
        if freq:
            self.conv = nn.Conv2d(chin, chout, (8, 1), (4, 1), (2, 0))
            self.rewrite = nn.Conv2d(chout, 2 * chout, 1)
        else:
            self.conv = nn.Conv1d(chin, chout, 8, 4, 2)
            self.rewrite = nn.Conv1d(chout, 2 * chout, 1)
        self.dconv = Residual(chout)

    def forward(self, x):
        if not self.freq and x.shape[-1] % 4:
            x = F.pad(x, (0, 4 - x.shape[-1] % 4))
        y = F.gelu(self.conv(x))
        y = _per_frequency(self.dconv, y) if self.freq else self.dconv(y)
        return F.glu(self.rewrite(y), dim=1)


class Decode(nn.Module):
    """Mirror of Encode: add the skip connection, refine, then upsample by 4."""

    def __init__(self, chin: int, chout: int, freq: bool, last: bool):
        super().__init__()
        self.freq = freq
        self.last = last
        if freq:
            self.rewrite = nn.Conv2d(chin, 2 * chin, 3, 1, 1)
            self.conv_tr = nn.ConvTranspose2d(chin, chout, (8, 1), (4, 1))
        else:
            self.rewrite = nn.Conv1d(chin, 2 * chin, 3, 1, 1)
            self.conv_tr = nn.ConvTranspose1d(chin, chout, 8, 4)
        self.dconv = Residual(chin)

    def forward(self, x, skip, length: int):
        y = F.glu(self.rewrite(x + skip), dim=1)
        y = _per_frequency(self.dconv, y) if self.freq else self.dconv(y)
        z = self.conv_tr(y)
        z = z[..., 2:-2, :] if self.freq else z[..., 2 : 2 + length]
        return z if self.last else F.gelu(z)


class FrequencyEmbedding(nn.Module):
    """Learned embedding of each frequency row, added after the first encoder layer."""

    def __init__(self, rows: int, channels: int, scale: float = 10.0):
        super().__init__()
        self.embedding = nn.Embedding(rows, channels)
        self.scale = scale

    def forward(self, rows):
        return self.embedding(rows) * self.scale


class GroupNormLast(nn.GroupNorm):
    """GroupNorm on a (B, T, C) tensor."""

    def forward(self, x):
        return super().forward(x.transpose(1, 2)).transpose(1, 2)


class _Block(nn.Module):
    """Pre-norm transformer block; `attend` is self-attention or cross-attention."""

    def __init__(self):
        super().__init__()
        self.linear1 = nn.Linear(DIM, 4 * DIM)
        self.linear2 = nn.Linear(4 * DIM, DIM)
        self.norm1 = nn.LayerNorm(DIM)
        self.norm2 = nn.LayerNorm(DIM)
        self.norm_out = GroupNormLast(1, DIM)
        self.gamma_1 = LayerScale(DIM, channel_last=True)
        self.gamma_2 = LayerScale(DIM, channel_last=True)

    def _feed_forward(self, x):
        return self.linear2(F.gelu(self.linear1(x)))


class SelfAttentionBlock(_Block):
    def __init__(self, heads: int = 8):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(DIM, heads, batch_first=True)

    def forward(self, x):
        h = self.norm1(x)
        x = x + self.gamma_1(self.self_attn(h, h, h, need_weights=False)[0])
        x = x + self.gamma_2(self._feed_forward(self.norm2(x)))
        return self.norm_out(x)


class CrossAttentionBlock(_Block):
    def __init__(self, heads: int = 8):
        super().__init__()
        self.cross_attn = nn.MultiheadAttention(DIM, heads, batch_first=True)
        self.norm3 = nn.LayerNorm(DIM)

    def forward(self, x, other):
        k = self.norm2(other)
        x = x + self.gamma_1(self.cross_attn(self.norm1(x), k, k, need_weights=False)[0])
        x = x + self.gamma_2(self._feed_forward(self.norm3(x)))
        return self.norm_out(x)


def _sin_embedding(length: int, dim: int, device, max_period: float = 10000.0) -> torch.Tensor:
    """(length, dim) cosine/sine position embedding."""
    pos = torch.arange(length, device=device).view(-1, 1)
    half = dim // 2
    phase = pos / (max_period ** (torch.arange(half, device=device).view(1, -1) / (half - 1)))
    return torch.cat([torch.cos(phase), torch.sin(phase)], dim=-1)


def _sin_embedding_2d(dim: int, height: int, width: int, device, max_period: float = 10000.0) -> torch.Tensor:
    """(dim, height, width) embedding: the first half of the channels encodes the column (time),
    the second half the row (frequency), each as interleaved sine/cosine pairs."""
    half = dim // 2
    div = torch.exp(torch.arange(0.0, half, 2) * -(math.log(max_period) / half))
    cols = torch.arange(0.0, width).unsqueeze(1) * div  # (width, half/2)
    rows = torch.arange(0.0, height).unsqueeze(1) * div  # (height, half/2)
    pe = torch.zeros(dim, height, width)
    pe[0:half:2] = torch.sin(cols).t()[:, None, :].expand(-1, height, -1)
    pe[1:half:2] = torch.cos(cols).t()[:, None, :].expand(-1, height, -1)
    pe[half::2] = torch.sin(rows).t()[:, :, None].expand(-1, -1, width)
    pe[half + 1 :: 2] = torch.cos(rows).t()[:, :, None].expand(-1, -1, width)
    return pe.to(device)


class CrossTransformer(nn.Module):
    """Five layers per branch, alternating self-attention and cross-attention between branches."""

    def __init__(self, layers: int = 5):
        super().__init__()
        self.norm_in = nn.LayerNorm(DIM)
        self.norm_in_t = nn.LayerNorm(DIM)
        self.layers = nn.ModuleList(SelfAttentionBlock() if i % 2 == 0 else CrossAttentionBlock() for i in range(layers))
        self.layers_t = nn.ModuleList(SelfAttentionBlock() if i % 2 == 0 else CrossAttentionBlock() for i in range(layers))

    def forward(self, x, xt):
        b, c, f, t = x.shape
        pos = _sin_embedding_2d(c, f, t, x.device)  # (c, f, t)
        x = x.permute(0, 3, 2, 1).reshape(b, t * f, c)  # one token per (time, frequency) cell
        x = self.norm_in(x) + pos.permute(2, 1, 0).reshape(1, t * f, c)
        xt = xt.transpose(1, 2)  # one token per time step
        xt = self.norm_in_t(xt) + _sin_embedding(xt.shape[1], c, x.device)[None]
        for spec_layer, wave_layer in zip(self.layers, self.layers_t):
            if isinstance(spec_layer, SelfAttentionBlock):
                x, xt = spec_layer(x), wave_layer(xt)
            else:
                x, xt = spec_layer(x, xt), wave_layer(xt, x)
        x = x.reshape(b, t, f, c).permute(0, 3, 2, 1)
        return x, xt.transpose(1, 2)


def _stft(x: torch.Tensor) -> torch.Tensor:
    *other, length = x.shape
    device = x.device
    if device.type == "mps":  # no complex numbers on MPS
        x = x.cpu()
    z = torch.stft(
        x.reshape(-1, length), NFFT, HOP, window=torch.hann_window(NFFT).to(x), win_length=NFFT,
        normalized=True, center=True, return_complex=True, pad_mode="reflect",
    )
    return z.view(*other, *z.shape[-2:])


def _istft(z: torch.Tensor, length: int) -> torch.Tensor:
    *other, freqs, frames = z.shape
    x = torch.istft(
        z.reshape(-1, freqs, frames), NFFT, HOP, window=torch.hann_window(NFFT).to(z.real), win_length=NFFT,
        normalized=True, length=length, center=True,
    )
    return x.view(*other, length)


class HTDemucs(nn.Module):
    """Input (B, 2, SEGMENT) waveform; output (B, 4, 2, SEGMENT), one stereo track per SOURCES."""

    def __init__(self):
        super().__init__()
        stems = len(SOURCES)
        self.encoder = nn.ModuleList()  # spectrogram branch; 2 stereo channels x (real, imaginary)
        self.tencoder = nn.ModuleList()  # waveform branch
        ins = (4,) + WIDTHS[:-1]
        ins_t = (2,) + WIDTHS[:-1]
        for chin, chin_t, chout in zip(ins, ins_t, WIDTHS):
            self.encoder.append(Encode(chin, chout, freq=True))
            self.tencoder.append(Encode(chin_t, chout, freq=False))
        outs = (stems * 4,) + WIDTHS[:-1]
        outs_t = (stems * 2,) + WIDTHS[:-1]
        self.decoder = nn.ModuleList(Decode(WIDTHS[i], outs[i], True, last=i == 0) for i in reversed(range(len(WIDTHS))))
        self.tdecoder = nn.ModuleList(Decode(WIDTHS[i], outs_t[i], False, last=i == 0) for i in reversed(range(len(WIDTHS))))
        self.freq_emb = FrequencyEmbedding(NFFT // 2 // 4, WIDTHS[0])
        self.channel_upsampler = nn.Conv1d(WIDTHS[-1], DIM, 1)
        self.channel_downsampler = nn.Conv1d(DIM, WIDTHS[-1], 1)
        self.channel_upsampler_t = nn.Conv1d(WIDTHS[-1], DIM, 1)
        self.channel_downsampler_t = nn.Conv1d(DIM, WIDTHS[-1], 1)
        self.crosstransformer = CrossTransformer()

    def _spectrogram(self, mix):
        # Pad so the frame count is exactly length / HOP, which keeps both branches aligned.
        frames = math.ceil(mix.shape[-1] / HOP)
        pad = HOP // 2 * 3
        x = F.pad(mix, (pad, pad + frames * HOP - mix.shape[-1]), mode="reflect")
        return _stft(x)[..., :-1, 2 : 2 + frames]

    def _waveform(self, z, length):
        z = F.pad(F.pad(z, (0, 0, 0, 1)), (2, 2))
        pad = HOP // 2 * 3
        x = _istft(z, HOP * math.ceil(length / HOP) + 2 * pad)
        return x[..., pad : pad + length]

    def forward(self, mix):
        b, _, length = mix.shape
        stems = len(SOURCES)
        z = self._spectrogram(mix)  # complex, so it stays on the CPU when running on MPS
        _, _, freqs, frames = z.shape
        x = torch.view_as_real(z).permute(0, 1, 4, 2, 3).reshape(b, -1, freqs, frames).to(mix.device)
        mean, std = x.mean(dim=(1, 2, 3), keepdim=True), x.std(dim=(1, 2, 3), keepdim=True)
        x = (x - mean) / (1e-5 + std)
        mean_t, std_t = mix.mean(dim=(1, 2), keepdim=True), mix.std(dim=(1, 2), keepdim=True)
        xt = (mix - mean_t) / (1e-5 + std_t)

        skips, skips_t, lengths_t = [], [], []
        for i, (encode, encode_t) in enumerate(zip(self.encoder, self.tencoder)):
            lengths_t.append(xt.shape[-1])
            xt = encode_t(xt)
            x = encode(x)
            if i == 0:
                rows = torch.arange(x.shape[-2], device=x.device)
                x = x + FREQ_EMB_WEIGHT * self.freq_emb(rows).t()[None, :, :, None]
            skips.append(x)
            skips_t.append(xt)

        _, c, f, t = x.shape
        x = self.channel_upsampler(x.reshape(b, c, f * t)).view(b, -1, f, t)
        x, xt = self.crosstransformer(x, self.channel_upsampler_t(xt))
        x = self.channel_downsampler(x.reshape(b, -1, f * t)).view(b, c, f, t)
        xt = self.channel_downsampler_t(xt)

        for decode, decode_t in zip(self.decoder, self.tdecoder):
            x = decode(x, skips.pop(), 0)
            xt = decode_t(xt, skips_t.pop(), lengths_t.pop())

        # The spectrogram branch predicts each stem's complex spectrogram as (real, imaginary) channels.
        x = x.view(b, stems, -1, freqs, frames) * std[:, None] + mean[:, None]
        if x.device.type == "mps":
            x = x.cpu()
        spec = torch.view_as_complex(x.view(b, stems, -1, 2, freqs, frames).permute(0, 1, 2, 4, 5, 3).contiguous())
        wave = self._waveform(spec, length).to(mix.device)
        xt = xt.view(b, stems, -1, length) * std_t[:, None] + mean_t[:, None]
        return xt + wave
