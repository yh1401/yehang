#!/usr/bin/env python3
"""夜航 · 助眠音景离线合成器

两类资产，全部交给 <audio> 媒体元素播放
（Web Audio 实时合成在 iOS 锁屏/切后台时会被系统挂起，必须换成媒体元素）：

1. 单轨循环 tracks：rain / ocean / piano / pink 四条互不相干的 60s 无缝循环，
   供桌面端「四轨自由混音」用——桌面浏览器能写 el.volume，可以实时精调每一轨。
2. 预混音景 scapes：把若干轨按固定比例烘成一条 120s 无缝循环，另外导出一份
   「60 分钟 + 尾部自带淡出」的长文件。原因：iOS 上 el.volume 是只读的
   （读回恒为 1，Apple 官方文档明确说明），锁屏后 JS 线程更是完全停摆，
   所以「调音量」和「淡出停止」都只能在文件里预先烘好，不能靠脚本。

无缝的关键：噪声在频域塑形后做逆 FFT，得到的信号以循环长度为周期，
循环点天然连续，不需要交叉淡化，也不会有 MP3/AAC 那样的编码器空隙。

长文件「一份撑多档定时」：总长 60 分钟、最后 45 秒自带淡出，于是
    30 分钟 = 从 30:00 起播；60 分钟 = 从 00:00 起播。
不必为每一档时长各存一份文件，省掉一半体积。

用法：
    python3 tools/make_loops.py             # 生成全部
    python3 tools/make_loops.py tracks      # 只生成四条单轨循环
    python3 tools/make_loops.py scapes      # 只生成预混音景
    python3 tools/make_loops.py rain ocean  # 只生成指定单轨
"""
import sys
import wave
import subprocess
import numpy as np
from pathlib import Path

SR = 22050          # 采样率：音景能量集中在 2kHz 以下，22.05k 足够且体积减半
DUR = 60.0          # 单轨循环长度（秒）
SCAPE_DUR = 120.0   # 预混音景的循环长度（秒）：更长 → 钢琴等旋律的重复感更弱
OUT_DIR = Path(__file__).resolve().parent.parent / "web" / "audio"
SEED = 20260930     # 固定随机种子，保证可复现
TOTAL_MIN = 60      # 长文件总时长（分钟）
FADE_IN = 3.0       # 长文件开头的淡入（秒）
FADE_OUT = 45.0     # 长文件末尾的淡出（秒）——锁屏后只有它靠得住
BITRATE = "24k"     # AAC 单声道码率：噪声类内容 24k 足够，60 分钟约 10 MB


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


def rain(dur=DUR):
    """雨声：宽带噪声，160Hz 高通去掉隆隆声，1500Hz 低通做两次（12dB/oct）让雨丝柔和。"""
    n = int(SR * dur)
    x = spectral_noise(n, lambda f: hp1(f, 160) * lp1(f, 1500) ** 2, SEED)
    # 缓慢起伏：约 30 秒一个周期，取整周期保证循环点不跳
    t = np.arange(n) / SR
    x *= 1.0 + 0.15 * np.sin(2 * np.pi * max(1, int(round(dur / 30))) * t / dur)
    return x


def ocean(dur=DUR):
    """海浪：更低的低通（布朗噪声感）+ 约 20 秒一波的涨落（取整周期，循环点不跳）。"""
    n = int(SR * dur)
    x = spectral_noise(n, lambda f: hp1(f, 40) * lp1(f, 520) ** 2, SEED + 1)
    t = np.arange(n) / SR
    x *= 0.62 + 0.38 * np.sin(2 * np.pi * max(1, int(round(dur / 20))) * t / dur)
    return x


def pink(dur=DUR):
    """粉红噪声：能量按 1/f 分布（每倍频程 -3dB），比白噪更"厚"、更适合掩蔽环境噪。

    低频兜底：把 0~1Hz 并入 1Hz，避开 1/sqrt(f) 在直流处的奇异点（spec[0] 随后会被置零）。
    """
    n = int(SR * dur)
    x = spectral_noise(n, lambda f: hp1(f, 30) * (1.0 / np.sqrt(np.maximum(f, 1.0))), SEED + 3)
    return x


# 低频钢琴用的音高：A2 起的五声音阶，只取低音区，避免听感"吵"
PENTA = [110.0, 130.81, 146.83, 164.81, 196.0, 220.0, 246.94]


def add_note(x, start_sec, freq, amp):
    """把一个钢琴音环绕累加进 x。

    起音 20ms、指数衰减 tau≈1.3s、总长 6s（尾部已很轻）。
    索引用 (start + i) % n 环绕：靠近循环末尾的音，其尾音会自然接回开头，
    所以接缝处依然是连续的（不需要交叉淡化）。
    """
    n = len(x)
    ln = int(6.0 * SR)
    t = np.arange(ln) / SR
    env = (1.0 - np.exp(-t / 0.02)) * np.exp(-t / 1.3)
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2.004 * t)
    idx = (int(start_sec * SR) + np.arange(ln)) % n
    x[idx] += amp * env * tone


def piano(dur=DUR):
    """低频钢琴：散布五声音阶低音，间隔 2.6~5.4 秒，偶尔两音叠置。"""
    n = int(SR * dur)
    rng = np.random.default_rng(SEED + 2)
    x = np.zeros(n)
    pos = 0.4
    while pos < dur:
        freq = PENTA[rng.integers(0, len(PENTA))]
        add_note(x, pos, freq, amp=0.5)
        if rng.random() < 0.28:                       # 偶尔叠一个高八度的泛音点缀
            add_note(x, pos + 0.06, freq * 2, amp=0.16)
        pos += rng.uniform(2.6, 5.4)
    return x


def normalise(x, peak=0.85):
    """按峰值归一化（单轨 WAV 用：交给桌面端混音器，只保证不削波）。"""
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def loudness_norm(x, rms=0.12, peak=0.92):
    """按 RMS 对齐响度，再兜一个峰值上限。

    不同音景的峰值因子差很多（钢琴有瞬态、噪声没有），只按峰值归一化会明显一响一轻；
    iOS 上又没法用 el.volume 补救，所以必须在这里把四条音景的脚步对齐。
    """
    cur = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    if cur > 0:
        x = x * (rms / cur)
    m = float(np.max(np.abs(x)))
    if m > peak:
        x = x * (peak / m)
    return x


def to_pcm(x):
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def write_wav(path, x):
    # WAV 无编码器延迟，循环点最干净；短的单轨循环用它，长文件转成 m4a 压体积
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(to_pcm(x))
    return path.stat().st_size


def encode_m4a(wav_path, m4a_path, bitrate=BITRATE):
    """WAV → m4a(AAC 单声道)。

    必须带 +faststart：把 moov 原子挪到文件头部，这样 iOS 在 60 分钟长文件里
    按 Range 跳到「30 分钟处」时不必先把整个文件下完。
    """
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav_path),
        "-c:a", "aac", "-b:a", bitrate,
        "-ac", "1", "-ar", str(SR),
        "-movflags", "+faststart",
        str(m4a_path),
    ], check=True)
    return m4a_path.stat().st_size


def write_timed_m4a(scape, m4a_path, minutes=TOTAL_MIN):
    """把无缝循环平铺到 minutes 分钟，首尾各烘一段淡入/淡出，再编码成 m4a。

    分块写入：60 分钟 = 7940 万个采样，一次性建数组会吃掉几百 MB 内存，
    所以按「一圈循环」为单位算好包络后立刻落盘，峰值内存只有一圈。
    """
    m4a_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = m4a_path.with_name(m4a_path.stem + ".tmp.wav")
    n = len(scape)
    total = int(round(SR * minutes * 60))
    fin = max(1, int(FADE_IN * SR))
    fout = max(1, int(FADE_OUT * SR))
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        pos = 0
        while pos < total:
            m = min(n, total - pos)
            idx = np.arange(pos, pos + m)
            g = np.ones(m)
            head = idx < fin
            g[head] = idx[head] / fin
            tail = idx >= (total - fout)
            g[tail] = (total - idx[tail]) / fout
            w.writeframes(to_pcm(scape[:m] * g))
            pos += m
    size = encode_m4a(tmp, m4a_path)
    tmp.unlink()
    return size


BUILDERS = {"rain": rain, "ocean": ocean, "piano": piano, "pink": pink}

# 预混音景：名称 → (显示名, {轨: 烘焙增益})
SCAPES = {
    "rainpiano": ("雨落屋檐 · 低频钢琴", {"rain": 0.62, "piano": 0.78}),
    "ocean":     ("海浪",               {"ocean": 1.0}),
    "rain":      ("纯雨声",             {"rain": 1.0}),
    "pink":      ("粉红噪声",           {"pink": 1.0}),
}


def build_scape(parts, dur=SCAPE_DUR):
    """按固定比例把若干轨混成一条无缝循环，并按 RMS 对齐响度。"""
    layers = {name: normalise(BUILDERS[name](dur)) for name in parts}
    n = int(SR * dur)
    x = np.zeros(n)
    for name, g in parts.items():
        x += g * layers[name]
    return loudness_norm(x)


def build_tracks(names):
    for name in names:
        x = normalise(BUILDERS[name]())
        p = OUT_DIR / f"{name}-loop.wav"
        size = write_wav(p, x)
        print(f"  + {p.name}  {DUR:.0f}s {SR}Hz mono  {size / 1024 / 1024:.2f} MB")


def build_scapes(names):
    for name in names:
        label, parts = SCAPES[name]
        x = build_scape(parts)
        loop_m4a = OUT_DIR / f"sc-{name}-loop.m4a"
        loop_wav = OUT_DIR / f"sc-{name}-loop.tmp.wav"
        write_wav(loop_wav, x)
        s1 = encode_m4a(loop_wav, loop_m4a)
        loop_wav.unlink()
        full_m4a = OUT_DIR / f"sc-{name}-full.m4a"
        s2 = write_timed_m4a(x, full_m4a)
        print(f"  + {loop_m4a.name}  {SCAPE_DUR:.0f}s  {s1 / 1024:.0f} KB  （{label}）")
        print(f"  + {full_m4a.name}  {TOTAL_MIN}min  {s2 / 1024 / 1024:.1f} MB")


def main():
    args = sys.argv[1:]
    if not args:
        build_tracks(list(BUILDERS))
        build_scapes(list(SCAPES))
        return
    if args[0] == "tracks":
        build_tracks(args[1:] or list(BUILDERS))
        return
    if args[0] == "scapes":
        build_scapes(args[1:] or list(SCAPES))
        return
    names = [a for a in args if a in BUILDERS]
    if not names:
        print("未知参数:", " ".join(args), "｜可选：tracks / scapes /", ", ".join(BUILDERS))
        return
    build_tracks(names)


if __name__ == "__main__":
    main()
