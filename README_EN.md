[简体中文](README.md) | **English**

# Pico Seven-Voice MIDI Buzzer Player

This project is a seven-voice passive-buzzer player for the Raspberry Pi Pico and Pico 2. MIDI files are preprocessed on a computer into a compact `.m7s` score. The Pico only streams timed records and drives seven hardware PWM outputs, so it never needs to parse or hold an entire MIDI file in memory.

The default voice layout is designed for two-track piano MIDI files: five buzzers are assigned to the right hand and two to the left hand. The two groups allocate voices independently and never steal channels from each other.

## Features

- MicroPython firmware; no C/C++ or PIO required.
- GP2, GP4, GP6, GP8, GP10, GP12, and GP14 use seven independent PWM slices.
- The desktop converter uses only the Python standard library and does not require `mido`.
- Playback streams one 11-byte record at a time, so RAM usage does not grow with song length.
- Supports MIDI tempo, Note On/Off, CC64 sustain, and CC120/121/123.
- Keeps up to five simultaneous right-hand pitches and the two highest left-hand pitches.
- Repairs zero-length Note On/Off pairs so that a buzzer can reproduce them.

## Repository Layout

```text
pico-midi-buzzer-player/
├─ firmware/
│  └─ main.py              Pico / Pico 2 player
├─ hardware/
│  └─ gerber/              PCB Gerber and drill production files
├─ tools/
│  └─ convert_midi.py      Desktop MIDI converter
├─ README.md               Chinese documentation
├─ README_EN.md            English documentation
├─ LICENSE                 MIT License
└─ .gitignore
```

Neither the repository nor its Releases provides MIDI or `.m7s` music data. `.gitignore` excludes these files, and users must locally convert MIDI they are entitled to use.

## Hardware

- Raspberry Pi Pico or Pico 2
- Seven passive buzzers
- DRV777 or an equivalent low-side driver
- An external supply rated for the buzzer voltage and total load current

### PCB Files

- Gerber and drill files ready for PCB fabrication belong in `hardware/gerber/`.
- The editable PCB project will be published on an external hardware-design platform. Its URL will be added here after that project is created.
- Gerbers committed to this repository are provided under the MIT License, but users should still verify board-house rules, footprints, and electrical parameters before fabrication.

### GPIO Assignment

| Voice | Part | Pico GPIO | PWM slice |
|---:|---|---:|---:|
| 1 | Right hand | GP2 | 1A |
| 2 | Right hand | GP4 | 2A |
| 3 | Right hand | GP6 | 3A |
| 4 | Right hand | GP8 | 4A |
| 5 | Right hand | GP10 | 5A |
| 6 | Left hand | GP12 | 6A |
| 7 | Left hand | GP14 | 7A |

### DRV777 Wiring

```text
Pico GPx  ────────── DRV777 INx
Buzzer negative ──── DRV777 OUTx
Buzzer positive ──── External supply positive
Pico GND ─────────── DRV777 GND ─── External supply negative
DRV777 COM ───────── External supply positive
```

Do not power the buzzers from a Pico GPIO, and do not run seven electromagnetic buzzers directly from the Pico 3V3 rail. The Pico, DRV777, and external load supply must share ground. Never exceed the buzzer voltage rating. During the first extended playback test, check total current, driver voltage drop, and DRV777 package temperature.

## Quick Start

### 1. Convert Your Own MIDI

Prepare a two-track piano MIDI that you created, are licensed to use, or are otherwise legally permitted to use. Temporarily place it in the repository root as `song.mid`, then generate `song.m7s`. `song.mid` is excluded by `.gitignore` and will not be committed:

```powershell
py .\tools\convert_midi.py .\song.mid --no-sustain -o .\song.m7s
```

The firmware expects this filename by default:

```python
SCORE_FILENAME = "song.m7s"
```

### 2. Copy Files to the Pico

With Thonny, save these two files in the root of the Pico filesystem:

```text
main.py
song.m7s
```

Use `firmware/main.py` as `main.py`. Do not copy the MIDI file to the Pico.

You can also use `mpremote`:

```powershell
mpremote connect auto fs cp .\firmware\main.py :main.py
mpremote connect auto fs cp .\song.m7s :song.m7s
mpremote connect auto reset
```

If the firmware is already running, stop it in Thonny or press `Ctrl+C` after connecting before copying files.

## Conversion Options

The converter supports Standard MIDI File formats 0 and 1, but the default voice layout expects at least two distinguishable tracks. By default, track 0 is the right hand and track 1 is the left hand.

Without sustain:

```powershell
py .\tools\convert_midi.py .\song.mid --no-sustain -o .\song.m7s
```

With CC64 sustain:

```powershell
py .\tools\convert_midi.py .\song.mid -o .\song_sustain.m7s
```

Specify different track indexes when needed:

```powershell
py .\tools\convert_midi.py .\song.mid --right-track 1 --left-track 2 -o .\song.m7s
```

The voice policy is:

- The right-hand track always uses the first five PWM outputs and can preserve up to five simultaneous pitches.
- The left-hand track always uses the last two PWM outputs and keeps the two highest pitches when oversubscribed.
- Sustained tails may use only left-hand outputs not occupied by currently held notes, with higher tails preferred.
- Zero-length notes are extended to one tenth of a beat. Other note lengths are unchanged.

## `.m7s` File Format

The file begins with a 9-byte header:

| Field | Size | Description |
|---|---:|---|
| Magic | 4 bytes | ASCII `M7S1` |
| Voice count | 1 byte | Fixed at 7 |
| Record count | 4 bytes | Little-endian unsigned integer |

Each following record is 11 bytes: a 4-byte little-endian time delta in microseconds followed by seven voice commands. Values `0..127` select a MIDI pitch, `0xFE` turns the voice off, and `0xFF` leaves it unchanged.

## Tuning

The duty cycle of each buzzer can be adjusted independently in `firmware/main.py`:

```python
DUTY_BY_VOICE = (32768, 32768, 32768, 32768, 32768, 32768, 32768)
```

Buzzer models can differ greatly in resonant frequency, loudness, and low-frequency response. A pitch may therefore sound weak because of the transducer or power supply even when the firmware is generating it correctly.

## Current Limitations

- MIDI instrument, velocity, pitch bend, and pan are ignored.
- The hands must be distinguishable by track. Files separated only by MIDI channel may need preprocessing.
- Overlapping notes at the same pitch share one physical output.
- `.m7s` is a project-specific score format, not a general MIDI format.

## Music and Copyright

Neither this repository nor its Releases provides MIDI, `.m7s`, or other song data. Only convert music you created, are licensed to use, or are otherwise legally permitted to use, and take responsibility for using or distributing generated files. Converting MIDI into `.m7s` does not automatically remove copyright that may exist in the composition, arrangement, or performance data.

## License

Code, documentation, and hardware files committed to this repository are available under the [MIT License](LICENSE). The editable PCB project hosted externally is governed by the license shown on that platform.
