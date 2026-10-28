"""Чтение сейва No Man's Sky (.hg): чанки LZ4 → JSON → человекочитаемые ключи."""
import json
import struct
from pathlib import Path

MAGIC = 0xFEEDA1E5
MAPPING = Path(__file__).with_name("data") / "mapping.json"


def lz4_block(src: bytes, out_size: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        mlen = token & 15
        if mlen == 15:
            while True:
                b = src[i]; i += 1; mlen += b
                if b != 255:
                    break
        mlen += 4
        start = len(out) - off
        if off >= mlen:
            out += out[start:start + mlen]
        else:
            for k in range(mlen):
                out.append(out[start + k])
    if len(out) != out_size:
        raise ValueError(f"LZ4: ожидалось {out_size} байт, получено {len(out)}")
    return bytes(out)


def decompress(raw: bytes) -> bytes:
    if struct.unpack_from("<I", raw)[0] != MAGIC:
        return raw  # старый несжатый формат
    out, pos = bytearray(), 0
    while pos < len(raw):
        magic, csize, usize, _ = struct.unpack_from("<4I", raw, pos)
        if magic != MAGIC:
            raise ValueError(f"битый чанк на смещении {pos}")
        pos += 16
        out += lz4_block(raw[pos:pos + csize], usize)
        pos += csize
    return bytes(out).rstrip(b"\x00")


def load_mapping() -> dict:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    return {m["Key"]: m["Value"] for m in data["Mapping"]}


def deobfuscate(obj, mp):
    if isinstance(obj, dict):
        return {mp.get(k, k): deobfuscate(v, mp) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deobfuscate(v, mp) for v in obj]
    return obj


def load_save(path) -> dict:
    text = decompress(Path(path).read_bytes()).decode("utf-8", errors="replace")
    return deobfuscate(json.loads(text), load_mapping())
