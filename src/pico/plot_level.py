"""
plot_level.py
=============

Plot the wave of `level` values that 3_deviation_ver.py saved on the Pico.

Workflow
--------
1) Run on the Pico:           mpremote run src/pico/3_deviation_ver.py
2) Stop with Ctrl+C           (the script writes /levels.txt on the Pico)
3) Copy the file off:         mpremote cp :levels.txt .
4) Plot it on your laptop:    python src/pico/plot_level.py
                              python src/pico/plot_level.py path/to/levels.txt

Install once:                 pip install matplotlib
"""

import sys
import matplotlib.pyplot as plt


# In silence the PDM bit density sits near 0.5. Subtracting 0.5 centers the
# series around zero so it actually looks like a wave instead of a flat line.
DC_BASELINE = 0.5


def load_levels(path):
    """Read one float per line from `path`. Skips blank / non-numeric lines."""
    levels = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                levels.append(float(s))
            except ValueError:
                continue
    return levels


def plot_levels(levels, source_label):
    if not levels:
        print("No level values found.", file=sys.stderr)
        return

    wave = [v - DC_BASELINE for v in levels]
    peak = max(0.05, max(abs(x) for x in wave))

    fig, (ax_wave, ax_raw) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax_wave.plot(wave, linewidth=0.9, color="tab:blue")
    ax_wave.axhline(0.0, color="gray", linewidth=0.5)
    ax_wave.set_ylim(-peak * 1.2, peak * 1.2)
    ax_wave.set_ylabel("level - 0.5\n(centered)")
    ax_wave.set_title(f"PDM density wave  —  {source_label}  ({len(levels)} samples)")
    ax_wave.grid(True, alpha=0.3)

    ax_raw.plot(levels, linewidth=0.9, color="tab:orange")
    ax_raw.axhline(DC_BASELINE, color="gray", linewidth=0.5, linestyle="--")
    ax_raw.set_ylim(0.0, 1.0)
    ax_raw.set_ylabel("raw level\n(0..1)")
    ax_raw.set_xlabel("sample index  (one per ~200 ms)")
    ax_raw.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "levels.txt"
    levels = load_levels(path)
    plot_levels(levels, source_label=path)


if __name__ == "__main__":
    main()
