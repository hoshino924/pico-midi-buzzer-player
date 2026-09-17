"""Low-memory seven-voice score player for Raspberry Pi Pico / Pico 2.

The MIDI file is converted on the computer by convert_midi.py. This program
only streams the selected M7S score one 11-byte record at a time, so its RAM
use does not grow with the length of the song.
"""

from machine import Pin, PWM
import time


# Name of the score generated locally with tools/convert_midi.py.
SCORE_FILENAME = "song.m7s"

# GP2/4/6/8/10 are dedicated to the right hand. GP12/14 are dedicated to
# the left hand. These pins use PWM slices 1..7 respectively.
BUZZER_PINS = (2, 4, 6, 8, 10, 12, 14)

# Approximately 50% duty on every channel. Adjust individual entries only
# after completing a same-condition comparison of the three buzzer types.
DUTY_BY_VOICE = (32768, 32768, 32768, 32768, 32768, 32768, 32768)

VOICE_COUNT = 7
HEADER_SIZE = 9
RECORD_SIZE = 11
NO_CHANGE = 0xFF
NOTE_OFF = 0xFE


def _read_into_exact(stream, buffer):
    # A regular file on the Pico filesystem fills this small buffer in one
    # call. Avoid sliced memoryview objects so playback allocates nothing for
    # each record.
    if stream.readinto(buffer) != len(buffer):
        raise ValueError("Unexpected end of score file")


def _u32_le(data, offset):
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


def midi_note_to_hz(note):
    return int(440.0 * (2.0 ** ((note - 69) / 12.0)) + 0.5)


def _wait_until(deadline_us):
    while True:
        remaining = time.ticks_diff(deadline_us, time.ticks_us())
        if remaining <= 0:
            return
        if remaining > 3000:
            time.sleep_ms((remaining - 1500) // 1000)
        elif remaining > 80:
            time.sleep_us(remaining - 40)


class BuzzerBank:
    def __init__(self):
        if len(BUZZER_PINS) != VOICE_COUNT:
            raise ValueError("Exactly seven buzzer pins are required")
        if len(DUTY_BY_VOICE) != VOICE_COUNT:
            raise ValueError("Exactly seven duty values are required")

        self.pwms = []
        for pin_number in BUZZER_PINS:
            # Zero duty keeps every DRV777 input low during startup.
            self.pwms.append(
                PWM(Pin(pin_number, Pin.OUT), freq=440, duty_u16=0)
            )

    def apply_record(self, record):
        for voice in range(VOICE_COUNT):
            command = record[4 + voice]
            if command == NO_CHANGE:
                continue

            pwm = self.pwms[voice]
            pwm.duty_u16(0)

            if command == NOTE_OFF:
                continue

            if command > 127:
                raise ValueError("Invalid note in score file")

            # Muting before changing frequency avoids a short old-frequency
            # chirp. The PWM peripheral then sustains the note autonomously.
            pwm.freq(midi_note_to_hz(command))
            pwm.duty_u16(DUTY_BY_VOICE[voice])

    def stop_all(self):
        for pwm in self.pwms:
            pwm.duty_u16(0)

    def close(self):
        self.stop_all()
        for pwm in self.pwms:
            pwm.deinit()


def play_score(bank):
    header = bytearray(HEADER_SIZE)
    record = bytearray(RECORD_SIZE)

    with open(SCORE_FILENAME, "rb") as stream:
        _read_into_exact(stream, header)

        if not (
            header[0] == ord("M")
            and header[1] == ord("7")
            and header[2] == ord("S")
            and header[3] == ord("1")
        ):
            raise ValueError("Invalid score file header")

        if header[4] != VOICE_COUNT:
            raise ValueError("Score voice count does not match this player")

        record_count = _u32_le(header, 5)
        print("Playing %s (%d records)" % (SCORE_FILENAME, record_count))

        deadline = time.ticks_us()
        for _ in range(record_count):
            _read_into_exact(stream, record)
            delta_us = _u32_le(record, 0)
            deadline = time.ticks_add(deadline, delta_us)
            _wait_until(deadline)
            bank.apply_record(record)

    bank.stop_all()
    print("Playback complete")


def main():
    bank = BuzzerBank()
    try:
        play_score(bank)
    except OSError:
        bank.stop_all()
        print("Score file not found: %s" % SCORE_FILENAME)
        print("Run convert_midi.py on the computer, then copy that score here.")
    except Exception as error:
        bank.stop_all()
        print("ERROR:", error)
        raise
    finally:
        bank.close()


if __name__ == "__main__":
    main()
