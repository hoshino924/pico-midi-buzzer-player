**简体中文** | [English](README_EN.md)

# Pico MIDI 七路无源蜂鸣器播放器

这是一个面向 Raspberry Pi Pico / Pico 2 的七声部无源蜂鸣器播放器。MIDI 在电脑端预先转换成紧凑的 `.m7s` 文件，Pico 只负责按时间流式读取记录并驱动七路硬件 PWM，因此不需要在内存中解析或保存整首 MIDI。

默认声部分配适用于钢琴双轨 MIDI：右手使用 5 个蜂鸣器，左手使用 2 个蜂鸣器。左右手声部独立分配，不会互相抢占。

## 特点

- Pico 端使用 MicroPython，无需 C/C++ 或 PIO。
- GP2、GP4、GP6、GP8、GP10、GP12、GP14 分属七个独立 PWM slice。
- 电脑端转换器仅使用 Python 标准库，不依赖 `mido`。
- 每次只读取一条 11 字节演奏记录，内存占用不随乐曲长度增长。
- 支持 MIDI tempo、Note On/Off、CC64 延音踏板以及 CC120/121/123。
- 右手最多保留 5 个同时音，左手最多保留 2 个高音。
- 自动修复 Note On 后立即 Note Off 的零长度音符，使蜂鸣器能够发声。

## 仓库结构

```text
pico-midi-buzzer-player/
├─ firmware/
│  └─ main.py              Pico / Pico 2 播放程序
├─ hardware/
│  └─ gerber/              PCB Gerber 与钻孔生产文件
├─ tools/
│  └─ convert_midi.py      电脑端 MIDI 转换器
├─ README.md               中文说明
├─ README_EN.md            English documentation
├─ LICENSE                 MIT License
└─ .gitignore
```

仓库和 Releases 均不提供 MIDI 或 `.m7s` 音乐数据。`.gitignore` 会排除这些文件，使用者需要在本地转换自己有权使用的 MIDI。

## 硬件

- Raspberry Pi Pico 或 Pico 2
- 7 个无源蜂鸣器
- DRV777 或功能相当的低侧驱动器
- 符合蜂鸣器额定电压和总电流要求的外部电源

### PCB 文件

- 可直接交给 PCB 工厂的 Gerber 和钻孔文件放在 `hardware/gerber/`。
- 可编辑 PCB 工程在外部硬件设计平台公开： https://oshwhub.com/andyray/project_hbfraeku
- Gerber 属于本仓库内容，按 MIT License 提供，但生产前仍应自行检查板厂规则、封装和电气参数。

### GPIO 分配

| 声部 | 用途 | Pico GPIO | PWM slice |
|---:|---|---:|---:|
| 1 | 右手 | GP2 | 1A |
| 2 | 右手 | GP4 | 2A |
| 3 | 右手 | GP6 | 3A |
| 4 | 右手 | GP8 | 4A |
| 5 | 右手 | GP10 | 5A |
| 6 | 左手 | GP12 | 6A |
| 7 | 左手 | GP14 | 7A |

### DRV777 接线

```text
Pico GPx  ────────── DRV777 INx
蜂鸣器负极 ───────── DRV777 OUTx
蜂鸣器正极 ───────── 外部电源正极
Pico GND ─────────── DRV777 GND ─── 外部电源负极
DRV777 COM ────────── 外部电源正极
```

不要从 Pico GPIO 给蜂鸣器供电，也不要让七个电磁蜂鸣器直接使用 Pico 的 3V3 电源。Pico、DRV777 和外部负载电源必须共地，电源电压不得超过蜂鸣器额定值。首次长时间演奏时应检查总电流、DRV777 压降和封装温升。

## 快速开始

### 1. 转换自己的 MIDI

准备一个自己创作、已获授权或法律允许使用的双 Track 钢琴 MIDI，将它以 `song.mid` 为名临时放在仓库根目录，然后生成 `song.m7s`。`song.mid` 已被 `.gitignore` 排除，不会进入提交：

```powershell
py .\tools\convert_midi.py .\song.mid --no-sustain -o .\song.m7s
```

固件默认读取：

```python
SCORE_FILENAME = "song.m7s"
```

### 2. 写入 Pico

使用 Thonny 将以下两个文件保存到 Pico 文件系统根目录：

```text
main.py
song.m7s
```

其中 `main.py` 来自 `firmware/main.py`。不要把 MIDI 文件复制到 Pico。

也可以使用 `mpremote`：

```powershell
mpremote connect auto fs cp .\firmware\main.py :main.py
mpremote connect auto fs cp .\song.m7s :song.m7s
mpremote connect auto reset
```

如果程序正在自动运行，先在 Thonny 中停止程序，或在连接后按 `Ctrl+C`，再复制文件。

## 转换选项

转换器支持 Standard MIDI File format 0/1，但默认声部分配要求 MIDI 中至少存在两个可区分的 Track。默认把 Track 0 作为右手、Track 1 作为左手。

无延音版本：

```powershell
py .\tools\convert_midi.py .\song.mid --no-sustain -o .\song.m7s
```

读取 CC64 延音踏板：

```powershell
py .\tools\convert_midi.py .\song.mid -o .\song_sustain.m7s
```

如果左右手位于其他 Track，可明确指定索引：

```powershell
py .\tools\convert_midi.py .\song.mid --right-track 1 --left-track 2 -o .\song.m7s
```

转换器的声部策略如下：

- 右手 Track 固定使用前 5 路 PWM，最多完整保留 5 个同时音。
- 左手 Track 固定使用后 2 路 PWM，发生竞争时优先保留两个较高音。
- 延音尾音只能使用左手当前没有被按键音占用的通道，并同样优先高音。
- 零长度音符会被延长到十分之一拍，其他音符时值不变。

## `.m7s` 格式

文件头为 9 字节：

| 字段 | 长度 | 说明 |
|---|---:|---|
| Magic | 4 字节 | ASCII `M7S1` |
| Voice count | 1 字节 | 固定为 7 |
| Record count | 4 字节 | 小端无符号整数 |

之后每条记录为 11 字节：4 字节小端时间增量（微秒），加上 7 个声部命令。命令 `0..127` 表示 MIDI 音高，`0xFE` 表示关闭该声部，`0xFF` 表示保持不变。

## 调整

每个蜂鸣器的占空比可以在 `firmware/main.py` 中独立设置：

```python
DUTY_BY_VOICE = (32768, 32768, 32768, 32768, 32768, 32768, 32768)
```

不同型号蜂鸣器的谐振频率、响度和低频响应可能差异很大。即使软件已经输出某个音高，蜂鸣器也可能因为频响或供电条件而听起来很弱。

## 当前限制

- 不处理 MIDI 音色、力度、弯音和声像。
- 左右手必须能够通过 Track 区分；仅按 MIDI Channel 分轨的文件可能需要预处理。
- 相同音高的重叠音会共享一个物理输出。
- `.m7s` 是本项目使用的专用演奏格式，不是通用 MIDI 格式。

## 音乐与版权

本仓库及其 Releases 不提供 MIDI、`.m7s` 或其他乐曲数据。使用者应只转换自己创作、已获授权或法律允许使用的音乐，并自行负责生成文件的使用与分发。把 MIDI 转换成 `.m7s` 并不会自动消除作品、编曲或演奏数据可能存在的版权。

## 许可证

本项目的代码、文档和仓库内硬件文件使用 [MIT License](LICENSE)。外部平台上的可编辑 PCB 工程应以该平台页面标示的许可证为准。
