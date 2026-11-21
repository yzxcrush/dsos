"""Put a Ds script into the DSSCRIPT slot of a DsOS image (or a USB device).

Slot: LBA 630 (offset 322,560), 32 sectors = 16 KiB.
Format: b"DSSC" + little-endian u32 length + UTF-8 source, padded to a sector.

    python put_script.py hello.ds                  # writes into the image file
    python put_script.py hello.ds --device 1       # writes to \\\\.\\PhysicalDrive1
    python put_script.py --show                    # show what is currently in the slot
"""
import hashlib, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE = os.path.join(HERE, "dsos-x86_64-shell.img")
SLOT_LBA = 630
SLOT_OFF = SLOT_LBA * 512
SLOT_BYTES = 32 * 512
MAGIC = b"DSSC"


def build_slot(src: bytes) -> bytes:
    if len(src) + 8 > SLOT_BYTES:
        sys.exit(f"script too big: {len(src)} bytes (max {SLOT_BYTES - 8})")
    blob = MAGIC + struct.pack("<I", len(src)) + src
    return blob + b"\x00" * (SLOT_BYTES - len(blob))


def parse_slot(buf: bytes):
    if buf[:4] != MAGIC:
        return None
    n = struct.unpack("<I", buf[4:8])[0]
    if n > SLOT_BYTES - 8:
        return None
    return buf[8:8 + n]


def main():
    args = [a for a in sys.argv[1:]]
    if "--show" in args:
        buf = read_device_or_file()
        src = parse_slot(buf)
        if src is None:
            print("slot is empty (no DSSC magic)")
        else:
            print(f"{len(src)} bytes in slot:")
            print(src.decode("utf-8", "replace"))
        return

    device = None
    if "--device" in args:
        i = args.index("--device")
        device = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    src_path = args[0]
    src = open(src_path, "rb").read()
    slot = build_slot(src)

    if device is None:
        img = bytearray(open(IMAGE, "rb").read())
        if len(img) < SLOT_OFF + SLOT_BYTES:
            img += b"\x00" * (SLOT_OFF + SLOT_BYTES - len(img))
        img[SLOT_OFF:SLOT_OFF + SLOT_BYTES] = slot
        open(IMAGE, "wb").write(bytes(img))
        print(f"wrote {len(src)} bytes into the slot of {IMAGE}")
        print(f"image sha256 now: {hashlib.sha256(bytes(img)).hexdigest()}")
        return

    # raw device: guarded, sector-aligned write of just the slot
    dev = f"\\\\.\\PhysicalDrive{device}"
    with open(dev, "r+b", buffering=0) as f:
        f.seek(SLOT_OFF)
        f.write(slot)
        f.flush()
        os.fsync(f.fileno())
        f.seek(SLOT_OFF)
        back = f.read(SLOT_BYTES)
    ok = back == slot
    print(f"wrote slot to {dev} at offset {SLOT_OFF}")
    print(f"readback: {len(back)} bytes, match={ok}")
    if not ok:
        sys.exit(1)


def read_device_or_file():
    if "--device" in sys.argv:
        d = int(sys.argv[sys.argv.index("--device") + 1])
        with open(f"\\\\.\\PhysicalDrive{d}", "rb", buffering=0) as f:
            f.seek(SLOT_OFF)
            return f.read(SLOT_BYTES)
    with open(IMAGE, "rb") as f:
        f.seek(SLOT_OFF)
        return f.read(SLOT_BYTES)


if __name__ == "__main__":
    main()
