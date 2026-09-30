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
    """海浪：更低的低通（布朗噪声感）+ 约 18 秒一波的涨落（60 秒 3.33 波不整周期，这里用 3 波）。"""
    n = int(SR * DUR)
    x = spectral_noise(n, lambda f: hp1(f, 40) * lp1(f, 520) ** 2, SEED + 1)
    t = np.arange(n) / SR
    x *= 0.62 + 0.38 * np.sin(2 * np.pi * 3 * t / DUR)
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


BUILDERS = {"rain": rain, "ocean": ocean}


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
