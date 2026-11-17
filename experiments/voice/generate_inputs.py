"""Generate the 60 synthetic test WAV files using installed macOS voices."""
import argparse
import subprocess
import tempfile
from pathlib import Path

VOICES = ['Samantha', 'Daniel', 'Karen', 'Moira', 'Rishi', 'Tessa']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir', type=Path)
    args = parser.parse_args()
    sentences_file = Path(__file__).with_name('sentences.txt')
    sentences = sentences_file.read_text().splitlines()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'sentences.txt').write_text(sentences_file.read_text())
    with tempfile.TemporaryDirectory(prefix='docent-synthetic-') as scratch:
        intermediate = Path(scratch) / 'speech.aiff'
        for voice in VOICES:
            for number, sentence in enumerate(sentences, 1):
                output = args.output_dir / f'{voice}_{number:02d}.wav'
                subprocess.run(['say', '-v', voice, '-o', str(intermediate), sentence], check=True)
                subprocess.run(['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1',
                                str(intermediate), str(output)], check=True)
                print(output, flush=True)


if __name__ == '__main__':
    main()
