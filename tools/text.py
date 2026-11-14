"""The game's string tables as plain text, and back.

  python tools/text.py build                       text/*.txt -> Language/Text/*.bin and *.ofs
  python tools/text.py decode <bin> <ofs> <txt>    a string table as text (what build makes of it)
  python tools/text.py import <old pack> <english game> <out folder>
        the tables of release 1.0.0 as text: once, to start text/*.txt

A string table is <name>.bin (strings, each ended by a zero byte) and <name>.ofs (16-bit offsets of
the strings). A byte of a string is the character's code minus 0x1F, and that byte is also the number
of the character's record in the font tables (FEText/*.tab). The codes follow ASCII up to 0x60; after
that come the fonts' symbols (0x5E-0x6E) and, in this translation, the Russian letters that no Latin
letter looks like (0x6F-0x84). A Russian letter that looks like a Latin one shares its code.

In text/*.txt one line is one string. Russian and Latin letters, digits and punctuation are written as
they are; any other code is written as {XX}, its hexadecimal value.
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLES = ('fetext', 'gtext')

# Russian letters with a code of their own, in alphabet order from 0x6F
OWN = 'БГДЁЖЗИЙЛПУФЦЧШЩЪЫЬЭЮЯ'
# Russian letters drawn by the Latin letter of the same shape
SHARED = dict(zip('АВЕКМНОРСТХ', 'ABEKMHOPCTX'))
CODE = {ch: 0x6F + i for i, ch in enumerate(OWN)}
CODE.update({ch: ord(latin) for ch, latin in SHARED.items()})
CHAR = {code: ch for ch, code in CODE.items() if ch in OWN}

# release 1.0.0 drew Russian letters in the places of the 26 Latin ones
OLD = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'АВСДЕБЖНIГКЦМИОРФЯЬТПЛШХУЮ'))


def read_table(bin_path, ofs_path):
    data = Path(bin_path).read_bytes()
    ofs = Path(ofs_path).read_bytes()
    offsets = struct.unpack('<%dH' % (len(ofs) // 2), ofs)
    return [data[o:data.index(0, o)] for o in offsets], data, offsets


def to_text(raw, old=False):
    """Bytes of one string -> a line of text. With old=True the Latin letters are the Russian ones of 1.0.0."""
    out = []
    command = False
    for b in raw:
        a = b + 0x1F
        ch = chr(a)
        if a in CHAR and not old:
            out.append(CHAR[a])
        elif 0x20 <= a < 0x5E and ch not in '{}':
            # a letter after a slash is a command of the game (/N new line, /S space, /Z position...), and
            # > with digits and a letter stands for a value (>S a name, >2N a number): these stay Latin
            out.append(OLD[ch] if old and ch in OLD and not command else ch)
        else:
            out.append('{%02X}' % a)
        command = (ch == '/' and not command) or ch == '>' or (command and ch.isdigit())
    return ''.join(out)


def to_bytes(line, where=''):
    out = bytearray()
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '{':
            end = line.index('}', i)
            a = int(line[i + 1:end], 16)
            i = end
        elif ch in CODE:
            a = CODE[ch]
        elif 0x20 <= ord(ch) < 0x5E:
            a = ord(ch)
        else:
            raise SystemExit('%s: no code for %r in %r' % (where, ch, line))
        out.append(a - 0x1F)
        i += 1
    if 0 in out:
        raise SystemExit('%s: code 0x1F ends a string: %r' % (where, line))
    return bytes(out)


def write_table(lines, bin_path, ofs_path, where):
    data = bytearray()
    offsets = []
    for n, line in enumerate(lines):
        offsets.append(len(data))
        data += to_bytes(line, '%s line %d' % (where, n + 1)) + b'\0'
    if len(data) > 0xFFFF:
        raise SystemExit('%s: %d bytes, the offsets are 16-bit' % (where, len(data)))
    Path(bin_path).write_bytes(bytes(data))
    Path(ofs_path).write_bytes(struct.pack('<%dH' % len(offsets), *offsets))
    return len(lines), len(data)


def lines_of(txt_path):
    text = Path(txt_path).read_text(encoding='utf-8')
    return text[:-1].split('\n') if text.endswith('\n') else text.split('\n')


def check_grids(lines):
    """The letter grids of the name screen (fetext strings 0 and 0x310) must hold all 26 Latin letters.

    For a key A-Z the game looks its Latin letter up in the grid and does not check that it is there:
    a grid without the letter crashes the game on that key (release 1.1.0 did, on 15 keys).
    """
    for n in (0, 0x310):
        grid = to_bytes(lines[n])
        missing = [chr(a) for a in range(ord('A'), ord('Z') + 1) if a - 0x1F not in grid]
        if missing:
            raise SystemExit('fetext line %d, a letter grid of the name screen, has no %s: the game crashes '
                             'on these keys' % (n + 1, ' '.join(missing)))
        if len(grid) > 49:
            raise SystemExit('fetext line %d: %d cells, the board of the name screen has five rows of ten and '
                             'the game makes a sixth row from 50 cells on' % (n + 1, len(grid)))


def build():
    for name in TABLES:
        out = ROOT / 'Language' / 'Text'
        if name == 'fetext':
            check_grids(lines_of(ROOT / 'text' / (name + '.txt')))
        count, size = write_table(lines_of(ROOT / 'text' / (name + '.txt')), out / (name + '.bin'), out / (name + '.ofs'), name)
        print('%s: %d strings, %d bytes' % (name, count, size))


def decode(bin_path, ofs_path, txt_path):
    strings, _, _ = read_table(bin_path, ofs_path)
    Path(txt_path).write_text(''.join(to_text(s) + '\n' for s in strings), encoding='utf-8')
    print('%d strings' % len(strings))


def import_old(pack, english, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        paths = [Path(root) / 'Language' / 'Text' / (name + ext) for root in (pack, english) for ext in ('.bin', '.ofs')]
        strings, data, offsets = read_table(paths[0], paths[1])
        untranslated = set(read_table(paths[2], paths[3])[0])
        # a string that the English game has too was left as it was: its letters are Latin
        lines = [to_text(s, old=s not in untranslated) for s in strings]
        (out / (name + '.txt')).write_text(''.join(l + '\n' for l in lines), encoding='utf-8')
        same = sum(1 for s in strings if s and s in untranslated)
        in_order = all(offsets[i] + len(strings[i]) + 1 == offsets[i + 1] for i in range(len(offsets) - 1))
        print('%s: %d strings, %d of them as in the English game, %d bytes, strings in file order: %s'
              % (name, len(strings), same, len(data), in_order))


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['build'] and len(args) == 1:
        build()
    elif args[:1] == ['decode'] and len(args) == 4:
        decode(*args[1:])
    elif args[:1] == ['import'] and len(args) == 4:
        import_old(*args[1:])
    else:
        raise SystemExit(__doc__)
