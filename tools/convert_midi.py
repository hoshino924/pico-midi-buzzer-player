"""Convert a Standard MIDI File to the compact seven-voice M7S format.

This script runs on a computer with normal CPython and has no dependencies
outside the Python standard library. MIDI parsing, tempo conversion, sustain
handling, hand separation and physical voice assignment all happen here.
"""

import argparse
from pathlib import Path
import struct


EV_NOTE_OFF = 0
EV_NOTE_ON = 1
EV_CONTROL = 2
EV_TEMPO = 3

PHYSICAL_VOICES = 7
RIGHT_VOICES = 5
LEFT_VOICES = 2
ZERO_LENGTH_NOTE_BEAT_DIVISOR = 10
NO_CHANGE = 0xFF
NOTE_OFF = 0xFE

HEADER = struct.Struct("<4sBI")
RECORD = struct.Struct("<I7B")


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("Unexpected end of MIDI file")
    return data


def read_u16_be(stream):
    return struct.unpack(">H", read_exact(stream, 2))[0]


def read_u32_be(stream):
    return struct.unpack(">I", read_exact(stream, 4))[0]


def read_varlen(stream):
    value = 0
    for _ in range(4):
        byte = read_exact(stream, 1)[0]
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value
    raise ValueError("Invalid MIDI variable-length value")


def parse_midi(path):
    events = []
    song_end_tick = 0

    with path.open("rb") as stream:
        if read_exact(stream, 4) != b"MThd":
            raise ValueError("Not a Standard MIDI File")

        header_length = read_u32_be(stream)
        if header_length < 6:
            raise ValueError("Invalid MIDI header")

        midi_format = read_u16_be(stream)
        track_count = read_u16_be(stream)
        division = read_u16_be(stream)

        if midi_format not in (0, 1):
            raise ValueError("Only MIDI format 0 and 1 are supported")
        if division & 0x8000:
            raise ValueError("SMPTE MIDI timing is not supported")

        if header_length > 6:
            stream.seek(header_length - 6, 1)

        for track_index in range(track_count):
            chunk_id = read_exact(stream, 4)
            track_length = read_u32_be(stream)
            track_end = stream.tell() + track_length

            if chunk_id != b"MTrk":
                stream.seek(track_end)
                continue

            absolute_tick = 0
            running_status = None
            sequence = 0

            while stream.tell() < track_end:
                absolute_tick += read_varlen(stream)
                status = read_exact(stream, 1)[0]
                first_data = None

                if status < 0x80:
                    if running_status is None:
                        raise ValueError("Invalid MIDI running status")
                    first_data = status
                    status = running_status

                order = (track_index << 20) | sequence
                sequence += 1

                if status == 0xFF:
                    running_status = None
                    meta_type = read_exact(stream, 1)[0]
                    length = read_varlen(stream)
                    if meta_type == 0x51 and length == 3:
                        raw = read_exact(stream, 3)
                        tempo = (raw[0] << 16) | (raw[1] << 8) | raw[2]
                        events.append(
                            (
                                absolute_tick,
                                order,
                                track_index,
                                EV_TEMPO,
                                0,
                                tempo,
                                0,
                            )
                        )
                    else:
                        stream.seek(length, 1)
                    continue

                if status in (0xF0, 0xF7):
                    running_status = None
                    stream.seek(read_varlen(stream), 1)
                    continue

                if status >= 0xF0:
                    raise ValueError("Unsupported MIDI system event")

                running_status = status
                message_type = status & 0xF0
                channel = status & 0x0F
                data1 = first_data if first_data is not None else read_exact(stream, 1)[0]
                data2 = 0 if message_type in (0xC0, 0xD0) else read_exact(stream, 1)[0]

                if message_type == 0x90:
                    event_type = EV_NOTE_ON if data2 else EV_NOTE_OFF
                    events.append(
                        (
                            absolute_tick,
                            order,
                            track_index,
                            event_type,
                            channel,
                            data1,
                            data2,
                        )
                    )
                elif message_type == 0x80:
                    events.append(
                        (
                            absolute_tick,
                            order,
                            track_index,
                            EV_NOTE_OFF,
                            channel,
                            data1,
                            data2,
                        )
                    )
                elif message_type == 0xB0 and data1 in (64, 120, 121, 123):
                    events.append(
                        (
                            absolute_tick,
                            order,
                            track_index,
                            EV_CONTROL,
                            channel,
                            data1,
                            data2,
                        )
                    )

            song_end_tick = max(song_end_tick, absolute_tick)
            stream.seek(track_end)

    events.sort()
    return midi_format, track_count, division, song_end_tick, events


def extend_zero_length_notes(events, minimum_ticks):
    """Give same-tick note-on/off pairs a short audible duration."""
    same_tick_starts = {}
    adjusted = []
    extended_count = 0

    for event in events:
        tick, _, track, event_type, channel, note, _ = event
        key = (tick, track, channel, note)

        if event_type == EV_NOTE_ON:
            same_tick_starts[key] = same_tick_starts.get(key, 0) + 1
        elif event_type == EV_NOTE_OFF and same_tick_starts.get(key, 0):
            remaining = same_tick_starts[key] - 1
            if remaining:
                same_tick_starts[key] = remaining
            else:
                del same_tick_starts[key]
            event = (tick + minimum_ticks,) + event[1:]
            extended_count += 1

        adjusted.append(event)

    adjusted.sort()
    return adjusted, extended_count


class MidiState:
    def __init__(self, use_sustain):
        self.use_sustain = use_sustain
        self.held = {}
        self.sounding = {}
        self.sustain = [False] * 16
        self.sequence = 0

    def note_on(self, channel, note):
        key = (channel << 7) | note
        self.held[key] = self.held.get(key, 0) + 1
        self.sequence += 1
        self.sounding[key] = self.sequence

    def note_off(self, channel, note):
        key = (channel << 7) | note
        count = self.held.get(key, 0)
        if count > 1:
            self.held[key] = count - 1
            return
        if count == 1:
            del self.held[key]
        if not (self.use_sustain and self.sustain[channel]):
            self.sounding.pop(key, None)

    def control_change(self, channel, controller, value):
        if controller == 64:
            pedal_down = self.use_sustain and value >= 64
            was_down = self.sustain[channel]
            self.sustain[channel] = pedal_down
            if was_down and not pedal_down:
                self._release_unheld(channel)
        elif controller == 120:
            self._clear_channel(channel)
        elif controller == 121:
            self.sustain[channel] = False
            self._release_unheld(channel)
        elif controller == 123:
            keys = [key for key in self.held if key >> 7 == channel]
            for key in keys:
                del self.held[key]
                if not (self.use_sustain and self.sustain[channel]):
                    self.sounding.pop(key, None)

    def _release_unheld(self, channel):
        stale = [
            key
            for key in self.sounding
            if key >> 7 == channel and key not in self.held
        ]
        for key in stale:
            del self.sounding[key]

    def _clear_channel(self, channel):
        keys = [key for key in self.sounding if key >> 7 == channel]
        for key in keys:
            self.sounding.pop(key, None)
            self.held.pop(key, None)
        self.sustain[channel] = False

    def pitch_info(self):
        info = {}
        for key, sequence in self.sounding.items():
            note = key & 0x7F
            is_held = key in self.held
            previous = info.get(note)
            if previous is None:
                info[note] = (is_held, sequence)
            else:
                info[note] = (
                    previous[0] or is_held,
                    max(previous[1], sequence),
                )
        return info

    def selected_right_pitches(self, limit):
        info = self.pitch_info()
        if len(info) <= limit:
            return set(info)

        # The upper track carries the melody. In the rare five-note chord,
        # keep its four highest pitches rather than sacrificing the melody.
        return set(sorted(info, reverse=True)[:limit])

    def selected_left_pitches(self, limit):
        info = self.pitch_info()
        held = [note for note, detail in info.items() if detail[0]]
        released = [note for note, detail in info.items() if not detail[0]]

        # Electromagnetic buzzers reproduce the upper part of the left-hand
        # track more cleanly. Held notes and pedal tails both prefer pitch.
        chosen = sorted(held, reverse=True)[:limit]

        if len(chosen) >= limit:
            return set(chosen)

        # Pedal-released notes may use only channels not needed by keys that
        # are currently held. Prefer the highest remaining tails.
        for note in sorted(released, reverse=True):
            if note not in chosen and len(chosen) < limit:
                chosen.append(note)

        return set(chosen[:limit])


class VoiceAllocator:
    def __init__(self, voice_count):
        self.voice_count = voice_count
        self.notes = [None] * voice_count
        self.next_voice = 0

    def apply(self, selected):
        for voice, note in enumerate(self.notes):
            if note is not None and note not in selected:
                self.notes[voice] = None

        already_playing = {note for note in self.notes if note is not None}
        for note in sorted(selected, reverse=True):
            if note in already_playing:
                continue

            for offset in range(self.voice_count):
                voice = (self.next_voice + offset) % self.voice_count
                if self.notes[voice] is None:
                    self.notes[voice] = note
                    self.next_voice = (voice + 1) % self.voice_count
                    already_playing.add(note)
                    break

        return tuple(self.notes)


def encode_change(delta_us, previous, current):
    if not 0 <= delta_us <= 0xFFFFFFFF:
        raise ValueError("Score interval is too long")

    commands = []
    for old_note, new_note in zip(previous, current):
        if old_note == new_note:
            commands.append(NO_CHANGE)
        elif new_note is None:
            commands.append(NOTE_OFF)
        else:
            commands.append(new_note)
    return RECORD.pack(delta_us, *commands)


def render_score(
    ticks_per_beat,
    song_end_tick,
    events,
    right_track,
    left_track,
    use_sustain,
):
    # The two states and allocators are intentionally independent: notes can
    # be stolen inside one hand, but never cross the 5+2 hardware boundary.
    right_state = MidiState(False)
    left_state = MidiState(use_sustain)
    right_allocator = VoiceAllocator(RIGHT_VOICES)
    left_allocator = VoiceAllocator(LEFT_VOICES)
    records = []
    previous_output = tuple([None] * PHYSICAL_VOICES)

    tempo = 500000
    previous_tick = 0
    absolute_us = 0
    last_record_us = 0
    division_remainder = 0
    peak_right_pitches = 0
    peak_left_pitches = 0
    event_index = 0

    while event_index < len(events):
        tick = events[event_index][0]
        delta_ticks = tick - previous_tick
        scaled = delta_ticks * tempo + division_remainder
        absolute_us += scaled // ticks_per_beat
        division_remainder = scaled % ticks_per_beat

        while event_index < len(events) and events[event_index][0] == tick:
            event = events[event_index]
            track, event_type, channel, data1, data2 = event[2:7]
            if event_type == EV_TEMPO:
                tempo = data1
            elif track == right_track:
                if event_type == EV_NOTE_ON:
                    right_state.note_on(channel, data1)
                elif event_type == EV_NOTE_OFF:
                    right_state.note_off(channel, data1)
                elif event_type == EV_CONTROL:
                    right_state.control_change(channel, data1, data2)
            elif track == left_track:
                if event_type == EV_NOTE_ON:
                    left_state.note_on(channel, data1)
                elif event_type == EV_NOTE_OFF:
                    left_state.note_off(channel, data1)
                elif event_type == EV_CONTROL:
                    left_state.control_change(channel, data1, data2)
            event_index += 1

        right_info = right_state.pitch_info()
        left_info = left_state.pitch_info()
        peak_right_pitches = max(peak_right_pitches, len(right_info))
        peak_left_pitches = max(peak_left_pitches, len(left_info))

        right_selected = right_state.selected_right_pitches(RIGHT_VOICES)
        left_selected = left_state.selected_left_pitches(LEFT_VOICES)
        output = (
            right_allocator.apply(right_selected)
            + left_allocator.apply(left_selected)
        )
        if output != previous_output:
            records.append(
                encode_change(absolute_us - last_record_us, previous_output, output)
            )
            previous_output = output
            last_record_us = absolute_us

        previous_tick = tick

    # End-of-track always silences lingering pedal notes.
    if song_end_tick > previous_tick:
        scaled = (song_end_tick - previous_tick) * tempo + division_remainder
        absolute_us += scaled // ticks_per_beat

    silent = tuple([None] * PHYSICAL_VOICES)
    if previous_output != silent:
        records.append(
            encode_change(absolute_us - last_record_us, previous_output, silent)
        )

    return records, absolute_us, peak_right_pitches, peak_left_pitches


def write_score(path, records):
    with path.open("wb") as stream:
        stream.write(HEADER.pack(b"M7S1", PHYSICAL_VOICES, len(records)))
        for record in records:
            stream.write(record)


def main():
    parser = argparse.ArgumentParser(
        description="Convert MIDI to a low-memory seven-PWM Pico score"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="input Standard MIDI File supplied by the user",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output score file (default: named from the sustain setting)",
    )
    parser.add_argument(
        "--right-track",
        type=int,
        default=0,
        help="zero-based MIDI track used for the right hand (default: 0)",
    )
    parser.add_argument(
        "--left-track",
        type=int,
        default=1,
        help="zero-based MIDI track used for the left hand (default: 1)",
    )
    parser.add_argument(
        "--no-sustain",
        action="store_true",
        help="ignore CC64 sustain pedal events",
    )
    args = parser.parse_args()

    if args.right_track == args.left_track:
        parser.error("right and left tracks must be different")

    midi_format, track_count, ticks_per_beat, end_tick, events = parse_midi(
        args.input
    )
    minimum_note_ticks = max(1, ticks_per_beat // ZERO_LENGTH_NOTE_BEAT_DIVISOR)
    events, extended_notes = extend_zero_length_notes(events, minimum_note_ticks)
    if events:
        end_tick = max(end_tick, events[-1][0])
    if not 0 <= args.right_track < track_count:
        parser.error("right track is outside this MIDI file")
    if not 0 <= args.left_track < track_count:
        parser.error("left track is outside this MIDI file")

    output_path = args.output
    if output_path is None:
        output_path = Path.cwd() / "song.m7s"

    records, duration_us, peak_right, peak_left = render_score(
        ticks_per_beat,
        end_tick,
        events,
        args.right_track,
        args.left_track,
        not args.no_sustain,
    )
    write_score(output_path, records)

    print("Input: {}".format(args.input))
    print(
        "MIDI format {}, {} tracks, {} ticks/beat".format(
            midi_format, track_count, ticks_per_beat
        )
    )
    print(
        "Right hand: track {}, {} voices, peak {} pitches".format(
            args.right_track, RIGHT_VOICES, peak_right
        )
    )
    print(
        "Left hand: track {}, {} voices, peak {} pitches".format(
            args.left_track, LEFT_VOICES, peak_left
        )
    )
    print(
        "Extended zero-length notes: {} ({} ticks each)".format(
            extended_notes, minimum_note_ticks
        )
    )
    print("Sustain pedal: {}".format("enabled" if not args.no_sustain else "ignored"))
    print("Score records: {}".format(len(records)))
    print("Duration: {:.3f} seconds".format(duration_us / 1_000_000))
    print("Output: {} ({} bytes)".format(output_path, output_path.stat().st_size))


if __name__ == "__main__":
    main()
