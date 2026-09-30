#!/usr/bin/env python3
"""夜航 · 助眠音景离线合成器

生成「无缝循环」的助眠音景音频文件，供 <audio loop> 播放使用
（Web Audio 实时合成在 iOS 后台/锁屏会被系统挂起，必须换成媒体元素播放）。

无缝的关键：噪声在频域塑形后做逆 FFT，得到的信号以循环长度为周期，
循环点天然连续，不需要交叉淡化，也不会有 MP3/AAC 那样的编码器空隙。

用法：
    python3 tools/make_loops.py            # 生成全部
    python3 tools/make_loops.py rain       # 只生成某一条
"""
import sys
import wave
import numpy as np
from pathlib import Path

SR = 22050          # 采样率：音景能量都在 2kHz 以下，22.05k 足够且体积减半
DUR = 60.0          # 循环长度（秒）
OUT_DIR = Path(__file__).resolve().parent.parent / "audio"
SEED = 20260930     # 固定随机种子，保证可复现


def spectral_noise(n, shape, seed):
    """在频域按 shape(f) 塑形白噪声，返回时域实信号（周期为 n，天然可无缝循环）。"""
    rng = np.random.default_rng(seed)
    # 频域白噪：实信号要求共轭对称，用 rfft 的规模构造更省事
    spec = rng.normal(0, 1, n // 2 + 1) + 1j * rng.normal(0, 1, n // 2 + 1)
    freq = np.fft.rfftfreq(n, 1 / SR)
    spec *= shape(freq)
    spec[0] = 0                      # 去掉直流，避免偏移
    x = np.fft.irfft(spec, n)
    return x


def hp1(f, fc):
    """一阶高通幅频响应"""
    return f / np.sqrt(f ** 2 + fc ** 2)


def lp1(f, fc):
    """一阶低通幅频响应"""
    return fc / np.sqrt(f ** 2 + fc ** 2)


def rain():
    """雨声：宽带噪声，160Hz 高通去掉隆隆声，1500Hz 低通做两次（12dB/oct）让雨丝柔和。"""
    n = int(SR * DUR)
    x = spectral_noise(n, lambda f: hp1(f, 160) * lp1(f, 1500) ** 2, SEED)
    # 缓慢起伏：60 秒走 2 个周期 → 周期性不被破坏
    t = np.arange(n) / SR
    x *= 1.0 + 0.15 * np.sin(2 * np.pi * 2 * t / DUR)
    return x


def ocean():
    """海浪：更低的低通（布朗噪声感）+ 约 20 秒一波的涨落（60 秒 3 个整周期，循环点不跳）。"""
    n = int(SR * DUR)
    x = spectral_noise(n, lambda f: hp1(f, 40) * lp1(f, 520) ** 2, SEED + 1)
    t = np.arange(n) / SR
    x *= 0.62 + 0.38 * np.sin(2 * np.pi * 3 * t / DUR)
    return x


def pink():
    """粉红噪声：能量按 1/f 分布（每倍频程 -3dB），比白噪更"厚"、更适合掩蔽环境噪。

    低频兜底：把 0~1Hz 并入 1Hz，避开 1/sqrt(f) 在直流处的奇异点（spec[0] 随后会被置零）。
    """
    n = int(SR * DUR)
    x = spectral_noise(n, lambda f: hp1(f, 30) * (1.0 / np.sqrt(np.maximum(f, 1.0))), SEED + 3)
    return x


# 低频钢琴用的音高：A2 起的五声音阶，只取低音区，避免听感"吵"
PENTA = [110.0, 130.81, 146.83, 164.81, 196.0, 220.0, 246.94]


def add_note(x, start_sec, freq, amp):
    """把一个钢琴音环绕累加进 x。

    起音 20ms、指数衰减 tau≈1.3s、总长 6s（尾部已很轻）。
    索引用 (start + i) % n 环绕：靠近循环末尾的音，其尾音会自然接回开头，
    所以 60 秒接缝处依然是连续的（不需要交叉淡化）。
    """
    n = len(x)
    ln = int(6.0 * SR)
    t = np.arange(ln) / SR
    env = (1.0 - np.exp(-t / 0.02)) * np.exp(-t / 1.3)
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2.004 * t)
    idx = (int(start_sec * SR) + np.arange(ln)) % n
    x[idx] += amp * env * tone


def piano():
    """低频钢琴：60 秒内散布 14 个左右五声音阶低音，间隔 2.6~5.4 秒，偶尔两音叠置。"""
    n = int(SR * DUR)
    rng = np.random.default_rng(SEED + 2)
    x = np.zeros(n)
    pos = 0.4
    while pos < DUR:
        freq = PENTA[rng.integers(0, len(PENTA))]
        add_note(x, pos, freq, amp=0.5)
        if rng.random() < 0.28:                       # 偶尔叠一个高八度的泛音点缀
            add_note(x, pos + 0.06, freq * 2, amp=0.16)
        pos += rng.uniform(2.6, 5.4)
    return x


def normalise(x, peak=0.85):
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def write_wav(path, x):
    # iOS 只对媒体元素给后台播放权限；WAV 无编码器延迟，循环点最干净
    data = np.clip(x, -1.0, 1.0)
    pcm = (data * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path.stat().st_size


BUILDERS = {"rain": rain, "ocean": ocean, "piano": piano, "pink": pink}


def main():
    names = sys.argv[1:] or list(BUILDERS)
    for name in names:
        if name not in BUILDERS:
            print("未知音景:", name, "可选:", ", ".join(BUILDERS))
            continue
        x = normalise(BUILDERS[name]())
        p = OUT_DIR / f"{name}-loop.wav"
        size = write_wav(p, x)
        print(f"  + {p.name}  {DUR:.0f}s {SR}Hz mono  {size/1024/1024:.2f} MB")


if __name__ == "__main__":
    main()
