"""The game's fonts with the whole Russian alphabet. Needs Pillow.

  python tools/fonts.py build <release 1.0.0 folder> <English game folder>
        writes the fonts of this repository: FEText/*.bmp, FEText/*.tab, Language/Tims/FONTTIMS.MAD
  python tools/fonts.py sheet <folder> <out folder>
        pictures of every font of a game or pack folder, each glyph with its record number

A font is a picture 256 pixels wide and a table (FEText/*.tab) with one record per character: x, y,
width, height, 16 bits each. A record's number is the character's byte in the text (see text.py), x and
y are counted from those of record 2, the first glyph. The game reads four tables:

  BIG.tab, SMALL.tab     battle text; pictures big.tim and small.tim inside Language/Tims/FONTTIMS.MAD
                         (Big.bmp and Small.bmp are kept the same)
  CHARS2.tab             menu text; Chars2.bmp and its light and dark copies chars2L.bmp, chars2D.bmp
  chars3.tab             menu headings; Chars3.bmp

The English fonts hold the Latin letters, the symbols and 25 accented letters. Release 1.0.0 of the
translation painted 26 Russian letters over the Latin ones. Here the Latin letters are the English ones
again, and the 22 Russian letters that no Latin letter looks like take the records of the accented
letters (0x50-0x65). Most of them are the drawings of release 1.0.0; the ones it lacked are put together
from other glyphs of the same font (see new_glyphs).
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
FIRST_OWN = 0x50                      # record of Б, the first Russian letter with a record of its own
OWN = 'БГДЁЖЗИЙЛПУФЦЧШЩЪЫЬЭЮЯ'      # the same order as in text.py


def rec(ch):
    """Record number of an ASCII character or of a Russian letter with a record of its own."""
    return FIRST_OWN + OWN.index(ch) if ch in OWN else ord(ch) - 0x1F


# ---- files ---------------------------------------------------------------------------------------

def read_tab(path):
    data = Path(path).read_bytes()
    return [list(struct.unpack_from('<4H', data, i)) for i in range(0, len(data), 8)]


def write_tab(path, records):
    Path(path).write_bytes(b''.join(struct.pack('<4H', *r) for r in records))


def read_mad(path):
    """A .MAD package: name -> bytes, in file order."""
    data = Path(path).read_bytes()
    count = struct.unpack_from('<I', data, 16)[0] // 24
    out = {}
    for i in range(count):
        name, off, size = struct.unpack_from('<16sII', data, i * 24)
        out[name.split(b'\0')[0].decode()] = data[off:off + size]
    return out


def write_mad(path, entries):
    head, body = b'', b''
    for name, data in entries.items():
        head += struct.pack('<16sII', name.encode(), 24 * len(entries) + len(body), len(data))
        body += data
    Path(path).write_bytes(head + body)


def tim_image(tim):
    """A 4-bit PSX TIM -> palette image. The game takes CLUT colour 0 for transparent."""
    colours = struct.unpack_from('<H', tim, 0x10)[0]
    assert colours == 16, 'only 4-bit TIMs'
    clut = struct.unpack_from('<16H', tim, 0x14)
    img = 0x14 + 32
    w16, h = struct.unpack_from('<HH', tim, img + 8)
    w = w16 * 4
    pix = bytearray()
    for b in tim[img + 12:img + 12 + w * h // 2]:
        pix += bytes((b & 15, b >> 4))
    im = Image.frombytes('P', (w, h), bytes(pix))
    pal = []
    for c in clut:
        pal += [(c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3]
    im.putpalette(pal + [0] * (768 - len(pal)))
    return im


def tim_with(tim, im):
    """The TIM with the pixels of a palette image of the same size and palette order."""
    img = 0x14 + 32
    pix = im.tobytes()
    packed = bytes(pix[i] | pix[i + 1] << 4 for i in range(0, len(pix), 2))
    assert len(packed) == len(tim) - img - 12
    return tim[:img + 12] + packed


def bmp_with(template, im):
    """The bytes of a palette BMP: header and palette of the template file, pixels of im (same size)."""
    data = Path(template).read_bytes()
    off = struct.unpack_from('<I', data, 10)[0]
    w, h, _, bpp = struct.unpack_from('<iiHH', data, 18)
    assert (w, h) == im.size and bpp in (4, 8)
    pix = im.tobytes()
    rows = []
    for y in range(h - 1, -1, -1):
        row = pix[y * w:(y + 1) * w]
        if bpp == 4:
            row = bytes(row[i] << 4 | row[i + 1] for i in range(0, w, 2))
        rows.append(row + b'\0' * (-len(row) % 4))
    return data[:off] + b''.join(rows)


def to_palette(im, like):
    """An RGB picture in the palette of the palette image `like`, each pixel its nearest colour."""
    pal = like.getpalette()
    count = len(pal) // 3
    used = sorted(set(like.tobytes())) or list(range(count))
    cache = {}
    out = bytearray()
    raw = im.convert('RGB').tobytes()
    for i in range(0, len(raw), 3):
        key = raw[i:i + 3]
        if key not in cache:
            r, g, b = key
            cache[key] = min(used, key=lambda i: (pal[3 * i] - r) ** 2 + (pal[3 * i + 1] - g) ** 2 + (pal[3 * i + 2] - b) ** 2)
        out.append(cache[key])
    res = Image.frombytes('P', im.size, bytes(out))
    res.putpalette(pal)
    return res


# ---- a font ---------------------------------------------------------------------------------------

class Font:
    def __init__(self, image, records):
        self.pal = image                      # the palette image as it was read
        self.rgb = image.convert('RGB')
        self.records = [list(r) for r in records]
        self.ox, self.oy = records[2][0], records[2][1]
        self.h = records[2][3]
        self.bg = self.rgb.getpixel((self.rgb.width - 1, self.rgb.height - 1))

    def glyph(self, n):
        x, y, w, h = self.records[n]
        return self.rgb.crop((x - self.ox, y - self.oy, x - self.ox + w, y - self.oy + h))


FONTS = {
    # name: (table, pictures; a name with a colon is a TIM inside FONTTIMS.MAD)
    'big': ('BIG.tab', ['tim:big.tim', 'Big.bmp']),
    'small': ('SMALL.tab', ['tim:small.tim', 'Small.bmp']),
    'chars2': ('CHARS2.tab', ['Chars2.bmp']),
    'chars2L': ('CHARS2.tab', ['chars2L.bmp']),
    'chars2D': ('CHARS2.tab', ['chars2D.bmp']),
    'chars3': ('chars3.tab', ['Chars3.bmp']),
}


def load(folder, name):
    folder = Path(folder)
    table, pictures = FONTS[name]
    first = pictures[0]
    if first.startswith('tim:'):
        image = tim_image(read_mad(folder / 'Language' / 'Tims' / 'FONTTIMS.MAD')[first[4:]])
    else:
        image = Image.open(folder / 'FEText' / first)
    return Font(image, read_tab(folder / 'FEText' / table))


# ---- glyphs as ink ----------------------------------------------------------------------------------
# A glyph is worked on as its ink: a list of rows (the line height of the font), a pixel is its colour
# or None. The battle fonts have a dark outline around the ink; it is left out here and drawn again by
# cell(), so a glyph put together from parts gets one outline. STYLE: the outline colour, the blank
# columns left and right of the ink in a cell, and the outline's shape.

STYLE = {
    'big': ((16, 8, 0), 2, 2, 'around'),      # 1 pixel all around, and the same again one pixel right and down
    'small': ((32, 32, 32), 1, 1, 'cross'),   # the 4 neighbours
}


def ink_of(font, name, n, trim=True):
    """Ink of record n. Returns (rows, left, right): the blank columns that were cut off at the sides."""
    edge = STYLE[name][0] if name in STYLE else None
    g = font.glyph(n)
    px = g.load()
    rows = [[None if px[x, y] in (font.bg, edge) else px[x, y] for x in range(g.width)] for y in range(g.height)]
    if not trim:
        return rows, 0, 0
    cols = [x for x in range(g.width) if any(r[x] for r in rows)]
    if not cols:
        return [[] for _ in rows], g.width, 0
    return [r[cols[0]:cols[-1] + 1] for r in rows], cols[0], g.width - 1 - cols[-1]


def width(m):
    return len(m[0])


def blank(h, w):
    return [[None] * w for _ in range(h)]


def paste(dst, src, x):
    for r, row in enumerate(src):
        for c, p in enumerate(row):
            if p is not None and 0 <= x + c < len(dst[r]):
                dst[r][x + c] = p


def hcat(a, b, gap=0):
    out = blank(len(a), width(a) + gap + width(b))
    paste(out, a, 0)
    paste(out, b, width(a) + gap)
    return out


def mirror(m):
    return [row[::-1] for row in m]


def span(m):
    rows = [r for r, row in enumerate(m) if any(p is not None for p in row)]
    return rows[0], rows[-1]


def runs(m, r):
    """The stretches of ink in row r: [(first column, last column)]."""
    out, start = [], None
    for x, p in enumerate(m[r] + [None]):
        if p is not None and start is None:
            start = x
        elif p is None and start is not None:
            out.append((start, x - 1))
            start = None
    return out


def full_rows(m):
    """Rows whose ink runs unbroken from the first column to the last: the bars of a letter."""
    return [r for r in range(len(m)) if runs(m, r) == [(0, width(m) - 1)]]


def middle(m):
    top, bottom = span(m)
    return (top + bottom) // 2


def cell(font, name, m, left, right):
    """The picture of a cell: the ink with `left` and `right` blank columns and the font's outline."""
    edge, _, _, shape = STYLE.get(name, (None, 0, 0, None))
    h, w = len(m), width(m) + left + right
    ink = blank(h, w)
    paste(ink, m, left)
    im = Image.new('RGB', (w, h), font.bg)
    px = im.load()

    def has(x, y):
        return 0 <= x < w and 0 <= y < h and ink[y][x] is not None

    for y in range(h):
        for x in range(w):
            if ink[y][x] is not None:
                px[x, y] = ink[y][x]
            elif shape == 'around':
                near = lambda cx, cy: any(has(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if near(x, y) or near(x - 1, y - 1):
                    px[x, y] = edge
            elif shape == 'cross':
                if has(x - 1, y) or has(x + 1, y) or has(x, y - 1) or has(x, y + 1):
                    px[x, y] = edge
    return im


# ---- the letters release 1.0.0 lacked -----------------------------------------------------------------

def yeru(soft, stem, gap):
    """Ы: Ь and a stem."""
    return hcat(soft, stem, gap)


def hard_sign(soft, te):
    """Ъ: Ь with the left end of the bar of Т."""
    bar = full_rows(te)
    stem = runs(te, middle(te))[0]
    arm = min(stem[0], stem[1] - stem[0] + 2)
    flag = blank(len(te), arm)
    for r in bar:
        flag[r] = te[r][:arm]
    return hcat(flag, soft)


def nub_of(tse):
    """The tail of Ц: what stands right of its right stem. None when it was drawn without one."""
    last = runs(tse, middle(tse))[-1][1]
    return [row[last + 1:] for row in tse] if last < width(tse) - 1 else None


def make_nub(sha):
    """A tail for a font whose Ц has none: the bottom bar goes on for two pixels and one row down."""
    bottom = span(sha)[1]
    nub = blank(len(sha), 2)
    for r in (bottom, bottom + 1):
        nub[r] = [sha[bottom][1]] * 2
    return nub


def de(el, sha, nub):
    """Д: Л on the bottom bar of Ш, with the tail of Ц at both ends."""
    w, n = width(el), width(nub)
    out = blank(len(el), w + 2 * n)
    paste(out, el, n)
    for r in full_rows(sha):
        if r >= middle(sha):
            for x in range(w):
                out[r][n + x] = sha[r][min(x, width(sha) - 1)]
    paste(out, nub, n + w)
    paste(out, mirror(nub), 0)
    return out


def squeeze(m, new_top):
    """The glyph with its top moved down to row new_top: rows are taken out evenly, the bottom stays."""
    top, bottom = span(m)
    k = new_top - top
    if k <= 0:
        return [row[:] for row in m]
    inner = list(range(top + 2, bottom - 1))
    drop = {inner[(i * 2 + 1) * len(inner) // (2 * k)] for i in range(k)}
    keep = [r for r in range(top, bottom + 1) if r not in drop]
    out = blank(len(m), width(m))
    for i, r in enumerate(reversed(keep)):
        out[bottom - i] = m[r][:]
    return out


def short_i(i, u_circumflex):
    """Й: И made lower, under the accent of the English U with circumflex turned upside down."""
    top = span(u_circumflex)[0]
    gap = next(r for r in range(top, len(u_circumflex)) if not runs(u_circumflex, r))
    body = next(r for r in range(gap, len(u_circumflex)) if runs(u_circumflex, r))
    accent = [u_circumflex[r] if top <= r < gap else [None] * width(u_circumflex) for r in range(len(u_circumflex))]
    cols = [x for x in range(width(accent)) if any(row[x] for row in accent)]
    accent = [row[cols[0]:cols[-1] + 1] for row in accent]
    accent[top:gap] = accent[top:gap][::-1]
    out = squeeze(i, body)
    paste(out, accent, (width(out) - width(accent)) // 2)
    return out


def reversed_e(c, e):
    """Э: the English C turned round, with the middle bar of E."""
    out = mirror(c)
    top, bottom = span(e)
    stem = min(r[0][1] - r[0][0] + 1 for r in (runs(e, y) for y in range(top, bottom + 1)) if r)
    for r in range(top + 2, bottom - 1):
        bar = runs(e, r)[0]
        if bar[1] - bar[0] + 1 > stem + 1 and runs(out, r):
            for x in range(width(out) // 2 - 1, runs(out, r)[-1][0]):
                out[r][x] = e[r][bar[0] + stem]
    return out


def che(en_h):
    """Ч: the English H without the lower half of its left stem."""
    out = [row[:] for row in en_h]
    right = runs(out, span(out)[0])[-1][0]
    for r in range(max(full_rows(out)) + 1, len(out)):
        out[r][:right] = [None] * right
    return out


def new_glyphs(name, en, old):
    """The ink of the 22 Russian letters with records of their own: {letter: (rows, left, right)}."""
    E = lambda ch: ink_of(en, name, rec(ch) if isinstance(ch, str) else ch)
    P = lambda ch: ink_of(old, name, rec(ch) if isinstance(ch, str) else ch)
    out = {ru: P(latin) for ru, latin in zip('БГЖИЛПУФЦШЬЮЯ', 'FJGNVUYQLWSZR')}
    sha, soft, el = out['Ш'][0], out['Ь'][0], out['Л'][0]
    sides = out['Ш'][1:]
    stems = runs(sha, middle(sha))
    out['З'] = E('3')
    out['Ё'] = E(0x59)
    out['Ы'] = (yeru(soft, E('I')[0], stems[1][0] - stems[0][1] - 1),) + sides
    out['Ъ'] = (hard_sign(soft, E('T')[0]),) + sides
    out['Й'] = (short_i(out['И'][0], E(0x66)[0]),) + out['И'][1:]
    nub = nub_of(out['Ц'][0])
    if nub is None:
        nub = make_nub(sha)
        out['Ц'] = (hcat(out['Ц'][0], nub),) + out['Ц'][1:]
    out['Щ'] = (hcat(sha, nub),) + sides
    if name == 'small':
        out['Д'] = P('D')                      # release 1.0.0 drew Д in this font only
    else:
        out['Д'] = (de(el, sha, nub),) + sides
    if name in ('big', 'small'):
        out['Э'] = (reversed_e(E('C')[0], E('E')[0]),) + E('C')[1:]
        out['Ч'] = (che(E('H')[0]),) + E('H')[1:]
    else:
        out['Э'], out['Ч'] = P(0x55), P(0x57)  # release 1.0.0 drew them in the menu fonts and never used them
    return out


# ---- build ------------------------------------------------------------------------------------------

def build_font(name, en, old):
    """The cells of the new font, by record: pictures as wide as the cell (None: an empty record)."""
    cells = [en.glyph(n) if r[2] and n < FIRST_OWN else None for n, r in enumerate(en.records)]
    for letter, (m, left, right) in new_glyphs(name, en, old).items():
        if name in STYLE:
            left, right = STYLE[name][1:3]
        cells[rec(letter)] = cell(en, name, m, left, right)
    return cells


def lay_out(font, cells):
    """Places the cells in rows from left to right. Returns the picture and the records."""
    for gap in (1, 0):
        records, x, y = [], 0, 0
        for n, c in enumerate(cells):
            if c is None:
                records.append([0, 0, 0, 0] if n < 2 else [font.ox, font.oy, 0, font.h])
                continue
            if x + c.width > font.rgb.width:
                x, y = 0, y + font.h
            records.append([font.ox + x, font.oy + y, c.width, font.h])
            x += c.width + gap
        if y + font.h <= font.rgb.height:
            break
    else:
        raise SystemExit('the glyphs do not fit into the picture')
    im = Image.new('RGB', font.rgb.size, font.bg)
    for c, r in zip(cells, records):
        if c is not None:
            im.paste(c, (r[0] - font.ox, r[1] - font.oy))
    return im, records


def build(old_folder, english_folder):
    old_folder, english_folder = Path(old_folder), Path(english_folder)
    fetext = ROOT / 'FEText'
    mad_path = ROOT / 'Language' / 'Tims' / 'FONTTIMS.MAD'
    mad = read_mad(english_folder / 'Language' / 'Tims' / 'FONTTIMS.MAD')
    tables = {}
    for name, (table, pictures) in FONTS.items():
        en, old = load(english_folder, name), load(old_folder, name)
        im, records = lay_out(en, build_font(name, en, old))
        if tables.setdefault(table, records) != records:
            raise SystemExit('%s: its glyphs are not as wide as those of the font it shares %s with' % (name, table))
        write_tab(fetext / table, records)
        for pic in pictures:
            if pic.startswith('tim:'):
                mad[pic[4:]] = tim_with(mad[pic[4:]], to_palette(im, en.pal))
            else:
                template = old_folder / 'FEText' / pic
                (fetext / pic).write_bytes(bmp_with(template, to_palette(im, Image.open(template))))
        if name == 'big':
            # Language/Tims/macfont.bmp is the big font once more, two rows higher
            template = old_folder / 'Language' / 'Tims' / 'macfont.bmp'
            mac = Image.new('RGB', Image.open(template).size, en.bg)
            mac.paste(im, (0, 0))
            (mad_path.parent / 'macfont.bmp').write_bytes(bmp_with(template, to_palette(mac, Image.open(template))))
        rows = (max(r[1] for r in records) - en.oy) // en.h + 1
        print('%-8s %d records, %d of %d rows used' % (name, len(records), rows, en.rgb.height // en.h))
    write_mad(mad_path, mad)


def check(english_folder):
    """How well cell() repeats the outline of the English battle fonts."""
    for name in STYLE:
        f = load(english_folder, name)
        bad = total = 0
        for n, r in enumerate(f.records):
            if r[2] and n < 0x3F:
                m, _, _ = ink_of(f, name, n, trim=False)
                a, b = cell(f, name, m, 0, 0).tobytes(), f.glyph(n).tobytes()
                total += len(a) // 3
                bad += sum(1 for i in range(0, len(a), 3) if a[i:i + 3] != b[i:i + 3])
        print('%s: %d of %d pixels differ' % (name, bad, total))


def sheet(folder, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in FONTS:
        f = load(folder, name)
        k = 4 if f.h <= 16 else 3
        cell_w = max(r[2] for r in f.records) * k + 8
        cell_h = f.h * k + 14
        per_row = 16
        rows = (len(f.records) + per_row - 1) // per_row
        im = Image.new('RGB', (cell_w * per_row, cell_h * rows), (40, 40, 70))
        d = ImageDraw.Draw(im)
        for n, r in enumerate(f.records):
            cx, cy = (n % per_row) * cell_w, (n // per_row) * cell_h
            d.text((cx + 2, cy), '%02X' % n, fill=(255, 220, 0))
            if r[2]:
                g = f.glyph(n)
                im.paste(g.resize((g.width * k, g.height * k), Image.NEAREST), (cx + 2, cy + 12))
        im.save(out / (name + '.png'))
        print(name, 'records', len(f.records), 'line height', f.h, 'picture', f.rgb.size)


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['sheet'] and len(args) == 3:
        sheet(args[1], args[2])
    elif args[:1] == ['build'] and len(args) == 3:
        build(args[1], args[2])
    elif args[:1] == ['check'] and len(args) == 2:
        check(args[1])
    else:
        raise SystemExit(__doc__)
